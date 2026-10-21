"""Presentation-only aggregate summaries and timelines for official results."""

import re
from functools import lru_cache

import numpy as np

from .core import result_tables
from .exploration import PARTICIPANT_COLUMNS, gait_context, measurement_columns, source_timeline

MODULE_NAMES = {"gait": "Gait", "tremor": "Tremor", "pulse_rate": "Pulse rate"}


@lru_cache(maxsize=2)
def gait_model_threshold(stage):
    from importlib.resources import files

    from paradigma.classification import ClassifierPackage

    asset = {
        "detection": "gait_detection_clf_package.pkl",
        "arm_activity": "gait_filtering_clf_package.pkl",
    }[stage]
    return float(ClassifierPackage.load(files("paradigma.assets") / asset).threshold)


def plot_tables(tables):
    """Add display-only gait window indicators; leave raw outputs untouched."""
    import pandas as pd

    plots, labels = dict(tables), {}
    for stage, probability, indicator, title in (
        ("detection", "pred_gait_proba", "pred_gait_window", "Gait presence"),
        (
            "arm_activity",
            "pred_no_other_arm_activity_proba",
            "pred_no_other_arm_activity_window",
            "Filtered gait presence",
        ),
    ):
        name = f"classifications/gait/{stage}"
        frame = tables.get(name)
        if frame is None or probability not in frame:
            continue
        threshold = gait_model_threshold(stage)
        values = pd.to_numeric(frame[probability], errors="coerce")
        view = frame.copy()
        view[indicator] = values.ge(threshold).astype(float).where(np.isfinite(values))
        plots[name] = view
        labels[(name, probability)] = f"{title} (probability)"
        labels[(name, indicator)] = f"{title} (prediction)"
    labels.update(_quantification_plot_labels(tables))
    return plots, labels


def _quantification_plot_labels(tables):
    labels = {}
    for branch in ("filtered", "unfiltered"):
        name = f"quantifications/gait/{branch}"
        frame = tables.get(name)
        if frame is not None:
            for metric, title in (
                ("range_of_motion", "Range of motion"),
                ("peak_velocity", "Peak velocity"),
            ):
                if metric in frame:
                    labels[(name, metric)] = f"{title} ({branch} gait)"
    module_labels = {
        "tremor": (
            ("pred_tremor_checked", "Tremor presence (prediction)"),
            ("pred_arm_at_rest", "Arm at rest (prediction)"),
            ("tremor_power", "Tremor power"),
        ),
        "pulse_rate": (
            ("pulse_rate", "Pulse rate"),
            ("pred_sqa_proba", "High-quality PPG (probability)"),
        ),
    }
    for name, frame in tables.items():
        for metric, title in module_labels.get(name.split("/")[1], ()):
            if metric in frame:
                labels[name, metric] = title
    return labels


def binary_interval_ends(name, frame, times):
    """Display each prediction until the next output update, capped at cadence.

    Use the complete output before filtering. Gaps and separate recordings do
    not extend positive states; overlapping analysis windows are displayed at
    their update cadence, rather than expanding every label to window length.
    """
    from paradigma.config import GaitConfig, PulseRateConfig, TremorConfig

    module = name.split("/")[1]
    if module == "tremor":
        default_step = TremorConfig().window_step_length_s
    elif module == "gait":
        step = "arm_activity" if name.endswith("/arm_activity") else "gait"
        default_step = GaitConfig(step=step).window_step_length_s
    elif module == "pulse_rate":
        config = PulseRateConfig()
        # Quality predictions update every second; quantified estimates use
        # the separate two-second pulse estimation interval.
        default_step = (
            config.pr_est_samples / config.ppg_sampling_frequency
            if name.startswith("quantifications/")
            else config.window_step_length_s
        )
    else:
        default_step = None
    times = np.asarray(times, dtype=float)
    ends = times.copy()
    keys = [
        column
        for column in (*PARTICIPANT_COLUMNS, "file_key", "data_segment_nr", "gait_segment_nr")
        if column in frame
    ]
    groups = (
        frame.groupby(keys, sort=False, dropna=False).indices.values()
        if keys
        else [np.arange(len(frame))]
    )
    for positions in groups:
        stamps = times[positions]
        gaps = np.diff(stamps)
        positive = gaps[np.isfinite(gaps) & (gaps > 0)]
        step = float(np.median(positive)) if len(positive) else default_step
        if step is None or not np.isfinite(step) or step <= 0:
            continue
        if default_step is not None:
            step = min(step, default_step)
        stops = stamps + step
        following = stamps[1:]
        stops[:-1] = np.where(
            np.isfinite(following) & (following > stamps[:-1]),
            np.minimum(stops[:-1], following),
            stops[:-1],
        )
        ends[positions] = stops
    return ends


