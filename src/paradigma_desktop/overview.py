"""Concise recording-level metadata, without repeating pipeline bookkeeping."""
import json
import math

import numpy as np
from .availability import availability_views
from .results_view import MODULE_NAMES, clock_origin, clock_times, flat_values, readable_key


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
        step = float(np.median(steps)) if len(steps) else 0.
        offset = (bases or {}).get(key, 0.)
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
    for start, end in sorted(zip(frame.time, frame.end)):
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


def _hours(seconds):
    # Small example files must not appear to contain zero hours of data.
    value = f"{seconds / 3600:,.2f}" if seconds >= 36 else f"{seconds / 3600:.6f}".rstrip("0").rstrip(".")
    return value + " h"


def recording_summary(results, provenance, clock, prepared_views=None):
    metadata = results.get("metadata", {})
    sources = provenance.get("sources", {}) or ({"recording_001": provenance["source"]} if provenance.get("source") else {})
    entries = []
    bounds = _bounds(provenance)
    if bounds:
        entries.append(("Recording timespan", _timespan(bounds, clock, len(sources) > 1)))
    elif clock:
        entries.append(("Time origin", clock_origin(clock).strftime("%d %b %Y, %H:%M:%S")
                        + " · " + (clock.get("timezone") or "Time zone unspecified")))
    preparation = metadata.get("desktop_preparation", {})
    for path, value in flat_values(metadata.get("recording", {})):
        if path[-1] not in ("start_time", "end_time", "duration_s", "sampling_rate_hz"):
            continue
        if not bounds:
            entries.append((" · ".join(readable_key(key) for key in path), value))
    coverage, labels = (prepared_views if prepared_views is not None else
                        availability_views(results, provenance.get("display_offsets", {})))
    covered_labels = set()
    for name, frame in coverage.items():
        prefix = labels[(name, "available")].removesuffix(" input available")
        covered_labels.update(prefix.split(", "))
        title = lambda text: f"{prefix} · {text}" if prefix else text
        intervals = _interval_union(frame, bounds)
        seconds = sum(end - start for start, end in intervals)
        value = _hours(seconds)
        if bounds and bounds[1] > bounds[0]:
            value += f" · {100 * seconds / (bounds[1] - bounds[0]):.1f}% of timespan"
        else:
            value += " · Timespan unavailable"
        entries.append((title("Data coverage (prepared)"), value))
        entries.append((title("Gaps"), str(max(0, len(intervals) - 1))))
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
        for key, title in (("analyzed_samples", "Prepared samples"),
                           ("excluded_samples", "Excluded missing samples"), ("continuous_sections", "Prepared sections")):
            value = values.get(key)
            if coverage and key in ("analyzed_samples", "continuous_sections") and (
                    not prefix or all(module in covered_labels for module in group["modules"])):
                continue
            if value is not None and (key != "excluded_samples" or value):
                entries.append((f"{prefix} · {title}" if prefix else title, f"{value:,}" if isinstance(value, int) else value))
    return entries
