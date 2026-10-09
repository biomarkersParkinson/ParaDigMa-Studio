"""Read-only descriptive statistics; never prepare or alter analysis inputs."""

import numpy as np
import pandas as pd


TIME_NAMES = {"time", "time_dt", "timestamp", "timestamps", "datetime", "date_time"}


def default_time_column(frame):
    for column in frame:
        if str(column).lower() == "time":
            return column
    for column in frame:
        if pd.api.types.is_datetime64_any_dtype(frame[column].dtype):
            return column
    return next((column for column in frame if str(column).lower() in TIME_NAMES), None)


def sensor_descriptives(frame, time_column):
    records = []
    for column in frame:
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
            "Missing": int(series.isna().sum()),
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
            finite = values[np.isfinite(values)]
            if len(finite):
                q1, median, q3 = np.quantile(finite, [0.25, 0.5, 0.75])
                record.update(
                    Range=f"{finite.min():.5g} – {finite.max():.5g}", Median=median, IQR=q3 - q1
                )
        records.append(record)
    return pd.DataFrame(
        records, columns=["Channel", "Type", "Missing", "Infinite", "Range", "Median", "IQR"]
    )


def time_descriptives(series, unit="relative_s"):
    """Report cadence without bridging invalid timestamps or guessing units.

    Sampling rate is the inverse median positive interval. A descriptive gap is
    an interval >1.5 times that median, independent of analysis gap settings.
    Difference timelines with invalid deltas have an unknown total time span.
    """
    if pd.api.types.is_datetime64_any_dtype(series.dtype) or pd.api.types.is_timedelta64_dtype(
        series.dtype
    ):
        valid = series.notna()
        intervals = series.diff().dt.total_seconds().to_numpy(dtype=float, na_value=np.nan)[1:]
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
    finite_intervals = intervals[np.isfinite(intervals)]
    positive = finite_intervals[finite_intervals > 0]
    median = np.median(positive) if len(positive) else np.nan
    iqr = np.diff(np.quantile(positive, [0.25, 0.75]))[0] if len(positive) else np.nan
    gaps = positive[positive > 1.5 * median] if len(positive) else np.array([])
    gap_count = len(gaps) if len(positive) else np.nan
    longest_gap = (gaps.max() if len(gaps) else 0.0) if len(positive) else np.nan
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
                int((~valid).sum()),
                int((finite_intervals == 0).sum()),
                int((finite_intervals < 0).sum()),
            ],
        }
    )


def inspect_recording(frame, time_unit):
    column = default_time_column(frame)
    return {
        "time_column": column,
        "time_unit": time_unit,
        "missing": int(frame.isna().sum().sum()),
        "sensors": sensor_descriptives(frame, column),
        "time": time_descriptives(frame[column], time_unit) if column is not None else None,
    }
