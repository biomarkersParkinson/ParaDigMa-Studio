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
from paradigma.prepare_data import correct_watch_orientation, prepare_raw_data
from paradigma.segmenting import create_segments, discard_segments

SUPPORTED = {".csv", ".parquet", ".pkl", ".pickle", ".json", ".avro", ".cwa"}
TIME_UNITS = {"relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"}


def validate_column_mapping(mapping):
    mapping = {} if mapping is None else mapping
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
    ):
        raise ValueError("Column mapping must be a JSON object of source-to-target names.")
    return mapping


def validate_orientation(axes):
    if axes is None:
        return None
    if not isinstance(axes, (list, tuple)) or len(axes) != 3 or any(
        not isinstance(axis, str) or axis not in {"x", "y", "z", "-x", "-y", "-z"} for axis in axes
    ) or sorted(axis[-1] for axis in axes) != ["x", "y", "z"]:
        raise ValueError("Device axes must contain x, y and z once each, optionally prefixed with '-'.")
    return list(axes)


class _PipelineFailures(logging.Handler):
    """Recover failures that ParaDigMa 1.1.2 logs but omits from results.errors."""
    def __init__(self):
        super().__init__(logging.WARNING)
        self.errors = []

    def emit(self, record):
        message = record.getMessage()
        for pipeline in ("tremor", "pulse_rate"):
            prefix = f"{pipeline} pipeline returned error: "
            if message.startswith(prefix):
                error = {"pipeline": pipeline, "stage": "pipeline_execution", "error": message[len(prefix):]}
                if error not in self.errors:
                    self.errors.append(error)


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
    if isinstance(pipelines, str):
        pipelines = [pipelines]
    if not pipelines or ("pulse_rate" in pipelines and len(pipelines) > 1):
        raise ValueError("Select gait/tremor, or pulse rate on its own.")
    if any(p not in {"gait", "tremor", "pulse_rate"} for p in pipelines):
        raise ValueError("Unknown pipeline. Choose gait, tremor or pulse_rate.")
    mapping = validate_column_mapping(column_mapping)
    axes = validate_orientation(settings.get("device_orientation", ["x", "y", "z"]))
    mapped = frame.rename(columns=mapping).copy().reset_index(drop=True)
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
    accelerometer_columns = {f"accelerometer_{axis}" for axis in "xyz"}
    if "pulse_rate" in pipelines and (
        not settings.get("skip_preparation", False) or accelerometer_columns <= set(mapped.columns)
    ):
        required.update(accelerometer_columns)
    missing = required - set(mapped.columns)
    if missing:
        raise ValueError("Missing sensor columns: " + ", ".join(sorted(missing)))
    if len(mapped) < 2:
        raise ValueError("At least two samples are required.")
    if pd.api.types.is_datetime64_any_dtype(mapped["time"].dtype) or pd.api.types.is_timedelta64_dtype(mapped["time"].dtype):
        raise ValueError("Time must use numeric seconds or milliseconds; convert datetime values before analysis.")
    values = mapped[list(required)].apply(pd.to_numeric, errors="raise")
    if any(pd.api.types.is_complex_dtype(dtype) for dtype in values.dtypes) or values.isna().any().any():
        raise ValueError("Required sensor channels must contain finite real numbers without missing values.")
    values = values.astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError("Required sensor channels must contain finite real numbers without missing values.")
    time_unit = settings.get("time_input_unit", "relative_s")
    if time_unit not in TIME_UNITS:
        raise ValueError("Select a supported numeric time unit.")
    if settings.get("skip_preparation", False) and time_unit != "relative_s":
        raise ValueError("Prepared data must use relative seconds. Enable preparation to convert time units.")
    if time_unit.startswith("difference"):
        if values["time"].iloc[0] < 0 or not (values["time"].iloc[1:] > 0).all():
            raise ValueError("Time differences must be positive after the first sample, which can be zero.")
    else:
        if not values["time"].is_monotonic_increasing or not values["time"].is_unique:
            raise ValueError("Time must be strictly increasing; remove duplicates or sort the file.")

    # Pass the validated numeric values, rather than the original object columns.
    for column in required:
        mapped[column] = values[column]
    prepared = mapped
    if not settings.get("skip_preparation", False):
        # Preparation is explicit because the pinned orchestrator ignores
        # accelerometer/orientation settings for some pipelines and passes None
        # as gap defaults. Continue to use the official preparation functions.
        prepared = prepare_raw_data(
            df=mapped, accelerometer_units=settings.get("accelerometer_units", "g"),
            gyroscope_units=settings.get("gyroscope_units", "deg/s"),
            time_input_unit=time_unit, device_orientation=None,
        )
        for sensor in ("accelerometer", "gyroscope"):
            if all(f"{sensor}_{axis}" in prepared for axis in "xyz"):
                prepared = correct_watch_orientation(prepared, device_orientation=axes, sensor=sensor)
        if settings.get("split_by_gaps", False):
            max_gap = settings.get("max_gap_seconds")
            minimum = settings.get("min_segment_seconds")
            max_gap = 1.5 if max_gap is None else float(max_gap)
            minimum = 1.5 if minimum is None else float(minimum)
            if not np.isfinite(max_gap) or not np.isfinite(minimum) or max_gap <= 0 or minimum <= 0:
                raise ValueError("Gap and minimum segment durations must be positive finite seconds.")
            intervals = np.diff(prepared["time"].to_numpy())
            frequency = 1 / np.median(intervals)
            prepared["data_segment_nr"] = create_segments(prepared["time"].to_numpy(), max_segment_gap_s=max_gap)
            prepared = discard_segments(prepared, "data_segment_nr", minimum, frequency).reset_index(drop=True)

    # The pinned preprocessing code otherwise interpolates across gaps even
    # when data_segment_nr is present. Give the orchestrator separate contiguous
    # frames so filtering and feature windows cannot bridge missing recordings.
    inputs = prepared
    if "data_segment_nr" in prepared:
        inputs = {f"segment_{i + 1}": group.reset_index(drop=True)
                  for i, (_, group) in enumerate(prepared.groupby("data_segment_nr", sort=False, dropna=False))}

    def run(output_dir):
        package_logger = logging.getLogger("paradigma")
        active_logger = logger if logger is not None else logging.Logger("paradigma-desktop-analysis", logging.INFO)
        recorder = _PipelineFailures()
        loggers = {package_logger, active_logger}
        for target in loggers:
            target.addHandler(recorder)
        handlers_before = set(package_logger.handlers)
        try:
            results = run_paradigma(
                dfs=inputs, pipelines=pipelines, column_mapping=None,
                save_intermediate=[], return_intermediate=["classification", "quantification"],
                custom_logger=active_logger, **{**settings, "output_dir": output_dir,
                                               "skip_preparation": True, "split_by_gaps": False},
            )
            for error in recorder.errors:
                if error not in results.setdefault("errors", []):
                    results["errors"].append(error)
            return results
        finally:
            for target in loggers:
                target.removeHandler(recorder)
            recorder.close()
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
    elif isinstance(value, list):
        if value:
            try:
                tables[path] = pd.DataFrame(value)
            except (ValueError, TypeError):
                tables[path] = pd.DataFrame({"value": [str(v) for v in value]})
    elif value is not None:
        tables[path] = pd.DataFrame({"value": [value]})
    return tables


def json_value(value):
    if isinstance(value, pd.DataFrame):
        return {"columns": [json_value(column) for column in value.columns],
                "data": json_value(value.to_dict(orient="records"))}
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, np.generic):
        return json_value(value.item())
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _write_export(path, writer, *, source=None):
    target = Path(path)
    if source:
        original = Path(source)
        originals = [original]
        if original.suffix.lower() == ".json":
            prefix = original.stem.replace("_meta", "")
            originals.extend(original.parent / f"{prefix}_{suffix}.bin" for suffix in ("time", "values"))
        for original_file in originals:
            same_file = target.resolve() == original_file.resolve()
            if target.exists() and original_file.exists():
                same_file = same_file or target.samefile(original_file)
            if same_file:
                raise ValueError("An export cannot overwrite the loaded sensor file or its companion binaries. Choose another filename.")
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
