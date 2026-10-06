"""File loading, analysis and lossless tabular result export."""
import json
import csv
import logging
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from paradigma.load import load_single_data_file
from paradigma.orchestrator import run_paradigma

SUPPORTED = {".csv", ".parquet", ".pkl", ".pickle", ".json", ".avro", ".cwa"}


def load_sensor_file(path, *, allow_pickle=False):
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError(f"Unsupported file format: {path.suffix}")
    if path.suffix.lower() in {".pkl", ".pickle"} and not allow_pickle:
        raise ValueError("Pickle loading is disabled unless the file is explicitly trusted.")
    _, frame, _ = load_single_data_file(path)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("The sensor file contains no tabular samples.")
    return frame


def analyze(frame, *, pipelines, column_mapping=None, logger=None, **settings):
    if not pipelines or ("pulse_rate" in pipelines and len(pipelines) > 1):
        raise ValueError("Select gait/tremor, or pulse rate on its own.")
    mapping = column_mapping or {}
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
    ):
        raise ValueError("Column mapping must be a JSON object of source-to-target names.")
    mapped = frame.rename(columns=mapping)
    if not mapped.columns.is_unique:
        raise ValueError("Column mapping produces duplicate column names.")
    required = {"time"}
    for pipeline in pipelines:
        if pipeline in ("gait", "tremor"):
            required.update(f"gyroscope_{axis}" for axis in "xyz")
        if pipeline == "gait":
            required.update(f"accelerometer_{axis}" for axis in "xyz")
        if pipeline == "pulse_rate":
            required.add("green")
    if "pulse_rate" in pipelines and not settings.get("skip_preparation", False):
        required.update(f"accelerometer_{axis}" for axis in "xyz")
    missing = required - set(mapped.columns)
    if missing:
        raise ValueError("Missing sensor columns: " + ", ".join(sorted(missing)))
    if len(mapped) < 2:
        raise ValueError("At least two samples are required.")
    values = mapped[list(required)].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError("Required sensor channels contain missing or infinite values.")
    if not settings.get("time_input_unit", "relative_s").startswith("difference"):
        if not (np.diff(values["time"]) > 0).all():
            raise ValueError("Time must be strictly increasing; remove duplicates or sort the file.")
    def run(output_dir):
        package_logger = logging.getLogger("paradigma")
        handlers_before = set(package_logger.handlers)
        try:
            return run_paradigma(
                dfs=frame.copy(), pipelines=pipelines, column_mapping=mapping,
                save_intermediate=[], return_intermediate=["classification", "quantification"],
                custom_logger=logger, **{**settings, "output_dir": output_dir},
            )
        finally:
            # Upstream may leave its diagnostic file open after an exception.
            for handler in list(package_logger.handlers):
                if handler not in handlers_before and isinstance(handler, logging.FileHandler):
                    package_logger.removeHandler(handler)
                    handler.close()

    if "output_dir" in settings:
        return run(settings["output_dir"])
    # A unique directory prevents pre-created files/symlinks in a shared temp
    # folder from redirecting diagnostic writes; logs are removed after each run.
    with tempfile.TemporaryDirectory(prefix="paradigma-desktop-") as directory:
        return run(directory)


def result_tables(value, path=""):
    """Flatten nested results, preserving filtered/unfiltered gait branches."""
    tables = {}
    if isinstance(value, pd.DataFrame):
        tables[path] = value
    elif isinstance(value, dict):
        if value and all(not isinstance(v, (dict, list, pd.DataFrame)) for v in value.values()):
            tables[path] = pd.DataFrame({"measure": list(value), "value": list(value.values())})
        else:
            for key, child in value.items():
                tables.update(result_tables(child, f"{path}/{key}".strip("/")))
    elif isinstance(value, list) and value:
        try:
            tables[path] = pd.DataFrame(value)
        except (ValueError, TypeError):
            tables[path] = pd.DataFrame({"value": [str(v) for v in value]})
    elif value is not None:
        tables[path] = pd.DataFrame({"value": [value]})
    return tables


def json_value(value):
    if isinstance(value, pd.DataFrame):
        return {"columns": list(value.columns), "data": json.loads(value.to_json(orient="records"))}
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, np.generic):
        return json_value(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _write_export(path, writer, *, source=None):
    target = Path(path)
    if source:
        original = Path(source)
        same_file = target.resolve() == original.resolve()
        if target.exists() and original.exists():
            same_file = same_file or target.samefile(original)
        if same_file:
            raise ValueError("An export cannot overwrite the loaded sensor file. Choose another filename.")
    # Write completely before replacing the chosen destination. A failed export
    # leaves any existing file intact and does not leave a partial output behind.
    fd, temporary = tempfile.mkstemp(prefix=".paradigma-export-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer(stream)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def export_results(path, results, provenance):
    _write_export(path, lambda stream: json.dump(
        {"analysis": provenance, "results": json_value(results)}, stream,
        indent=2, allow_nan=False), source=provenance.get("source"))


def _spreadsheet_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_table_csv(path, frame, *, source=None):
    """Neutralize formula-like text while retaining actual numeric values."""
    safe = frame.map(_spreadsheet_text)
    safe.columns = [_spreadsheet_text(str(column)) for column in frame.columns]
    _write_export(path, lambda stream: safe.to_csv(stream, index=False, quoting=csv.QUOTE_ALL),
                  source=source)
