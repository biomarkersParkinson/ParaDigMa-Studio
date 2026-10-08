"""Local run metadata and safe reopening of explicitly exported JSON results."""
import json
import os
import re
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from .core import json_value
from .core import validate_column_mapping, validate_orientation


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run(source, settings):
    return {"id": uuid4().hex, "started": now(), "finished": None,
            "status": "Running", "source": source, "settings": settings,
            "paradigma_version": "", "warnings": [], "errors": [], "outputs": [], "log": ""}


def error_text(error):
    if isinstance(error, str):
        return error
    module = error.get("pipeline") or ", ".join(error.get("pipelines", []))
    context = " · ".join(str(value) for value in (module, error.get("stage"), error.get("file")) if value)
    return f"{context}: {error['error']}" if context else str(error["error"])


def failure_log(message):
    """ParaDigMa reports some pipeline failures at WARNING log level."""
    return any(message.startswith(f"{module} pipeline returned error: ")
               for module in ("gait", "tremor", "pulse_rate"))


def error_summary(message):
    return bool(re.fullmatch(r"ParaDigMa analysis completed with \d+ error\(s\)", message))


def run_status(record):
    status = record["status"]
    return "Completed with warnings" if status == "Completed" and record["warnings"] else status


def merge_errors(existing, errors):
    """Prefer structured pipeline errors over duplicate log messages."""
    messages = [error_text(error) for error in errors]
    details = [str(error.get("error", "")) if isinstance(error, dict) else error for error in errors]
    for message in existing:
        detail = message.split(" pipeline returned error: ", 1)[-1]
        if message.startswith("Modules ") and " failed: " in message:
            detail = message.split(" failed: ", 1)[1]
        if not any(detail and (detail in value or value in detail) for value in details):
            messages.append(message)
    return list(dict.fromkeys(messages))


def migrate_problems(record):
    """Recover errors saved in the warnings field by older app versions."""
    if "errors" in record:
        return
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
    record["errors"] = merge_errors([error for error in errors if isinstance(error, str)],
                                    [error for error in errors if isinstance(error, dict)])


