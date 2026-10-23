"""Local run metadata, complete result snapshots and safe JSON reopening."""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast, get_args
from uuid import uuid4

from .axis_mapping import preparation_orientations
from .column_mapping import validate_signal_columns
from .contracts import (
    AnalysisError,
    AnalysisResults,
    AnalysisSettings,
    OutputKind,
    PathInput,
    Provenance,
    RunOutput,
    RunRecord,
    RunStatus,
)
from .core import validate_column_mapping
from .result_integrity import (
    provenance_for_run,
    read_verified_text,
    validate_checksum,
    verify_run_id,
)
from .serialization import json_value
from .storage import atomic_file, recording_files, same_file


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_run(source: str, settings: AnalysisSettings) -> RunRecord:
    return {
        "id": uuid4().hex,
        "started": now(),
        "finished": None,
        "status": "Running",
        "source": source,
        "settings": settings,
        "paradigma_version": "",
        "warnings": [],
        "errors": [],
        "outputs": [],
        "log": "",
    }


def error_text(error: AnalysisError) -> str:
    if isinstance(error, str):
        return error
    module = error.get("pipeline") or ", ".join(error.get("pipelines", []))
    context = " · ".join(
        str(value) for value in (module, error.get("stage"), error.get("file")) if value
    )
    return f"{context}: {error['error']}" if context else str(error["error"])


def failure_log(message: str) -> bool:
    """ParaDigMa reports some pipeline failures at WARNING log level."""
    return any(
        message.startswith(f"{module} pipeline returned error: ")
        for module in ("gait", "tremor", "pulse_rate")
    )


def error_summary(message: str) -> bool:
    return bool(re.fullmatch(r"ParaDigMa analysis completed with \d+ error\(s\)", message))


def run_status(record: RunRecord) -> str:
    status = record["status"]
    return "Completed with warnings" if status == "Completed" and record["warnings"] else status


def saved_result_output(record: RunRecord) -> RunOutput | None:
    """Local snapshots are distinct from configurable user exports."""
    return next(
        (
            output
            for output in reversed(record["outputs"])
            if output.get("local") and output.get("kind") == "JSON"
        ),
        None,
    )


def run_is_saved(record: RunRecord) -> bool:
    output = saved_result_output(record)
    return output is not None and Path(output["path"]).is_file()


def run_exports(record: RunRecord) -> list[RunOutput]:
    return [output for output in record["outputs"] if not output.get("local")]


def merge_errors(existing: Iterable[str], errors: Sequence[AnalysisError]) -> list[str]:
    """Prefer structured pipeline errors over duplicate log messages."""
    messages = [error_text(error) for error in errors]
    details = [
        str(error.get("error", "")) if isinstance(error, dict) else error for error in errors
    ]
    for message in existing:
        detail = message.split(" pipeline returned error: ", 1)[-1]
        if message.startswith("Modules ") and " failed: " in message:
            detail = message.split(" failed: ", 1)[1]
        if not any(detail and (detail in value or value in detail) for value in details):
            messages.append(message)
    return list(dict.fromkeys(messages))


def migrate_problems(record: dict[str, Any]) -> None:
    """Recover errors saved in the warnings field by older app versions."""
    if "errors" in record:
        return
    errors: list[AnalysisError]
    warnings, errors, remaining = record["warnings"], [], []
    for message in warnings:
        if error_summary(message):
            continue
        try:
            value = json.loads(message)
        except (ValueError, TypeError):
            value = None
        if isinstance(value, dict) and "error" in value:
            errors.append(value)
        elif failure_log(message):
            errors.append(message)
        else:
            remaining.append(message)
    # Failed runs appended the terminal exception last; earlier messages
    # retain their original warning meaning.
    if record["status"] == "Failed" and remaining:
        errors.append(remaining.pop())
    record["warnings"] = remaining
    record["errors"] = merge_errors(
        [error for error in errors if isinstance(error, str)],
        [error for error in errors if isinstance(error, dict)],
    )


def _read_run_record(path: Path) -> RunRecord:
    if path.is_symlink():
        raise ValueError("History entries must be regular files.")
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(record, dict)
        or not isinstance(record.get("id"), str)
        or not re.fullmatch(r"[0-9a-f]{32}", record["id"])
        or path.stem != record["id"]
        or not isinstance(record.get("settings"), dict)
        or not all(isinstance(record.get(key), str) for key in ("started", "status", "source"))
        or not isinstance(record.get("outputs"), list)
        or not isinstance(record.get("warnings"), list)
    ):
        raise ValueError("Invalid run metadata.")
    # Caches are created from live frames/results, never restored from history JSON.
    record = {key: value for key, value in record.items() if not key.startswith("_")}
    if record["status"] not in get_args(RunStatus) or not isinstance(
        record.get("paradigma_version", ""), str
    ):
        raise ValueError("Invalid run status or version.")
    settings = record["settings"]
    sources = record.get("sources", {})
    if not isinstance(sources, dict) or not all(
        isinstance(key, str) and isinstance(path, str) for key, path in sources.items()
    ):
        raise ValueError("Invalid recording sources.")
    datetime.fromisoformat(record["started"])
    finished = record.get("finished")
    if finished is not None:
        if not isinstance(finished, str):
            raise ValueError("Invalid run completion time.")
        datetime.fromisoformat(finished)
    _validate_run_outputs(record, settings)
    migrate_problems(record)
    validate_column_mapping(settings.get("column_mapping"))
    validate_signal_columns(settings.get("signal_columns"))
    preparation_orientations(settings)
    _validate_preparation_settings(settings)
    record.setdefault("finished", None)
    record.setdefault("paradigma_version", "")
    record.setdefault("log", "")
    # All required fields and known optional fields are now validated/normalized.
    return cast(RunRecord, record)


