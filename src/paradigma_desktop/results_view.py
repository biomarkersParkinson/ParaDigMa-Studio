"""Presentation-only aggregate summaries and timelines for official results."""
import re
import numpy as np
import pandas as pd

from .core import result_tables
from .exploration import gait_context, measurement_columns, source_timeline


MODULE_NAMES = {"gait": "Gait", "tremor": "Tremor", "pulse_rate": "Pulse rate"}


def readable_key(key):
    match = re.fullmatch(r"(\d+)_(\d+|inf)", key)
    if match:
        low, high = match.groups()
        return f"{low}+ s" if high == "inf" else f"{low}–{high} s"
    text = key.replace("95p", "95th percentile").replace("cov", "CV").replace("_", " ")
    if key.endswith("_s"):
        text = text[:-2] + " (s)"
    return text[0].upper() + text[1:] if text else "Value"


def detail_tables(results):
    return {name: frame for category in ("classifications", "quantifications")
            for name, frame in result_tables(results.get(category, {}), category).items()
            if isinstance(frame, pd.DataFrame)}


def output_label(name):
    parts = name.split("/")
    module = MODULE_NAMES.get(parts[1], parts[1].replace("_", " ").title()) if len(parts) > 1 else name
    stage = "Classification" if parts[0] == "classifications" else "Quantification"
    branch = " · " + " / ".join(part.replace("_", " ").title() for part in parts[2:]) if len(parts) > 2 else ""
    return f"{module} · {stage}{branch}"


def plot_metrics(name, frame):
    metrics = measurement_columns(frame)
    if name.startswith("classifications/"):
        predictions = [column for column in metrics if str(column).startswith("pred_")
                       or "proba" in str(column) or "probability" in str(column)]
        return predictions or metrics
    return metrics


def preferred_metric(name, frame):
    metrics = plot_metrics(name, frame)
    return next((column for column in ("range_of_motion", "tremor_power", "pulse_rate", "heart_rate",
                "pred_gait_proba", "pred_tremor_proba", "pred_sqa_proba") if column in metrics),
                metrics[0] if metrics else None)


