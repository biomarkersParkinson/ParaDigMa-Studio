"""Concise recording-level metadata, without repeating pipeline bookkeeping."""

import json
import math
from typing import TYPE_CHECKING

import numpy as np

from .availability import availability_views
from .results_view import MODULE_NAMES, clock_origin, clock_times, flat_values, readable_key

if TYPE_CHECKING:
    from .contracts import AnalysisResults, Provenance


def _pulse_estimate_count(results: "AnalysisResults") -> int | None:
    value = results.get("metadata", {}).get("pulse_rate", {}).get("nr_pr_est")
    if value is None:
        import pandas as pd

        frame = results.get("quantifications", {}).get("pulse_rate")
        if isinstance(frame, pd.DataFrame) and "pulse_rate" in frame:
            return int(frame.pulse_rate.notna().sum())
        return None
    try:
        count = float(value)
        if math.isfinite(count) and count >= 0 and count.is_integer():
            return int(count)
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def pulse_estimate_availability(
    results: "AnalysisResults", provenance: "Provenance"
) -> tuple[int | None, int | None, float | None]:
    """Returned estimates per complete 2-second epoch of the full source extent.

    Retain gaps and excluded edges in the denominator. Never infer the original
    duration from the returned estimates or change official result metadata.
    """
    count = _pulse_estimate_count(results)
    bounds = _bounds(provenance)
    periods = (bounds[1] - bounds[0]) / 2 if bounds is not None else math.nan
    # Source timestamps can leave tiny roundoff at an exact epoch boundary.
    epochs = math.floor(periods + 1e-9) if math.isfinite(periods) else None
    percentage = count / epochs * 100 if count is not None and epochs else None
    return count, epochs, percentage


def recording_extent(timelines, bases=None):
    """Original source bounds in display seconds, including the last sample.

    Use every finite source timestamp, including rows excluded during preparation.
    Save these small bounds in provenance so an export needs no sensor-file access.
    """
    if timelines is None:
        return None
    groups = timelines if isinstance(timelines, dict) else {"recording": timelines}
    bounds = []
    for key, values in groups.items():
        times = np.asarray(values, dtype=float)
        finite = times[np.isfinite(times)]
        if not len(finite):
            continue
        steps = np.diff(times)
        steps = steps[np.isfinite(steps) & (steps > 0)]
        step = float(np.median(steps)) if len(steps) else 0.0
        offset = (bases or {}).get(key, 0.0)
        bounds.append((float(finite.min() + offset), float(finite.max() + step + offset)))
    if not bounds:
        return None
    return {"start_s": min(start for start, _ in bounds), "end_s": max(end for _, end in bounds)}


def _bounds(provenance):
    extent = provenance.get("recording_extent", {})
    try:
        start, end = float(extent["start_s"]), float(extent["end_s"])
        if math.isfinite(start) and math.isfinite(end) and end >= start:
            return start, end
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return None


def _interval_union(frame, bounds):
    """Elapsed coverage, rather than sample-count ratios or summed overlaps."""
    merged = []
    for start, end in sorted(zip(frame.time, frame.end, strict=False)):
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        if bounds:
            start, end = max(start, bounds[0]), min(end, bounds[1])
        if end <= start:
            continue
        # Ignore roundoff at section boundaries; retain real sub-second gaps.
        if merged and start <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def _timespan(bounds, clock, file_order=False):
    start, end = bounds
    if clock:
        origin = clock_origin(clock)
        dates = clock_times(bounds, clock)
        # Only repeat zone abbreviations when needed to distinguish DST times.
        changes_offset = origin.tz is not None and dates[0].utcoffset() != dates[1].utcoffset()
        pattern = "%d %b %Y, %H:%M:%S" + (" %Z" if changes_offset else "")
        zone = clock.get("timezone") or "Time zone unspecified"
        return " – ".join(date.strftime(pattern) for date in dates) + " · " + zone
    prefix = "File order" if file_order else "Elapsed"
    return f"{prefix}: {start:,.2f}–{end:,.2f} s · Absolute dates unavailable"


def _coverage_duration(seconds):
    days, remainder = divmod(seconds, 86400)
    # Small example files must not appear to contain zero hours of data.
    value = (
        f"{remainder / 3600:,.2f}"
        if remainder >= 36
        else f"{remainder / 3600:.6f}".rstrip("0").rstrip(".")
    )
    return f"{int(days):,} {'day' if days == 1 else 'days'} · {value} h"


def recording_summary(results, provenance, clock, prepared_views=None):
    metadata = results.get("metadata", {})
    sources = provenance.get("sources", {}) or (
        {"recording_001": provenance["source"]} if provenance.get("source") else {}
    )
    entries = []
    bounds = _bounds(provenance)
    if bounds:
        entries.append(("Recording timespan", _timespan(bounds, clock, len(sources) > 1)))
    elif clock:
        entries.append(
            (
                "Time origin",
                clock_origin(clock).strftime("%d %b %Y, %H:%M:%S")
                + " · "
                + (clock.get("timezone") or "Time zone unspecified"),
            )
        )
    preparation = metadata.get("desktop_preparation", {})
    for path, value in flat_values(metadata.get("recording", {})):
        if path[-1] not in ("start_time", "end_time", "duration_s", "sampling_rate_hz"):
            continue
        if not bounds:
            entries.append((" · ".join(readable_key(key) for key in path), value))
    coverage, labels = (
        prepared_views
        if prepared_views is not None
        else availability_views(results, provenance.get("display_offsets", {}))
    )
    coverage_entries, covered_labels = _coverage_entries(coverage, labels, bounds)
    entries.extend(coverage_entries)
    entries.extend(_preparation_entries(preparation, coverage, covered_labels))
    return entries


def _coverage_entries(coverage, labels, bounds):
    entries = []
    covered_labels = set()
    for name, frame in coverage.items():
        prefix = labels[(name, "available")].removesuffix(" input available")
        covered_labels.update(prefix.split(", "))

        def title(text, prefix=prefix):
            return f"{prefix} · {text}" if prefix else text

        intervals = _interval_union(frame, bounds)
        seconds = sum(end - start for start, end in intervals)
        value = _coverage_duration(seconds)
        if bounds and bounds[1] > bounds[0]:
            value += f" · {100 * seconds / (bounds[1] - bounds[0]):.1f}% of timespan"
        else:
            value += " · Timespan unavailable"
        entries.append((title("Data coverage"), value))
        entries.append((title("Gaps"), str(max(0, len(intervals) - 1))))
    return entries, covered_labels


def _preparation_entries(preparation, coverage, covered_labels):
    entries = []
    groups = preparation.get("by_module", {}) or {"": preparation}
    unique = {}
    for module, values in groups.items():
        key = json.dumps(values, sort_keys=True, default=str)
        group = unique.setdefault(key, {"modules": [], "values": values})
        if module:
            group["modules"].append(MODULE_NAMES.get(module, module))
    for group in unique.values():
        prefix = ", ".join(group["modules"])
        values = group["values"]
        for key, title in (
            ("analyzed_samples", "Prepared samples"),
            ("excluded_samples", "Excluded missing samples"),
            ("continuous_sections", "Prepared sections"),
        ):
            value = values.get(key)
            if (
                coverage
                and key in ("analyzed_samples", "continuous_sections")
                and (not prefix or all(module in covered_labels for module in group["modules"]))
            ):
                continue
            if value is not None and (key != "excluded_samples" or value):
                entries.append(
                    (
                        f"{prefix} · {title}" if prefix else title,
                        f"{value:,}" if isinstance(value, int) else value,
                    )
                )
    return entries
