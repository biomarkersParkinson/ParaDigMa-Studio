"""Official file loading, preparation and analysis; compatible export aliases."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import logging
import re
import tempfile
from pathlib import Path
from typing import Any, TYPE_CHECKING

import numpy as np

from .serialization import (
    json_value as json_value,
    export_results as export_results,
    export_table_csv as export_table_csv,
)
from .availability import prepared_availability
from .empatica import load_empatica_imu
from .contracts import AnalysisResults, PathInput, Pipeline, SegmentArray, SensorInput

if TYPE_CHECKING:
    import pandas as pd

SUPPORTED = {".csv", ".parquet", ".pkl", ".pickle", ".json", ".avro", ".cwa"}
TIME_UNITS = {
    "relative_s",
    "relative_ms",
    "absolute_s",
    "absolute_ms",
    "difference_s",
    "difference_ms",
}


def load_single_data_file(*args: Any, **kwargs: Any) -> tuple[str, pd.DataFrame, datetime | None]:
    # ParaDigMa's package initializer imports every pipeline. Defer that work
    # until file loading/analysis, which the GUI already performs in a worker.
    from paradigma.load import load_single_data_file as official

    return official(*args, **kwargs)


def run_paradigma(*args: Any, **kwargs: Any) -> AnalysisResults:
    from paradigma.orchestrator import run_paradigma as official

    return official(*args, **kwargs)


def prepare_raw_data(*args: Any, **kwargs: Any) -> pd.DataFrame:
    from paradigma.prepare_data import prepare_raw_data as official

    return official(*args, **kwargs)


def correct_watch_orientation(*args: Any, **kwargs: Any) -> pd.DataFrame:
    from paradigma.prepare_data import correct_watch_orientation as official

    return official(*args, **kwargs)


def create_segments(*args: Any, **kwargs: Any) -> SegmentArray:
    from paradigma.segmenting import create_segments as official

    return official(*args, **kwargs)


def discard_segments(*args: Any, **kwargs: Any) -> pd.DataFrame:
    from paradigma.segmenting import discard_segments as official

    return official(*args, **kwargs)


def validate_column_mapping(mapping: object) -> dict[str, str]:
    mapping = {} if mapping is None else mapping
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
    ):
        raise ValueError("Column mapping must be a JSON object of source-to-target names.")
    return mapping


def validate_orientation(axes: object) -> list[str] | None:
    if axes is None:
        return None
    if (
        not isinstance(axes, (list, tuple))
        or len(axes) != 3
        or any(
            not isinstance(axis, str) or axis not in {"x", "y", "z", "-x", "-y", "-z"}
            for axis in axes
        )
        or sorted(axis[-1] for axis in axes) != ["x", "y", "z"]
    ):
        raise ValueError(
            "Device axes must contain x, y and z once each, optionally prefixed with '-'."
        )
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
                error = {
                    "pipeline": pipeline,
                    "stage": "pipeline_execution",
                    "error": message[len(prefix) :],
                }
                if error not in self.errors:
                    self.errors.append(error)


def load_sensor_file(path: PathInput, *, allow_pickle: bool = False) -> pd.DataFrame:
    import pandas as pd

    path = Path(path)
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError(f"Unsupported file format: {path.suffix}")
    if path.suffix.lower() in {".pkl", ".pickle"} and not allow_pickle:
        raise ValueError("Pickle loading is disabled unless the file is explicitly trusted.")
    if path.suffix.lower() == ".avro":
        frame = load_empatica_imu(path)
    else:
        _, frame, start = load_single_data_file(path)
        if start is not None:
            frame.attrs["desktop_recording_start"] = str(start)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("The sensor file contains no tabular samples.")
    return frame


def analyze(
    frame: SensorInput,
    *,
    pipelines: Pipeline | Sequence[Pipeline],
    column_mapping: dict[str, str] | None = None,
    logger: logging.Logger | None = None,
    drop_missing_samples: bool = False,
    **settings: Any,
) -> AnalysisResults:
    if isinstance(pipelines, str):
        pipelines = [pipelines]
    if not pipelines:
        raise ValueError("Select at least one analysis module.")
    if any(p not in {"gait", "tremor", "pulse_rate"} for p in pipelines):
        raise ValueError("Unknown pipeline. Choose gait, tremor or pulse_rate.")
    if "pulse_rate" in pipelines and len(pipelines) > 1:
        return _analyze_pipeline_groups(
            frame, pipelines, column_mapping, logger, drop_missing_samples, settings
        )
    inputs, exclusion, analyzed_samples, recordings = _prepare_analysis_inputs(
        frame, pipelines, column_mapping, logger, drop_missing_samples, settings
    )
    coverage = prepared_availability(inputs, pipelines)

    def run(output_dir):
        return _run_prepared_analysis(
            inputs,
            pipelines,
            logger,
            settings,
            output_dir,
            recordings,
            exclusion,
            analyzed_samples,
            coverage,
        )

    if "output_dir" in settings:
        return run(settings["output_dir"])
    # A unique directory prevents pre-created files/symlinks in a shared temp
    # folder from redirecting diagnostic writes; logs are removed after each run.
    with tempfile.TemporaryDirectory(prefix="paradigma-studio-") as directory:
        return run(directory)


def _analyze_pipeline_groups(
    frame, pipelines, column_mapping, logger, drop_missing_samples, settings
):
    groups = [[pipeline for pipeline in pipelines if pipeline != "pulse_rate"], ["pulse_rate"]]
    combined = {
        "quantifications": {},
        "classifications": {},
        "aggregations": {},
        "metadata": {},
        "errors": [],
    }
    preparation = {}
    for group in groups:
        (logger or logging.getLogger("paradigma")).info(
            "Running selected modules: %s", ", ".join(group)
        )
        try:
            output = analyze(
                frame,
                pipelines=group,
                column_mapping=column_mapping,
                logger=logger,
                drop_missing_samples=drop_missing_samples,
                **settings,
            )
        except Exception as exc:
            combined["errors"].append(
                {
                    "pipelines": group,
                    "stage": "desktop_execution",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            for pipeline in group:
                combined["aggregations"][pipeline] = {}
            (logger or logging.getLogger("paradigma")).error(
                "Modules %s failed: %s", ", ".join(group), exc
            )
            continue
        for category in ("quantifications", "classifications", "aggregations"):
            combined[category].update(output.get(category, {}))
        metadata = dict(output.get("metadata", {}))
        details = metadata.pop("desktop_preparation", None)
        if details:
            preparation.update({pipeline: dict(details) for pipeline in group})
        recording_details = metadata.pop("desktop_recordings", None)
        if recording_details:
            previous = combined["metadata"].get("desktop_recordings", {})
            combined["metadata"]["desktop_recordings"] = {
                **recording_details,
                "sections": {**previous.get("sections", {}), **recording_details["sections"]},
            }
        coverage = metadata.pop("desktop_availability", {})
        combined["metadata"].setdefault("desktop_availability", {}).update(coverage)
        combined["metadata"].update(metadata)
        combined["errors"].extend(output.get("errors", []))
    combined["metadata"]["desktop_preparation"] = {
        "analysis_groups": groups,
        "by_module": preparation,
    }
    return combined


def _prepare_analysis_inputs(
    frame, pipelines, column_mapping, logger, drop_missing_samples, settings
):
    """Prepare inputs and retain source/section identities for combined outputs."""
    import pandas as pd

    recordings = None
    if isinstance(frame, dict):
        if not frame or any(
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", key)
            or not isinstance(value, pd.DataFrame)
            for key, value in frame.items()
        ):
            raise ValueError(
                "Recordings must be a non-empty mapping of safe identifiers to sensor tables."
            )
        inputs, sections, preparation = {}, {}, {}
        for key, recording in frame.items():
            (logger or logging.getLogger("paradigma")).info(
                "Preparing recording %s (%s samples)", key, len(recording)
            )
            try:
                prepared, excluded, count = _prepare_recording(
                    recording,
                    pipelines,
                    column_mapping,
                    logger,
                    drop_missing_samples,
                    dict(settings),
                )
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{key}: {exc}") from exc
            pieces = prepared if isinstance(prepared, dict) else {"": prepared}
            for section, data in pieces.items():
                file_key = f"{key}__{section}" if section else key
                if file_key in inputs:
                    raise ValueError(
                        "Recording identifiers overlap with generated section identifiers."
                    )
                inputs[file_key], sections[file_key] = data, key
            preparation[key] = {
                **(excluded or {}),
                "input_samples": len(recording),
                "analyzed_samples": count,
                "continuous_sections": len(pieces),
            }
        recordings = {"recordings": list(frame), "sections": sections}
        exclusion = {
            "by_recording": preparation,
            "input_samples": sum(len(data) for data in frame.values()),
            "excluded_samples": sum(
                data.get("excluded_samples", 0) for data in preparation.values()
            ),
        }
        analyzed_samples = sum(data["analyzed_samples"] for data in preparation.values())
    else:
        inputs, exclusion, analyzed_samples = _prepare_recording(
            frame, pipelines, column_mapping, logger, drop_missing_samples, settings
        )
        exclusion = exclusion or {"input_samples": len(frame), "excluded_samples": 0}
    return inputs, exclusion, analyzed_samples, recordings


def _run_prepared_analysis(
    inputs,
    pipelines,
    logger,
    settings,
    output_dir,
    recordings,
    exclusion,
    analyzed_samples,
    coverage,
):
    import pandas as pd

    # Retain the official classification exports that 1.1.2 computes but
    # omits from its orchestrator return value. A fresh directory prevents
    # a failed run from reading a previous run's predictions.
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    run_directory = Path(tempfile.mkdtemp(prefix="run-", dir=output_dir))
    package_logger = logging.getLogger("paradigma")
    active_logger = (
        logger if logger is not None else logging.Logger("paradigma-studio-analysis", logging.INFO)
    )
    recorder = _PipelineFailures()
    loggers = {package_logger, active_logger}
    for target in loggers:
        target.addHandler(recorder)
    handlers_before = set(package_logger.handlers)
    try:
        results = run_paradigma(
            dfs=inputs,
            pipelines=pipelines,
            column_mapping=None,
            save_intermediate=["classification"],
            return_intermediate=["classification", "quantification"],
            custom_logger=active_logger,
            **{
                **settings,
                "output_dir": run_directory,
                "skip_preparation": True,
                "split_by_gaps": False,
            },
        )
        classifications, keys = _read_classification_outputs(
            run_directory, inputs, pipelines, recordings
        )
        results["classifications"] = classifications
        if recordings is not None and len(keys) == 1:
            for quantified in result_tables(results.get("quantifications", {})).values():
                if isinstance(quantified, pd.DataFrame) and "file_key" not in quantified:
                    quantified["file_key"] = keys[0]
        for error in recorder.errors:
            if error not in results.setdefault("errors", []):
                results["errors"].append(error)
        if exclusion:
            results.setdefault("metadata", {})["desktop_preparation"] = {
                **exclusion,
                "analyzed_samples": analyzed_samples,
                "continuous_sections": len(inputs) if isinstance(inputs, dict) else 1,
            }
        if recordings is not None:
            results.setdefault("metadata", {})["desktop_recordings"] = recordings
        results.setdefault("metadata", {})["desktop_availability"] = coverage
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


def _read_classification_outputs(run_directory, inputs, pipelines, recordings):
    """Read only official prediction files produced in this run's fresh directory."""
    import pandas as pd

    files = {
        "gait": {
            "detection": "gait_predictions.parquet",
            "arm_activity": "arm_activity_predictions.parquet",
        },
        "tremor": {"": "tremor_predictions.parquet"},
        "pulse_rate": {"": "ppg_quality_predictions.parquet"},
    }
    keys = list(inputs) if isinstance(inputs, dict) else ["df_1"]
    classifications = {}
    for pipeline in pipelines:
        for name, filename in files[pipeline].items():
            frames = []
            for key in keys:
                path = run_directory / "individual_files" / key / "classification" / filename
                if path.is_file():
                    classified = pd.read_parquet(path)
                    if len(keys) > 1 or recordings is not None:
                        classified["file_key"] = key
                    frames.append(classified)
            if frames:
                classified = pd.concat(frames, ignore_index=True)
                if name:
                    classifications.setdefault(pipeline, {})[name] = classified
                else:
                    classifications[pipeline] = classified
    return classifications, keys