class RunHistory:
    def __init__(self, directory):
        self.directory = Path(directory)

    def load(self):
        records, issues = [], []
        try:
            if not self.directory.exists():
                return records, issues
            paths = list(self.directory.glob("*.json"))
        except OSError as exc:
            return [], [f"Run history could not be read: {exc}"]
        for path in paths:
            try:
                if path.is_symlink():
                    raise ValueError("History entries must be regular files.")
                record = json.loads(path.read_text(encoding="utf-8"))
                if (not isinstance(record, dict) or not re.fullmatch(r"[0-9a-f]{32}", record.get("id", ""))
                        or path.stem != record["id"] or not isinstance(record.get("settings"), dict)
                        or not all(isinstance(record.get(key), str) for key in ("started", "status", "source"))
                        or not isinstance(record.get("outputs"), list) or not isinstance(record.get("warnings"), list)):
                    raise ValueError("Invalid run metadata.")
                settings = record["settings"]
                sources = record.get("sources", {})
                if not isinstance(sources, dict) or not all(isinstance(key, str) and isinstance(path, str)
                                                            for key, path in sources.items()):
                    raise ValueError("Invalid recording sources.")
                datetime.fromisoformat(record["started"])
                if record.get("finished") is not None:
                    datetime.fromisoformat(record["finished"])
                pipelines = settings.get("pipelines", [])
                if (not isinstance(pipelines, list) or not all(p in ("gait", "tremor", "pulse_rate") for p in pipelines)
                        or not all(isinstance(warning, str) for warning in record["warnings"])
                        or not isinstance(record.get("errors", []), list)
                        or not all(isinstance(error, str) for error in record.get("errors", []))
                        or not isinstance(record.get("log", ""), str)
                        or not all(isinstance(output, dict) and output.get("kind") in ("CSV", "JSON")
                                   and isinstance(output.get("path"), str) for output in record["outputs"])):
                    raise ValueError("Invalid run parameters or outputs.")
                migrate_problems(record)
                validate_column_mapping(settings.get("column_mapping"))
                validate_orientation(settings.get("device_orientation"))
                for key in ("max_gap_seconds", "min_segment_seconds"):
                    value = settings.get(key)
                    if value is not None and (isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0):
                        raise ValueError("Invalid gap duration.")
                for key in ("skip_preparation", "split_by_gaps", "drop_missing_samples"):
                    if key in settings and not isinstance(settings[key], bool):
                        raise ValueError("Invalid preparation setting.")
                if record["status"] == "Running":
                    record["status"] = "Unfinished"
                records.append(record)
            except (OSError, ValueError, TypeError) as exc:
                issues.append(f"Could not read run {path.name}: {exc}")
        return sorted(records, key=lambda record: record["started"], reverse=True), issues

    def save(self, record):
        if not re.fullmatch(r"[0-9a-f]{32}", record["id"]):
            raise ValueError("Invalid run identifier.")
        self.directory.mkdir(parents=True, exist_ok=True)
        public = {key: value for key, value in record.items() if not key.startswith("_")}
        fd, temporary = tempfile.mkstemp(prefix=".run-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(json_value(public), stream, indent=2, allow_nan=False)
            os.replace(temporary, self.directory / f"{record['id']}.json")
        finally:
            Path(temporary).unlink(missing_ok=True)

    def removal_files(self, record, records, protected_sources=(), removing=()):
        """Exports owned only by this run; never original inputs or directories."""
        if not re.fullmatch(r"[0-9a-f]{32}", record["id"]):
            raise ValueError("Invalid run identifier.")
        sources = list(protected_sources)
        for run in records:
            sources.extend([run["source"], *run.get("sources", {}).values()])
        protected = []
        for source in sources:
            if not source:
                continue
            path = Path(source)
            protected.append(path)
            if path.suffix.lower() == ".json":
                prefix = path.stem.replace("_meta", "")
                protected.extend(path.parent / f"{prefix}_{suffix}.bin" for suffix in ("time", "values"))
        deleting = {record["id"], *(run["id"] for run in removing)}
        shared = [Path(item["path"]) for run in records if run["id"] not in deleting for item in run["outputs"]]

        def same(first, second):
            return first.resolve() == second.resolve() or first.exists() and second.exists() and first.samefile(second)

        files = []
        for output in record["outputs"]:
            path = Path(output["path"])
            if (path.is_file() or path.is_symlink()) and not any(same(path, keep) for keep in [*protected, *shared, *files]):
                files.append(path)
        return files

    def remove(self, record, records, protected_sources=(), removing=()):
        files = self.removal_files(record, records, protected_sources, removing)
        for path in files:
            path.unlink(missing_ok=True)
        (self.directory / f"{record['id']}.json").unlink(missing_ok=True)
        return files


def load_result_export(path):
    """Read the wrapper's JSON export, never pickle or original sensor files."""
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(saved, dict) or not isinstance(saved.get("analysis"), dict) or not isinstance(saved.get("results"), dict):
        raise ValueError("This file is not a ParaDigMa result export.")
    sources = saved["analysis"].get("sources", {})
    if not isinstance(sources, dict) or not all(isinstance(key, str) and isinstance(path, str)
                                                for key, path in sources.items()):
        raise ValueError("Invalid recording sources in the result export.")

    def restore(value):
        if isinstance(value, dict):
            if set(value) == {"columns", "data"} and isinstance(value["columns"], list) and isinstance(value["data"], list):
                columns = value["columns"]
                if not all(isinstance(row, dict) for row in value["data"]):
                    raise ValueError("Malformed result table.")
                # JSON object keys are strings even when source column names
                # were numeric; preserve the original exported column labels.
                return pd.DataFrame([[row.get(str(column)) for column in columns]
                                     for row in value["data"]], columns=columns)
            return {key: restore(child) for key, child in value.items()}
        if isinstance(value, list):
            return [restore(child) for child in value]
        return value

    return saved["analysis"], restore(saved["results"])
