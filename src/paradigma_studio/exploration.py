"""Selection helpers shared by result graphs, summaries and tables."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SensorContext:
    """The initial view of one original recording and its selected Results time."""

    frame: object
    analysis_times: np.ndarray
    display_times: np.ndarray
    start: float
    end: float
    selected_time: float
    source_name: str = ""
    include_end: bool = True

    def positions(self):
        upper = (
            self.analysis_times <= self.end if self.include_end else self.analysis_times < self.end
        )
        return np.flatnonzero(
            np.isfinite(self.analysis_times) & (self.analysis_times >= self.start) & upper
        )


PARTICIPANT_COLUMNS = ("participant_id", "participant", "subject_id", "subject", "patient_id")


def measurement_columns(frame):
    return [
        column
        for column in frame.select_dtypes(include=["number", "bool"]).columns
        if column != "time"
        and column not in PARTICIPANT_COLUMNS
        and not str(column).endswith(("_id", "_nr"))
    ]


def gait_context(results, dataset, row):
    """Use explicit segment times; never invent per-arm-swing timestamps."""
    if not dataset.startswith("quantifications/gait/") or "gait_segment_nr" not in row:
        return None
    branch = dataset.rsplit("/", 1)[-1]
    segments = results.get("metadata", {}).get("gait", {}).get(branch, {}).get("per_segment", {})
    number = row["gait_segment_nr"]
    try:
        key = int(number)
        if key != number:
            return None
        metadata = segments.get(key, segments.get(str(key), {}))
        start, end = float(metadata["start_s"]), float(metadata["end_s"])
        if np.isfinite(start) and np.isfinite(end) and end > start:
            return start, end, key
    except (TypeError, ValueError, KeyError, OverflowError):
        pass
    return None


def select_rows(
    frame,
    *,
    participant_column=None,
    participant=None,
    segment=None,
    column=None,
    text="",
    minimum="",
    maximum="",
):
    """Return a positional selection without altering scientific outputs."""
    mask = np.ones(len(frame), dtype=bool)
    if participant_column is not None and participant is not None:
        mask &= frame[participant_column].eq(participant).fillna(False).to_numpy(dtype=bool)
    if segment is not None and "file_key" in frame:
        mask &= frame["file_key"].eq(segment).fillna(False).to_numpy(dtype=bool)
    if text or minimum or maximum:
        _apply_column_filter(frame, mask, column, text, minimum, maximum)
    positions = np.flatnonzero(mask)
    return frame.iloc[positions], positions


def _apply_column_filter(frame, mask, column, text, minimum, maximum):
    import pandas as pd

    if column is None or column not in frame:
        raise ValueError("Select a filter column first.")
    series = frame[column]
    if text:
        mask &= (
            series.astype("string")
            .str.contains(text, case=False, regex=False, na=False)
            .to_numpy(dtype=bool)
        )
    if minimum or maximum:
        if not pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_complex_dtype(
            series.dtype
        ):
            raise ValueError("Numeric bounds require a real numeric column.")
        low, high = None, None
        try:
            low = float(minimum) if minimum else None
            high = float(maximum) if maximum else None
        except ValueError as exc:
            raise ValueError("Filter bounds must be finite numbers.") from exc
        if any(v is not None and not np.isfinite(v) for v in (low, high)):
            raise ValueError("Filter bounds must be finite numbers.")
        if low is not None and high is not None and low > high:
            raise ValueError("The minimum cannot exceed the maximum.")
        if low is not None:
            mask &= series.ge(low).fillna(False).to_numpy(dtype=bool)
        if high is not None:
            mask &= series.le(high).fillna(False).to_numpy(dtype=bool)


def source_timeline(frame, settings):
    """Align raw timestamps with the existing wrapper's analysis preparation.

    Sensor values remain in their original units. No signal preprocessing or
    derived window interpretation is performed for this contextual display.
    """
    import pandas as pd
    from paradigma.util import transform_time_array

    mapped = frame.rename(columns=settings.get("column_mapping", {}), copy=False)
    if "time" not in mapped or not mapped.columns.is_unique:
        raise ValueError("The original recording has no unambiguous time channel.")
    times = pd.to_numeric(mapped["time"], errors="raise").astype(float).reset_index(drop=True)
    if settings.get("skip_preparation", False):
        return times.to_numpy()
    unit = settings.get("time_input_unit", "relative_s")
    valid, excluded = _timeline_valid_samples(mapped, settings)
    if not valid.any():
        raise ValueError("No valid sensor samples are available for this run.")
    if unit.startswith("difference"):
        if not np.isfinite(times).all():
            raise ValueError("Missing time differences prevent sensor alignment.")
        result = transform_time_array(times, unit, "relative_s")
        # The missing-sample adapter preserves the entire difference timeline
        # and subtracts its first delta before dropping sensor rows.
        if excluded:
            result = result - times.iloc[0] / (1000 if unit.endswith("ms") else 1)
        return result
    if unit.startswith("absolute"):
        # Official preparation starts at the first retained sample.
        times = times - times.iloc[np.flatnonzero(valid)[0]]
        return times.to_numpy() / (1000 if unit.endswith("ms") else 1)
    return np.asarray(transform_time_array(times, unit, "relative_s"))


def _timeline_valid_samples(mapped, settings):
    import pandas as pd

    required = {"time"}
    pipelines = settings.get("pipelines", [])
    for pipeline in pipelines:
        if pipeline in ("gait", "tremor"):
            required.update(f"gyroscope_{axis}" for axis in "xyz")
        if pipeline == "gait":
            required.update(f"accelerometer_{axis}" for axis in "xyz")
        if pipeline == "pulse_rate":
            required.add("green")
    accelerometer_columns = {f"accelerometer_{axis}" for axis in "xyz"}
    if "pulse_rate" in pipelines and accelerometer_columns <= set(mapped.columns):
        required.update(accelerometer_columns)
    excluded = False
    valid = np.ones(len(mapped), dtype=bool)
    if settings.get("drop_missing_samples", False) and required <= set(mapped.columns):
        # Work one channel at a time: a clock preview needs one validity mask,
        # not several full copies of a day-long sensor matrix.
        for column in sorted(required):
            values = pd.to_numeric(mapped[column], errors="raise").astype(float, copy=False)
            valid &= np.isfinite(values.to_numpy())
        excluded = not valid.all()
    return valid, excluded
