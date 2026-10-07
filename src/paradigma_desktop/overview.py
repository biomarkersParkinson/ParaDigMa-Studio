"""Concise recording-level metadata, without repeating pipeline bookkeeping."""
import json
from pathlib import Path

from .results_view import MODULE_NAMES, clock_origin, flat_values, readable_key


def recording_summary(results, provenance, clock):
    metadata = results.get("metadata", {})
    recordings = metadata.get("desktop_recordings", {}).get("recordings", [])
    sources = provenance.get("sources", {}) or ({"recording_001": provenance["source"]} if provenance.get("source") else {})
    entries = []
    if recordings or sources:
        entries.append(("Recordings", len(recordings) or len(sources)))
    if sources:
        entries.append(("Files", " · ".join(Path(path).name for path in sources.values())))
    if clock:
        entries.append(("Time origin", clock_origin(clock).strftime("%d %b %Y, %H:%M:%S")
                        + " · " + (clock.get("timezone") or "Time zone unspecified")))
    preparation = metadata.get("desktop_preparation", {})
    for path, value in flat_values(metadata.get("recording", {})):
        if path[-1] not in ("input_samples", "n_samples", "start_time", "end_time", "duration_s", "sampling_rate_hz"):
            continue
        entries.append((" · ".join(readable_key(key) for key in path), value))
    if "input_samples" in preparation:
        entries.append(("Input samples", f"{preparation['input_samples']:,}"))
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
        for key, title in (("input_samples", "Input samples"), ("analyzed_samples", "Prepared samples"),
                           ("excluded_samples", "Excluded missing samples"), ("continuous_sections", "Prepared sections")):
            value = values.get(key)
            if key == "input_samples" and "input_samples" in preparation:
                continue
            if value is not None and (key != "excluded_samples" or value):
                entries.append((f"{prefix} · {title}" if prefix else title, f"{value:,}" if isinstance(value, int) else value))
    return entries
