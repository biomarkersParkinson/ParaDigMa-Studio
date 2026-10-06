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
            "paradigma_version": "", "warnings": [], "outputs": [], "log": ""}


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
                datetime.fromisoformat(record["started"])
                if record.get("finished") is not None:
                    datetime.fromisoformat(record["finished"])
                pipelines = settings.get("pipelines", [])
                if (not isinstance(pipelines, list) or not all(p in ("gait", "tremor", "pulse_rate") for p in pipelines)
                        or not all(isinstance(warning, str) for warning in record["warnings"])
                        or not isinstance(record.get("log", ""), str)
                        or not all(isinstance(output, dict) and output.get("kind") in ("CSV", "JSON")
                                   and isinstance(output.get("path"), str) for output in record["outputs"])):
                    raise ValueError("Invalid run parameters or outputs.")
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


def load_result_export(path):
    """Read the wrapper's JSON export, never pickle or original sensor files."""
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(saved, dict) or not isinstance(saved.get("analysis"), dict) or not isinstance(saved.get("results"), dict):
        raise ValueError("This file is not a ParaDigMa result export.")

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