def detail_timing(results, name, frame):
    """Estimate gait display positions on the FULL output, before any filtering.

    These positions are never added to scientific output tables. Each swing is
    placed at a bin midpoint within its known segment, rather than pretending
    that segment boundaries are exact timestamps for the first/last swing.
    """
    times = np.full(len(frame), np.nan)
    starts, ends = times.copy(), times.copy()
    basis = np.full(len(frame), "Timing unavailable", dtype=object)
    if "time" in frame:
        times = pd.to_numeric(frame["time"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        basis[np.isfinite(times)] = "Toolbox timestamp"
    elif name.startswith("quantifications/gait/") and "gait_segment_nr" in frame:
        groups = ["gait_segment_nr"] + (["file_key"] if "file_key" in frame else [])
        for positions in frame.groupby(groups, sort=False, dropna=False).indices.values():
            context = gait_context(results, name, frame.iloc[positions[0]])
            if context is not None:
                start, end, _ = context
                times[positions] = start + (np.arange(len(positions)) + .5) / len(positions) * (end - start)
                starts[positions], ends[positions] = start, end
                basis[positions] = "Estimated within gait segment"
    return pd.DataFrame({"Analysis time (s)": times, "Time basis": basis,
                         "Segment start (s)": starts, "Segment end (s)": ends})


def recording_clock(frame, settings, timeline=None):
    """Return the clock at analysis second zero, keeping known timezone context."""
    if frame is None or frame.empty:
        return None
    try:
        timeline = source_timeline(frame, settings) if timeline is None else timeline
        mapped = frame.rename(columns=settings.get("column_mapping", {}))
        candidates = [column for column in frame if str(column).lower() in ("time_dt", "datetime", "timestamp")
                      or pd.api.types.is_datetime64_any_dtype(frame[column].dtype)]
        for column in candidates:
            if pd.api.types.is_numeric_dtype(frame[column].dtype):
                continue
            stamps = pd.to_datetime(frame[column], errors="coerce")
            valid = stamps.notna().to_numpy() & np.isfinite(timeline)
            if valid.any():
                index = np.flatnonzero(valid)[0]
                origin = stamps.iloc[index] - pd.to_timedelta(timeline[index], unit="s")
                return {"origin": origin.isoformat(), "source": str(column),
                        "timezone": str(origin.tz) if origin.tz is not None else None}
        unit = settings.get("time_input_unit", "relative_s")
        if unit.startswith("absolute") and not settings.get("skip_preparation", False):
            raw = pd.to_numeric(mapped["time"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
            valid = np.isfinite(raw) & np.isfinite(timeline)
            if valid.any():
                index = np.flatnonzero(valid)[0]
                origin = pd.to_datetime(raw[index], unit="ms" if unit.endswith("ms") else "s", utc=True)
                origin -= pd.to_timedelta(timeline[index], unit="s")
                return {"origin": origin.isoformat(), "source": unit, "timezone": "UTC"}
        start = frame.attrs.get("desktop_recording_start")
        if start is not None and np.isfinite(timeline[0]):
            origin = pd.Timestamp(start) - pd.to_timedelta(timeline[0], unit="s")
            return {"origin": origin.isoformat(), "source": "Recording metadata",
                    "timezone": str(origin.tz) if origin.tz is not None else None}
    except (ValueError, TypeError, KeyError, OverflowError):
        pass
    return None


def clock_times(times, clock):
    if clock is None:
        return np.asarray(times, dtype=float)
    return clock_origin(clock) + pd.to_timedelta(np.asarray(times, dtype=float), unit="s")


def clock_origin(clock):
    origin = pd.Timestamp(clock["origin"])
    if origin.tz is not None and clock.get("timezone"):
        origin = origin.tz_convert(clock["timezone"])
    return origin


def flat_values(value, prefix=()):
    """All aggregate leaves, plus compact non-segment metadata leaves."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key != "per_segment":
                yield from flat_values(child, (*prefix, str(key)))
    elif isinstance(value, pd.DataFrame):
        for index, row in value.iterrows():
            for key, child in row.items():
                yield (*prefix, str(index), str(key)), child
    elif isinstance(value, (list, tuple, np.ndarray)):
        yield prefix, ", ".join(map(str, value))
    else:
        yield prefix, value


def segment_summary(metadata):
    """Summarize each gait branch, never list individual segments in Overview."""
    summaries = {}
    for branch in ("filtered", "unfiltered"):
        segments = metadata.get(branch, {}).get("per_segment", {})
        durations = []
        for segment in segments.values():
            try:
                length = float(segment["duration_s"]) if "duration_s" in segment else float(segment["end_s"]) - float(segment["start_s"])
                if np.isfinite(length) and length >= 0:
                    durations.append(length)
            except (ValueError, TypeError, KeyError):
                pass
        summary = {"Segment count": len(segments), "Segments with valid duration": len(durations)}
        if durations:
            q1, median, q3 = np.quantile(durations, [.25, .5, .75])
            summary.update({"Total duration (s)": sum(durations), "Median duration (s)": median,
                            "Duration IQR (s)": q3 - q1,
                            "Duration range (s)": f"{min(durations):.5g} – {max(durations):.5g}"})
        summaries[branch] = summary
    return summaries


def time_bound(text, clock):
    if not text.strip():
        return None
    try:
        value = float(text)
    except ValueError:
        if clock is None:
            raise ValueError("Time bounds must be finite elapsed seconds.") from None
    else:
        if not np.isfinite(value):
            raise ValueError("Time bounds must be finite elapsed seconds.")
        return value
    if not re.match(r"^\d{4}-\d{2}-\d{2}", text.strip()):
        raise ValueError("Use a full ISO date/time or elapsed seconds.")
    origin, bound = clock_origin(clock), pd.Timestamp(text)
    if pd.isna(bound):
        raise ValueError("Enter a valid date/time.")
    if origin.tz is not None and bound.tz is None:
        try:
            bound = bound.tz_localize(origin.tz)
        except Exception as exc:
            raise ValueError("Ambiguous or invalid local time; include a timezone offset.") from exc
    if origin.tz is None and bound.tz is not None:
        raise ValueError("Use a time without a timezone for this recording's unspecified clock.")
    return (bound - origin).total_seconds()


def normalise_clock(clock):
    text = clock["origin"]
    if not isinstance(text, str) or not re.match(r"^\d{4}-\d{2}-\d{2}", text):
        raise ValueError("Use a full ISO date/time for the time origin.")
    stamp = pd.Timestamp(text).as_unit("ns")
    if pd.isna(stamp):
        raise ValueError("Enter a valid time origin.")
    if stamp.tz is not None and clock.get("timezone"):
        stamp = stamp.tz_convert(clock["timezone"])
    return {"origin": stamp.isoformat(), "source": str(clock.get("source", "Stored display clock")),
            "timezone": str(stamp.tz) if stamp.tz is not None else None}


def analysis_alignment(frame, settings, results, saved_offsets=None):
    """Calibrate independently prepared groups to one source-sample timeline.

    Different exclusions can move absolute-time zero in each official run.
    Offsets are for display only; each group's outputs retain their own time.
    """
    offsets = {}
    for module, value in (saved_offsets if isinstance(saved_offsets, dict) else {}).items():
        if module in MODULE_NAMES and isinstance(value, (int, float)) and np.isfinite(value):
            offsets[module] = float(value)
    if frame is None:
        return None, {}, offsets
    groups = results.get("metadata", {}).get("desktop_preparation", {}).get("analysis_groups")
    if not isinstance(groups, list):
        groups = [settings.get("pipelines", [])]
    timelines = {}
    common = None
    try:
        candidate = source_timeline(frame, settings)
        if np.isfinite(candidate).any():
            common = candidate
    except (ValueError, TypeError, KeyError, OverflowError):
        pass
    for group in groups:
        if not isinstance(group, list) or any(module not in MODULE_NAMES for module in group):
            continue
        try:
            timeline = source_timeline(frame, {**settings, "pipelines": group})
            if not np.isfinite(timeline).any():
                continue
            if common is None:
                common = timeline
            valid = np.isfinite(common) & np.isfinite(timeline)
            offset = float(common[np.flatnonzero(valid)[0]] - timeline[np.flatnonzero(valid)[0]]) if valid.any() else 0.
            for module in group:
                timelines[module], offsets[module] = timeline, offset
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return common, timelines, offsets