def _validate_run_outputs(record: dict[str, Any], settings: AnalysisSettings) -> None:
    pipelines = settings.get("pipelines", [])
    if (
        not isinstance(pipelines, list)
        or not all(p in ("gait", "tremor", "pulse_rate") for p in pipelines)
        or not all(isinstance(warning, str) for warning in record["warnings"])
        or not isinstance(record.get("errors", []), list)
        or not all(isinstance(error, str) for error in record.get("errors", []))
        or not isinstance(record.get("log", ""), str)
    ):
        raise ValueError("Invalid run parameters or outputs.")
    for output in record["outputs"]:
        _validate_run_output(output)


def _validate_run_output(output: object) -> None:
    if (
        not isinstance(output, dict)
        or output.get("kind") not in get_args(OutputKind)
        or not isinstance(output.get("path"), str)
        or any(key in output and not isinstance(output[key], str) for key in ("saved", "dataset"))
        or any(key in output and not isinstance(output[key], bool) for key in ("local", "complete"))
    ):
        raise ValueError("Invalid run output.")
    if "sha256" in output:
        validate_checksum(output["sha256"])
    selected = output.get("selected", [])
    if not isinstance(selected, list) or not all(isinstance(name, str) for name in selected):
        raise ValueError("Invalid exported table selection.")
    rows = output.get("selected_rows", 0)
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise ValueError("Invalid exported row count.")
    if not isinstance(output.get("selection", {}), dict):
        raise ValueError("Invalid export selection metadata.")


def _validate_preparation_settings(settings):
    for key in ("max_gap_seconds", "min_segment_seconds"):
        value = settings.get(key)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("Invalid gap duration.")
    for key in ("skip_preparation", "split_by_gaps", "drop_missing_samples"):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError("Invalid preparation setting.")