def result_tables(value: Any, path: str = "") -> dict[str, pd.DataFrame]:
    """Flatten nested results, preserving filtered/unfiltered gait branches."""
    import pandas as pd

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


def _prepare_recording(frame, pipelines, column_mapping, logger, drop_missing_samples, settings):
    mapping = validate_column_mapping(column_mapping)
    axes = validate_orientation(settings.get("device_orientation", ["x", "y", "z"]))
    mapped = frame.rename(columns=mapping).copy().reset_index(drop=True)
    if not mapped.columns.is_unique:
        raise ValueError("Column mapping produces duplicate column names.")
    required, time_unit = _validate_required_channels(mapped, pipelines, settings)
    values, finite, invalid, excluded_count = _numeric_sensor_values(mapped, required)
    exclusion = None
    if excluded_count:
        mapped, values, time_unit, exclusion = _exclude_invalid_samples(
            frame,
            mapped,
            values,
            finite,
            invalid,
            excluded_count,
            time_unit,
            settings,
            logger,
            drop_missing_samples,
        )
    _validate_timeline(values, time_unit)

    # Pass the validated numeric values, rather than the original object columns.
    for column in required:
        mapped[column] = values[column]
    prepared = mapped
    if not settings.get("skip_preparation", False):
        prepared = _convert_recording(mapped, axes, time_unit, settings)
    inputs = _contiguous_recording_inputs(prepared)
    return inputs, exclusion, len(prepared)


