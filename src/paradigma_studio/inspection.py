"""Read-only descriptives and display timelines; never alter analysis inputs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import tzinfo
from typing import TYPE_CHECKING, cast

import numpy as np

from .analysis_limits import inspection_worker_count
from .analysis_progress import AnalysisProgress, ProgressCallback
from .contracts import RecordingInspector
from .loading_progress import InspectionProgress

if TYPE_CHECKING:
    import logging

    import pandas as pd
    from numpy.typing import NDArray

    from .contracts import FloatArray, RecordingDescription

TIME_NAMES = {"time", "time_dt", "timestamp", "timestamps", "datetime", "date_time"}


def inspect_recordings(
    frames: dict[str, pd.DataFrame],
    time_unit: str,
    *,
    describe: RecordingInspector | None = None,
    logger: logging.Logger | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, RecordingDescription]:
    """Finish exact initial statistics for every recording before publishing any."""
    describe = describe or inspect_recording
    tracking = InspectionProgress(frames, progress) if progress is not None else None
    workers = inspection_worker_count(frames)
    if logger is not None:
        logger.info(
            "Preparing initial statistics for %s recordings using %s worker%s.",
            len(frames),
            workers,
            "s" if workers != 1 else "",
        )

    def inspect(item: tuple[str, pd.DataFrame]) -> RecordingDescription:
        key, frame = item
        if tracking is not None:
            return describe(frame, time_unit, progress=tracking.for_recording(key))
        return describe(frame, time_unit)

    if workers == 1:
        return {key: inspect((key, frame)) for key, frame in frames.items()}

    # NumPy's exact quantiles release the GIL. Share read-only frames between
    # two threads instead of copying large recordings to separate processes.
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="paradigma-inspection") as pool:
        return dict(zip(frames, pool.map(inspect, frames.items()), strict=True))


def input_plot_time(
    series: pd.Series, unit: str = "relative_s"
) -> tuple[pd.Series | None, str, tzinfo | None]:
    """Display absolute timestamps as dates and other time encodings as seconds.

    Match ParaDigMa's difference-time conversion: cumulative increments,
    including the first increment, expressed in seconds. Missing increments
    leave the elapsed timeline unknown instead of silently bridging them.
    """
    import pandas as pd

    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return series, "Recording date/time", series.dt.tz
    if pd.api.types.is_timedelta64_dtype(series.dtype):
        return series.dt.total_seconds(), "Elapsed time (s)", None
    if pd.api.types.is_complex_dtype(series.dtype):
        return None, "Sample position", None
    times = pd.to_numeric(series, errors="coerce")
    if unit.startswith("absolute"):
        try:
            calendar_times = pd.to_datetime(
                times, unit="ms" if unit.endswith("ms") else "s", errors="coerce", utc=True
            )
        except OverflowError:
            # Pandas can still raise on infinite/oversized floats with errors="coerce".
            return None, "Sample position", None
        return calendar_times, "Recording date/time", calendar_times.dt.tz
    if unit.startswith("difference"):
        values = times.to_numpy(dtype=float, na_value=np.nan)
        if not np.isfinite(values).all():
            return None, "Elapsed time (s)", None
        times = pd.Series(
            np.cumsum(values) / (1000 if unit.endswith("ms") else 1),
            index=series.index,
            name=series.name,
        )
    elif unit.endswith("ms"):
        times = times / 1000
    return times, "Elapsed time (s)", None


def default_time_column(frame):
    import pandas as pd

    for column in frame:
        if str(column).lower() == "time":
            return column
    for column in frame:
        if pd.api.types.is_datetime64_any_dtype(frame[column].dtype):
            return column
    return next((column for column in frame if str(column).lower() in TIME_NAMES), None)


def sensor_descriptives(frame, time_column):
    return _sensor_descriptives(frame, time_column, {})


def _sensor_descriptives(frame, time_column, missing_counts, progress=None):
    import pandas as pd

    records = []
    for index, column in enumerate(frame):
        if progress is not None:
            progress(index * 1000 // max(1, len(frame.columns)))
        series = frame[column]
        if (
            column == time_column
            or str(column).lower() in TIME_NAMES
            or (
                pd.api.types.is_datetime64_any_dtype(series.dtype)
                or pd.api.types.is_timedelta64_dtype(series.dtype)
            )
        ):
            continue
        record = {
            "Channel": str(column),
            "Type": str(series.dtype),
            "Missing": (
                missing_counts[column] if column in missing_counts else int(series.isna().sum())
            ),
            "Infinite": 0,
            "Range": "—",
            "Median": np.nan,
            "IQR": np.nan,
        }
        if pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_complex_dtype(
            series.dtype
        ):
            values = series.to_numpy(dtype=float, na_value=np.nan)
            record["Infinite"] = int(np.isinf(values).sum())
            finite_mask = np.isfinite(values)
            # Healthy channels need no filtered copy. Quantile keeps its own
            # workspace, so source samples remain unchanged in either branch.
            finite = values if finite_mask.all() else values[finite_mask]
            if len(finite):
                q1, median, q3 = np.quantile(finite, [0.25, 0.5, 0.75])
                record.update(
                    Range=f"{finite.min():.5g} – {finite.max():.5g}", Median=median, IQR=q3 - q1
                )
        records.append(record)
    report = pd.DataFrame(
        records, columns=["Channel", "Type", "Missing", "Infinite", "Range", "Median", "IQR"]
    )
    if progress is not None:
        progress(1000)
    return report


def time_descriptives(series: pd.Series, unit: str = "relative_s") -> pd.DataFrame:
    """Report cadence without bridging invalid timestamps or guessing units.

    Sampling rate is the inverse median positive interval. A descriptive gap is
    an interval >1.5 times that median, independent of analysis gap settings.
    Difference timelines with invalid deltas have an unknown total time span.
    """
    intervals, span, missing_samples = _time_intervals(series, unit)
    return _time_statistics(intervals, span, missing_samples)


def _time_intervals(series: pd.Series, unit: str) -> tuple[FloatArray, float, int]:
    """Interpret adjacent intervals and span in seconds, without bridging holes."""
    import pandas as pd

    valid: pd.Series | NDArray[np.bool_]
    if pd.api.types.is_datetime64_any_dtype(series.dtype) or pd.api.types.is_timedelta64_dtype(
        series.dtype
    ):
        valid = series.notna()
        # The dtype check above guarantees that differences are timedeltas.
        deltas = cast("pd.Series[pd.Timedelta]", series.diff())
        intervals = deltas.dt.total_seconds().to_numpy(dtype=float, na_value=np.nan)[1:]
        if valid.any():
            delta = series[valid].max() - series[valid].min()
            span = delta.total_seconds() + delta.nanoseconds / 1e9
        else:
            span = np.nan
    else:
        if unit not in {
            "relative_s",
            "relative_ms",
            "absolute_s",
            "absolute_ms",
            "difference_s",
            "difference_ms",
        }:
            raise ValueError("Select seconds or milliseconds for numeric time.")
        if pd.api.types.is_complex_dtype(series.dtype):
            values = np.full(len(series), np.nan)
        else:
            values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        valid = np.isfinite(values)
        values = np.where(valid, values, np.nan)
        scale = 0.001 if unit.endswith("ms") else 1.0
        if unit.startswith("difference"):
            intervals = values[1:] * scale
            span = intervals.sum() if valid.all() and np.all(intervals >= 0) else np.nan
        else:
            # Subtract before scaling to preserve precision in epoch times.
            intervals = np.diff(values) * scale
            span = (values[valid].max() - values[valid].min()) * scale if valid.any() else np.nan
    return intervals, span, int((~valid).sum())


def _time_statistics(intervals: FloatArray, span: float, missing_samples: int) -> pd.DataFrame:
    """Summarize interpreted intervals in the existing statistic order and units."""
    import pandas as pd

    finite_intervals = intervals[np.isfinite(intervals)]
    positive = finite_intervals[finite_intervals > 0]
    median = np.median(positive) if len(positive) else np.nan
    iqr = np.diff(np.quantile(positive, [0.25, 0.75]))[0] if len(positive) else np.nan
    gaps: FloatArray = positive[positive > 1.5 * median] if len(positive) else np.array([])
    gap_count = len(gaps) if len(positive) else np.nan
    longest_gap = (np.max(gaps) if len(gaps) else 0.0) if len(positive) else np.nan
    return pd.DataFrame(
        {
            "Statistic": [
                "Time span (s)",
                "Estimated sampling rate (Hz)",
                "Median interval (s)",
                "Interval IQR (s)",
                "Gaps (>1.5 × median interval)",
                "Longest gap interval (s)",
                "Missing / invalid time samples",
                "Zero-length intervals",
                "Backward intervals",
            ],
            "Value": [
                span,
                1 / median if median > 0 else np.nan,
                median,
                iqr,
                gap_count,
                longest_gap,
                missing_samples,
                int((finite_intervals == 0).sum()),
                int((finite_intervals < 0).sum()),
            ],
        }
    )


def inspect_recording(
    frame: pd.DataFrame, time_unit: str, *, progress: ProgressCallback | None = None
) -> RecordingDescription:
    column = default_time_column(frame)
    tracking = AnalysisProgress(progress) if progress is not None else None
    # Count each column once, including time/non-sensor columns in the total,
    # without constructing another full-table missingness mask.
    missing_counts = {}
    for index, name in enumerate(frame, 1):
        missing_counts[name] = int(frame[name].isna().sum())
        if tracking is not None:
            tracking.report(150 * index / max(1, len(frame.columns)))
    sensors = _sensor_descriptives(
        frame,
        column,
        missing_counts,
        progress=tracking.span(150, 800).report if tracking is not None else None,
    )
    report: RecordingDescription = {
        "time_column": column,
        "time_unit": time_unit,
        "missing": sum(missing_counts.values()),
        "sensors": sensors,
        "time": time_descriptives(frame[column], time_unit) if column is not None else None,
    }
    if tracking is not None:
        tracking.report(1000)
    return report