class RunHistory:
    def __init__(self, directory: PathInput) -> None:
        self.directory = Path(directory)

    def load(self) -> tuple[list[RunRecord], list[str]]:
        records: list[RunRecord]
        issues: list[str]
        records, issues = [], []
        try:
            if not self.directory.exists():
                return records, issues
            paths = list(self.directory.glob("*.json"))
        except OSError as exc:
            return [], [f"Run history could not be read: {exc}"]
        for path in paths:
            try:
                record = _read_run_record(path)
                if record["status"] == "Running":
                    record["status"] = "Unfinished"
                records.append(record)
            except (OSError, ValueError, TypeError) as exc:
                issues.append(f"Could not read run {path.name}: {exc}")
        return sorted(records, key=lambda record: record["started"], reverse=True), issues

    def save(self, record: RunRecord) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", record["id"]):
            raise ValueError("Invalid run identifier.")
        self.directory.mkdir(parents=True, exist_ok=True)
        public = {key: value for key, value in record.items() if not key.startswith("_")}
        target = self.directory / f"{record['id']}.json"
        with atomic_file(target, prefix=".run-") as stream:
            json.dump(json_value(public), stream, indent=2, allow_nan=False)

    def save_results(
        self,
        record: RunRecord,
        results: AnalysisResults,
        provenance: Provenance,
        protected_sources: Iterable[PathInput] = (),
    ) -> list[RunOutput]:
        """Save complete outputs and their history link before reporting success."""
        from .serialization import export_results

        if not re.fullmatch(r"[0-9a-f]{32}", record["id"]):
            raise ValueError("Invalid run identifier.")
        protected_sources = tuple(protected_sources)
        directory = self.directory / "results"
        directory.mkdir(parents=True, exist_ok=True)
        # A new snapshot stays independent of the old history/checksum pair.
        # Only publish its link after both its write and the history update succeed.
        path = directory / f"{record['id']}-{uuid4().hex}.json"
        if path.exists():
            raise ValueError("A snapshot destination already exists; refusing to overwrite it.")
        checksum = export_results(
            path,
            results,
            provenance_for_run(provenance, record["id"]),
            protected_sources=[
                record["source"],
                *record.get("sources", {}).values(),
                *protected_sources,
            ],
        )
        output: RunOutput = {
            "kind": "JSON",
            "path": str(path.resolve()),
            "saved": now(),
            "dataset": "all results",
            "local": True,
            "complete": True,
            "sha256": checksum,
        }
        outputs = [item for item in record["outputs"] if not item.get("local")] + [output]
        history_saved = False
        try:
            self.save({**record, "outputs": outputs})
            history_saved = True
        finally:
            if not history_saved:
                path.unlink(missing_ok=True)
        self._remove_previous_snapshots(record, protected_sources)
        return outputs

    def _remove_previous_snapshots(
        self, record: RunRecord, protected_sources: Iterable[PathInput]
    ) -> None:
        directory = (self.directory / "results").resolve()
        protected = recording_files(
            [record["source"], *record.get("sources", {}).values(), *protected_sources]
        )
        for output in record["outputs"]:
            path = Path(output["path"])
            if not output.get("local") or not re.fullmatch(
                rf"{record['id']}-[0-9a-f]{{32}}\.json", path.name
            ):
                continue
            try:
                if (
                    not path.is_symlink()
                    and path.parent.resolve() == directory
                    and not any(same_file(path, source) for source in protected)
                ):
                    path.unlink(missing_ok=True)
            except OSError as exc:
                # The new snapshot/history pair is already committed and usable.
                logging.getLogger("paradigma").warning(
                    "Could not remove old snapshot %s: %s", path, exc
                )

    def validate_export_destination(self, path: PathInput, records: Iterable[RunRecord]) -> None:
        """An adjustable export must not replace a local snapshot or its history."""
        for record in records:
            saved = saved_result_output(record)
            protected = [
                self.directory / f"{record['id']}.json",
                self.directory / "results" / f"{record['id']}.json",
            ]
            if saved is not None:
                protected.append(Path(saved["path"]))
            if any(same_file(path, original) for original in protected):
                raise ValueError(
                    "An export cannot overwrite a saved run or its history entry. Choose another filename."
                )

    def removal_files(
        self,
        record: RunRecord,
        records: Sequence[RunRecord],
        protected_sources: Iterable[PathInput] = (),
        removing: Iterable[RunRecord] = (),
    ) -> list[Path]:
        """Exports owned only by this run; never original inputs or directories."""
        if not re.fullmatch(r"[0-9a-f]{32}", record["id"]):
            raise ValueError("Invalid run identifier.")
        sources = list(protected_sources)
        for run in records:
            sources.extend([run["source"], *run.get("sources", {}).values()])
        protected = recording_files(sources)
        deleting = {record["id"], *(run["id"] for run in removing)}
        shared = [
            Path(item["path"])
            for run in records
            if run["id"] not in deleting
            for item in run["outputs"]
        ]

        files: list[Path] = []
        for output in record["outputs"]:
            path = Path(output["path"])
            if (path.is_file() or path.is_symlink()) and not any(
                same_file(path, keep) for keep in [*protected, *shared, *files]
            ):
                files.append(path)
        return files

    def remove(
        self,
        record: RunRecord,
        records: Sequence[RunRecord],
        protected_sources: Iterable[PathInput] = (),
        removing: Iterable[RunRecord] = (),
    ) -> list[Path]:
        files = self.removal_files(record, records, protected_sources, removing)
        for path in files:
            path.unlink(missing_ok=True)
        (self.directory / f"{record['id']}.json").unlink(missing_ok=True)
        return files


def load_result_export(path: PathInput) -> tuple[Provenance, AnalysisResults]:
    """Decode an unassociated export; run reopening must use the verified reader."""
    return _decode_result_export(Path(path).read_text(encoding="utf-8"))


def load_verified_result_export(
    path: PathInput, run_id: str, checksum: object
) -> tuple[Provenance, AnalysisResults]:
    """Require both the recorded fingerprint and the selected run's identity."""
    provenance, results = _decode_result_export(read_verified_text(path, checksum))
    verify_run_id(provenance, run_id)
    return provenance, results


def _decode_result_export(text: str) -> tuple[Provenance, AnalysisResults]:
    import pandas as pd

    saved = json.loads(text)
    if (
        not isinstance(saved, dict)
        or not isinstance(saved.get("analysis"), dict)
        or not isinstance(saved.get("results"), dict)
    ):
        raise ValueError("This file is not a ParaDigMa result export.")
    sources = saved["analysis"].get("sources", {})
    if not isinstance(sources, dict) or not all(
        isinstance(key, str) and isinstance(path, str) for key, path in sources.items()
    ):
        raise ValueError("Invalid recording sources in the result export.")

    def restore(value):
        if isinstance(value, dict):
            if (
                set(value) == {"columns", "data"}
                and isinstance(value["columns"], list)
                and isinstance(value["data"], list)
            ):
                columns = value["columns"]
                if not all(isinstance(row, dict) for row in value["data"]):
                    raise ValueError("Malformed result table.")
                # JSON object keys are strings even when source column names
                # were numeric; preserve the original exported column labels.
                return pd.DataFrame(
                    [[row.get(str(column)) for column in columns] for row in value["data"]],
                    columns=columns,
                )
            return {key: restore(child) for key, child in value.items()}
        if isinstance(value, list):
            return [restore(child) for child in value]
        return value

    return saved["analysis"], restore(saved["results"])