def _validate_required_channels(mapped, pipelines, settings):
    import pandas as pd

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
        message = "Missing sensor columns: " + ", ".join(sorted(missing))
        if any(column.startswith("gyroscope_") for column in missing):
            message += ". Gait and tremor require gyroscope samples; an accelerometer-only recording cannot run these pipelines."
        if "green" in missing:
            message += ". Pulse rate requires raw green PPG; processed BVP is a different input."
        raise ValueError(message)
    if len(mapped) < 2:
        raise ValueError("At least two samples are required.")
    if pd.api.types.is_datetime64_any_dtype(
        mapped["time"].dtype
    ) or pd.api.types.is_timedelta64_dtype(mapped["time"].dtype):
        raise ValueError(
            "Time must use numeric seconds or milliseconds; convert datetime values before analysis."
        )
    time_unit = settings.get("time_input_unit", "relative_s")
    if time_unit not in TIME_UNITS:
        raise ValueError("Select a supported numeric time unit.")
    if settings.get("skip_preparation", False) and time_unit != "relative_s":
        raise ValueError(
            "Prepared data must use relative seconds. Enable preparation to convert time units."
        )
    return required, time_unit


def _numeric_sensor_values(mapped, required):
    import pandas as pd

    values = mapped[sorted(required)].apply(pd.to_numeric, errors="raise")
    if any(pd.api.types.is_complex_dtype(dtype) for dtype in values.dtypes):
        raise ValueError(
            "Required sensor channels must contain finite real numbers without missing values."
        )
    values = values.astype(float)
    finite = np.isfinite(values.to_numpy())
    invalid = ~finite.all(axis=1)
    excluded_count = int(invalid.sum())
    return values, finite, invalid, excluded_count


