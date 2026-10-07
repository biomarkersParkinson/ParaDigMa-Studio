"""Selection helpers shared by result graphs, summaries and tables."""
import numpy as np
import pandas as pd


PARTICIPANT_COLUMNS = ("participant_id", "participant", "subject_id", "subject", "patient_id")


def measurement_columns(frame):
    return [column for column in frame.select_dtypes(include=["number", "bool"]).columns
            if column != "time" and column not in PARTICIPANT_COLUMNS
            and not str(column).endswith(("_id", "_nr"))]


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


def select_rows(frame, *, participant_column=None, participant=None, segment=None,
                column=None, text="", minimum="", maximum=""):
    """Return a positional selection without altering scientific outputs."""
    mask = np.ones(len(frame), dtype=bool)
    if participant_column is not None and participant is not None:
        mask &= frame[participant_column].eq(participant).fillna(False).to_numpy(dtype=bool)
    if segment is not None and "file_key" in frame:
        mask &= frame["file_key"].eq(segment).fillna(False).to_numpy(dtype=bool)
    if text or minimum or maximum:
        if column is None or column not in frame:
            raise ValueError("Select a filter column first.")
        series = frame[column]
        if text:
            mask &= series.astype("string").str.contains(text, case=False, regex=False, na=False).to_numpy(dtype=bool)
        if minimum or maximum:
            if not pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_complex_dtype(series.dtype):
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
    positions = np.flatnonzero(mask)
    return frame.iloc[positions], positions


def source_timeline(frame, settings):
    """Align raw timestamps with the existing wrapper's analysis preparation.

    Sensor values remain in their original units. No signal preprocessing or
    derived window interpretation is performed for this contextual display.
    """
    from paradigma.util import transform_time_array

    mapped = frame.rename(columns=settings.get("column_mapping", {}))
    if "time" not in mapped or not mapped.columns.is_unique:
        raise ValueError("The original recording has no unambiguous time channel.")
    times = pd.to_numeric(mapped["time"], errors="raise").astype(float).reset_index(drop=True)
    if settings.get("skip_preparation", False):
        return times.to_numpy()
    unit = settings.get("time_input_unit", "relative_s")
    required = {"time"}
    for pipeline in settings.get("pipelines", []):
        if pipeline in ("gait", "tremor"):
            required.update(f"gyroscope_{axis}" for axis in "xyz")
        if pipeline in ("gait", "pulse_rate"):
            required.update(f"accelerometer_{axis}" for axis in "xyz")
        if pipeline == "pulse_rate":
            required.add("green")
    excluded = False
    valid = np.ones(len(frame), dtype=bool)
    if settings.get("drop_missing_samples", False) and required <= set(mapped.columns):
        values = mapped[sorted(required)].apply(pd.to_numeric, errors="raise").astype(float)
        valid = np.isfinite(values.to_numpy()).all(axis=1)
        excluded = not valid.all()
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