def tremor_window_counts(frame):
    """Display the official resting-window denominator for the selected rows."""
    if not {"pred_tremor_checked", "pred_arm_at_rest"}.issubset(frame.columns):
        return None
    resting = frame.pred_arm_at_rest.eq(1).fillna(False)
    checked = frame.pred_tremor_checked.eq(1).fillna(False)
    count, denominator = int((checked & resting).sum()), int(resting.sum())
    return count, denominator, count / denominator * 100 if denominator else None


def tremor_overview_entries(results):
    """Selected official measures plus resting-window percentage for display.

    Power aggregates already use ParaDigMa's log10(power + 1) scale. Never
    transform them again or insert the derived rest percentage into outputs.
    """
    import pandas as pd

    aggregates = {
        path[-1]: (path, value)
        for path, value in flat_values(results.get("aggregations", {}).get("tremor", {}))
        if path
    }
    titles = {
        "perc_windows_tremor": "Percentage tremor during rest (%)",
        "median_tremor_power": "Median tremor power",
        "modal_tremor_power": "Modal tremor power",
        "90p_tremor_power": "90th percentile tremor power",
    }
    for key in aggregates:
        if key.endswith("_tremor_power") and key not in titles:
            titles[key] = readable_key(key)
    entries = []
    for key, title in titles.items():
        path, value = aggregates.get(key, ((key,), None))
        explanation = (
            "Checked tremor-positive windows ÷ resting/stable windows × 100."
            if key == "perc_windows_tremor"
            else "Official ParaDigMa aggregate of log10(tremor power + 1)."
        )
        entries.append(("Aggregates", path, title, value, explanation))
    metadata = results.get("metadata", {}).get("tremor", {})
    counts = {path[-1]: value for path, value in flat_values(metadata) if path}
    rest, total = counts.get("nr_windows_rest"), counts.get("nr_windows_total")
    if rest is None or total is None:
        # Older result exports may lack aggregate metadata but retain the exact
        # quantification rows used by the official resting-window denominator.
        frame = results.get("quantifications", {}).get("tremor")
        if isinstance(frame, pd.DataFrame) and "pred_arm_at_rest" in frame:
            rest, total = int(frame.pred_arm_at_rest.eq(1).sum()), len(frame)
    percentage = None
    try:
        rest, total = float(rest), float(total)
        if np.isfinite([rest, total]).all() and 0 <= rest <= total and total > 0:
            percentage = rest / total * 100
    except (TypeError, ValueError, OverflowError):
        pass
    entries.append(
        (
            "Metadata",
            ("percentage_arm_at_rest",),
            "Percentage arm at rest (%)",
            percentage,
            "Official resting/stable windows ÷ total quantified windows × 100.",
        )
    )
    return entries


def readable_key(key):
    if key == "perc_windows_tremor":
        return "Checked tremor / resting windows (%)"
    match = re.fullmatch(r"(\d+)_(\d+|inf)", key)
    if match:
        low, high = match.groups()
        return f"{low}+ s" if high == "inf" else f"{low}–{high} s"
    text = key.replace("95p", "95th percentile").replace("cov", "CV").replace("_", " ")
    if key.endswith("_s"):
        text = text[:-2] + " (s)"
    return text[0].upper() + text[1:] if text else "Value"


def detail_tables(results):
    import pandas as pd

    return {
        name: frame
        for category in ("classifications", "quantifications")
        for name, frame in result_tables(results.get(category, {}), category).items()
        if isinstance(frame, pd.DataFrame)
    }


def aggregation_tables(results):
    """Present each original aggregate dictionary as an ordered key/value table.

    Object-valued cells preserve integer precision and mixed scalar types;
    aggregates remain separate from time-filtered classifications/measurements.
    """
    import pandas as pd

    tables = {}

    def collect(value, path):
        if isinstance(value, pd.DataFrame):
            tables[path] = value
        elif isinstance(value, dict):
            if any(isinstance(child, dict) for child in value.values()):
                for key, child in value.items():
                    collect(child, f"{path}/{key}")
            else:
                tables[path] = pd.DataFrame(
                    {"measure": list(value), "value": pd.Series(list(value.values()), dtype=object)}
                )
        else:
            tables.update(result_tables(value, path))

    for module, value in results.get("aggregations", {}).items():
        collect(value, f"aggregations/{module}")
    return tables