def _exclude_invalid_samples(
    frame,
    mapped,
    values,
    finite,
    invalid,
    excluded_count,
    time_unit,
    settings,
    logger,
    drop_missing_samples,
):
    """Remove invalid rows after converting a complete difference timeline.

    Update settings when differences become relative seconds and preserve
    section boundaries so subsequent preparation cannot interpolate over holes.
    """
    bad_columns = values.columns[~finite.all(axis=0)].tolist()
    if not drop_missing_samples:
        raise ValueError(
            "Required sensor channels must contain finite real numbers without missing values. "
            f"Found {excluded_count} affected samples in {', '.join(bad_columns)}. "
            "Enable 'Exclude missing sensor samples' to discard affected rows before analysis."
        )
    # Convert the complete difference timeline before removing sensor rows.
    if time_unit.startswith("difference"):
        if not np.isfinite(values["time"]).all():
            raise ValueError(
                "Missing time differences cannot be excluded; supply a valid relative or absolute timeline."
            )
        if values["time"].iloc[0] < 0 or not (values["time"].iloc[1:] > 0).all():
            raise ValueError(
                "Time differences must be positive after the first sample, which can be zero."
            )
        elapsed = values["time"].cumsum() - values["time"].iloc[0]
        values["time"] = elapsed / (1000 if time_unit == "difference_ms" else 1)
        time_unit = "relative_s"
        settings["time_input_unit"] = time_unit
    positions = np.flatnonzero(~invalid)
    if len(positions) < 2:
        raise ValueError(
            "At least two valid samples must remain after excluding missing sensor samples."
        )
    mapped = mapped.iloc[positions].copy().reset_index(drop=True)
    values = values.iloc[positions].reset_index(drop=True)
    boundaries = np.r_[True, np.diff(positions) > 1]
    if "data_segment_nr" in mapped:
        boundaries |= (
            mapped["data_segment_nr"]
            .ne(mapped["data_segment_nr"].shift())
            .fillna(True)
            .to_numpy(dtype=bool)
        )
    mapped["data_segment_nr"] = np.cumsum(boundaries)
    exclusion = {
        "input_samples": len(frame),
        "excluded_samples": excluded_count,
        "samples_after_exclusion": len(mapped),
        "invalid_columns": bad_columns,
        "split_at_excluded_samples": True,
    }
    (logger or logging.getLogger("paradigma")).info(
        "Excluded %s of %s samples with missing/non-finite values in %s; processing valid sections separately.",
        excluded_count,
        len(frame),
        ", ".join(bad_columns),
    )
    return mapped, values, time_unit, exclusion


