"""File loading, analysis and lossless tabular result export."""
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from paradigma.load import load_single_data_file
from paradigma.orchestrator import run_paradigma

SUPPORTED = {".csv", ".parquet", ".pkl", ".pickle", ".json", ".avro", ".cwa"}


def load_sensor_file(path):
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError(f"Unsupported file format: {path.suffix}")
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
    settings.setdefault("output_dir", Path(tempfile.gettempdir()) / "paradigma-desktop-logs")
    return run_paradigma(
        dfs=frame.copy(), pipelines=pipelines, column_mapping=mapping,
        save_intermediate=[], return_intermediate=["classification", "quantification"],
        custom_logger=logger, **settings,
    )


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


def export_results(path, results, provenance):
    Path(path).write_text(json.dumps({"analysis": provenance, "results": json_value(results)},
                                    indent=2, allow_nan=False), encoding="utf-8")