def output_label(name):
    if name.startswith("preparation/"):
        return "Data coverage"
    parts = name.split("/")
    module = (
        MODULE_NAMES.get(parts[1], parts[1].replace("_", " ").title()) if len(parts) > 1 else name
    )
    stage = {
        "classifications": "Classification",
        "quantifications": "Quantification",
        "aggregations": "Aggregation",
    }.get(parts[0], parts[0].title())
    branch = (
        " · " + " / ".join(part.replace("_", " ").title() for part in parts[2:])
        if len(parts) > 2
        else ""
    )
    return f"{module} · {stage}{branch}"


def plot_metrics(name, frame):
    if name.startswith("preparation/"):
        return ["available"]
    metrics = measurement_columns(frame)
    if name.split("/")[1] == "tremor":
        metrics = [
            column
            for column in metrics
            if column not in ("pred_tremor_proba", "pred_tremor_logreg")
        ]
    if name.startswith("quantifications/tremor"):
        metrics = [
            column
            for column in metrics
            if column not in ("pred_arm_at_rest", "pred_tremor_checked")
        ]
    if name.startswith("classifications/"):
        predictions = [
            column
            for column in metrics
            if str(column).startswith("pred_")
            or "proba" in str(column)
            or "probability" in str(column)
        ]
        return predictions or metrics
    return metrics


def preferred_metric(name, frame):
    metrics = plot_metrics(name, frame)
    return next(
        (
            column
            for column in (
                "range_of_motion",
                "tremor_power",
                "pulse_rate",
                "heart_rate",
                "pred_gait_proba",
                "pred_tremor_proba",
                "pred_sqa_proba",
            )
            if column in metrics
        ),
        metrics[0] if metrics else None,
    )


def detail_timing(results, name, frame):
    """Estimate gait display positions on the FULL output, before any filtering.

    These positions are never added to scientific output tables. Each swing is
    placed at a bin midpoint within its known segment, rather than pretending
    that segment boundaries are exact timestamps for the first/last swing.
    """
    import pandas as pd

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
                times[positions] = start + (np.arange(len(positions)) + 0.5) / len(positions) * (
                    end - start
                )
                starts[positions], ends[positions] = start, end
                basis[positions] = "Estimated within gait segment"
    return pd.DataFrame(
        {
            "Analysis time (s)": times,
            "Time basis": basis,
            "Segment start (s)": starts,
            "Segment end (s)": ends,
        }
    )


def recording_clock(frame, settings, timeline=None):
    """Return the clock at analysis second zero, keeping known timezone context."""
    import pandas as pd

    if frame is None or frame.empty:
        return None
    try:
        timeline = source_timeline(frame, settings) if timeline is None else timeline
        mapped = frame.rename(columns=settings.get("column_mapping", {}), copy=False)
        candidates = [
            column
            for column in frame
            if str(column).lower() in ("time_dt", "datetime", "timestamp")
            or pd.api.types.is_datetime64_any_dtype(frame[column].dtype)
        ]
        for column in candidates:
            if pd.api.types.is_numeric_dtype(frame[column].dtype):
                continue
            stamps = pd.to_datetime(frame[column], errors="coerce")
            valid = stamps.notna().to_numpy() & np.isfinite(timeline)
            if valid.any():
                index = np.flatnonzero(valid)[0]
                origin = stamps.iloc[index] - pd.to_timedelta(timeline[index], unit="s")
                return {
                    "origin": origin.isoformat(),
                    "source": str(column),
                    "timezone": str(origin.tz) if origin.tz is not None else None,
                }
        unit = settings.get("time_input_unit", "relative_s")
        if unit.startswith("absolute") and not settings.get("skip_preparation", False):
            raw = pd.to_numeric(mapped["time"], errors="coerce").to_numpy(
                dtype=float, na_value=np.nan
            )
            valid = np.isfinite(raw) & np.isfinite(timeline)
            if valid.any():
                index = np.flatnonzero(valid)[0]
                origin = pd.to_datetime(
                    raw[index], unit="ms" if unit.endswith("ms") else "s", utc=True
                )
                origin -= pd.to_timedelta(timeline[index], unit="s")
                return {"origin": origin.isoformat(), "source": unit, "timezone": "UTC"}
        start = frame.attrs.get("desktop_recording_start")
        if start is not None and np.isfinite(timeline[0]):
            origin = pd.Timestamp(start) - pd.to_timedelta(timeline[0], unit="s")
            return {
                "origin": origin.isoformat(),
                "source": "Recording metadata",
                "timezone": str(origin.tz) if origin.tz is not None else None,
            }
    except (ValueError, TypeError, KeyError, OverflowError):
        pass
    return None