def _validate_timeline(values, time_unit):
    if time_unit.startswith("difference"):
        if values["time"].iloc[0] < 0 or not (values["time"].iloc[1:] > 0).all():
            raise ValueError(
                "Time differences must be positive after the first sample, which can be zero."
            )
    else:
        if not values["time"].is_monotonic_increasing or not values["time"].is_unique:
            raise ValueError(
                "Time must be strictly increasing; remove duplicates or sort the file."
            )


def _convert_recording(mapped, axes, time_unit, settings):
    # Preparation is explicit because the pinned orchestrator ignores
    # accelerometer/orientation settings for some pipelines and passes None
    # as gap defaults. Continue to use the official preparation functions.
    prepared = prepare_raw_data(
        df=mapped,
        accelerometer_units=settings.get("accelerometer_units", "g"),
        gyroscope_units=settings.get("gyroscope_units", "deg/s"),
        time_input_unit=time_unit,
        device_orientation=None,
    )
    for sensor in ("accelerometer", "gyroscope"):
        if all(f"{sensor}_{axis}" in prepared for axis in "xyz"):
            prepared = correct_watch_orientation(prepared, device_orientation=axes, sensor=sensor)
    if settings.get("split_by_gaps", False):
        prepared = _split_recording_gaps(prepared, settings)
    return prepared


def _split_recording_gaps(prepared, settings):
    import pandas as pd

    max_gap = settings.get("max_gap_seconds")
    minimum = settings.get("min_segment_seconds")
    max_gap = 1.5 if max_gap is None else float(max_gap)
    minimum = 1.5 if minimum is None else float(minimum)
    if not np.isfinite(max_gap) or not np.isfinite(minimum) or max_gap <= 0 or minimum <= 0:
        raise ValueError("Gap and minimum segment durations must be positive finite seconds.")
    intervals = np.diff(prepared["time"].to_numpy())
    frequency = 1 / np.median(intervals)
    gaps = pd.Series(
        create_segments(prepared["time"].to_numpy(), max_segment_gap_s=max_gap),
        index=prepared.index,
    )
    boundaries = gaps.ne(gaps.shift())
    if "data_segment_nr" in prepared:
        boundaries |= (
            prepared["data_segment_nr"].ne(prepared["data_segment_nr"].shift()).fillna(True)
        )
    prepared["data_segment_nr"] = boundaries.cumsum()
    prepared = discard_segments(prepared, "data_segment_nr", minimum, frequency).reset_index(
        drop=True
    )
    return prepared


def _contiguous_recording_inputs(prepared):
    # The pinned preprocessing code otherwise interpolates across gaps even
    # when data_segment_nr is present. Give the orchestrator separate contiguous
    # frames so filtering and feature windows cannot bridge missing recordings.
    inputs = prepared
    if "data_segment_nr" in prepared:
        inputs = {
            f"segment_{i + 1}": group.reset_index(drop=True)
            for i, (_, group) in enumerate(
                prepared.groupby("data_segment_nr", sort=False, dropna=False)
            )
        }
    return inputs