def clock_times(times, clock):
    import pandas as pd

    if clock is None:
        return np.asarray(times, dtype=float)
    return clock_origin(clock) + pd.to_timedelta(np.asarray(times, dtype=float), unit="s")


def clock_origin(clock):
    import pandas as pd

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
    else:
        import pandas as pd

        if isinstance(value, pd.DataFrame):
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
                length = (
                    float(segment["duration_s"])
                    if "duration_s" in segment
                    else float(segment["end_s"]) - float(segment["start_s"])
                )
                if np.isfinite(length) and length >= 0:
                    durations.append(length)
            except (ValueError, TypeError, KeyError):
                pass
        summary = {"Segment count": len(segments), "Segments with valid duration": len(durations)}
        if durations:
            q1, median, q3 = np.quantile(durations, [0.25, 0.5, 0.75])
            summary.update(
                {
                    "Total duration (s)": sum(durations),
                    "Median duration (s)": median,
                    "Duration IQR (s)": q3 - q1,
                    "Duration range (s)": f"{min(durations):.5g} – {max(durations):.5g}",
                }
            )
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
    return _date_time_bound(text, clock)


def _date_time_bound(text, clock):
    import pandas as pd
    from pytz.exceptions import AmbiguousTimeError, NonExistentTimeError

    origin, bound = clock_origin(clock), pd.Timestamp(text)
    if pd.isna(bound):
        raise ValueError("Enter a valid date/time.")
    if origin.tz is not None and bound.tz is None:
        try:
            bound = bound.tz_localize(origin.tz)
        except (AmbiguousTimeError, NonExistentTimeError) as exc:
            raise ValueError("Ambiguous or invalid local time; include a timezone offset.") from exc
    if origin.tz is None and bound.tz is not None:
        raise ValueError("Use a time without a timezone for this recording's unspecified clock.")
    return (bound - origin).total_seconds()


def normalise_clock(clock):
    import pandas as pd

    text = clock["origin"]
    if not isinstance(text, str) or not re.match(r"^\d{4}-\d{2}-\d{2}", text):
        raise ValueError("Use a full ISO date/time for the time origin.")
    stamp = pd.Timestamp(text).as_unit("ns")
    if pd.isna(stamp):
        raise ValueError("Enter a valid time origin.")
    if stamp.tz is not None and clock.get("timezone"):
        stamp = stamp.tz_convert(clock["timezone"])
    return {
        "origin": stamp.isoformat(),
        "source": str(clock.get("source", "Stored display clock")),
        "timezone": str(stamp.tz) if stamp.tz is not None else None,
    }


def analysis_alignment(frame, settings, results, saved_offsets=None):
    """Calibrate independently prepared groups to one source-sample timeline.

    Different exclusions can move absolute-time zero in each official run.
    Offsets are for display only; each group's outputs retain their own time.
    """
    offsets = _saved_alignment_offsets(saved_offsets)
    if frame is None:
        return None, {}, offsets
    groups = results.get("metadata", {}).get("desktop_preparation", {}).get("analysis_groups")
    if not isinstance(groups, list):
        groups = [settings.get("pipelines", [])]
    timelines = {}
    common = _common_source_timeline(frame, settings)
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
            offset = (
                float(common[np.flatnonzero(valid)[0]] - timeline[np.flatnonzero(valid)[0]])
                if valid.any()
                else 0.0
            )
            for module in group:
                timelines[module], offsets[module] = timeline, offset
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return common, timelines, offsets


def _saved_alignment_offsets(saved_offsets):
    offsets = {}
    for module, value in (saved_offsets if isinstance(saved_offsets, dict) else {}).items():
        if module in MODULE_NAMES and isinstance(value, (int, float)) and np.isfinite(value):
            offsets[module] = float(value)
        elif module in MODULE_NAMES and isinstance(value, dict):
            offsets[module] = {
                key: float(offset)
                for key, offset in value.items()
                if isinstance(key, str) and isinstance(offset, (int, float)) and np.isfinite(offset)
            }
    return offsets


def _common_source_timeline(frame, settings):
    common = None
    try:
        candidate = source_timeline(frame, settings)
        if np.isfinite(candidate).any():
            common = candidate
    except (ValueError, TypeError, KeyError, OverflowError):
        pass
    return common
