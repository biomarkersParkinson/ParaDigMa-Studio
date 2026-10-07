"""Independent recordings sharing one subject and one analysis configuration."""
from pathlib import Path

import numpy as np
import pandas as pd

from .core import load_sensor_file
from .results_view import analysis_alignment, recording_clock, normalise_clock


def load_recordings(paths, *, allow_pickle=False, logger=None):
    sources, frames = {}, {}
    for index, path in enumerate(dict.fromkeys(map(str, paths)), start=1):
        key = f"recording_{index:03d}"
        if logger:
            logger.info("Loading %s: %s", key, path)
        try:
            frames[key] = load_sensor_file(path, allow_pickle=allow_pickle)
        except Exception as exc:
            raise ValueError(f"{Path(path).name}: {exc}") from exc
        sources[key] = path
    if not frames:
        raise ValueError("Select at least one sensor recording.")
    return sources, frames


def source_key(file_key, results):
    return results.get("metadata", {}).get("desktop_recordings", {}).get("sections", {}).get(file_key, file_key)


def timeline_offsets(name, frame, offsets):
    value = offsets.get(name.split("/")[1], 0.)
    if isinstance(value, dict):
        return frame["file_key"].map(value).fillna(0.).to_numpy(dtype=float) if "file_key" in frame else 0.
    return value


def align_recordings(frames, settings, results):
    """Display offsets only: never shift scientific timestamps or sensor values."""
    common, module_times, local_offsets, clocks = {}, {}, {}, {}
    for key, frame in frames.items():
        timeline, modules, offsets = analysis_alignment(frame, settings, results)
        if timeline is None:
            timeline = np.full(len(frame), np.nan)
        common[key], local_offsets[key] = timeline, offsets
        for module, times in modules.items():
            module_times.setdefault(module, {})[key] = times
        clocks[key] = recording_clock(frame, settings, timeline)
    clock, bases = None, {}
    available = [pd.Timestamp(value["origin"]) for value in clocks.values() if value is not None]
    if len(available) == len(frames) and len({stamp.tz is None for stamp in available}) == 1:
        origin = min(available)
        earliest = min(clocks, key=lambda key: pd.Timestamp(clocks[key]["origin"]))
        try:
            clock = normalise_clock({**clocks[earliest], "source": "Multiple recording clocks"})
        except (ValueError, KeyError, TypeError):
            # Parquet can restore a fixed-offset tz with a non-IANA type name.
            clock = normalise_clock({"origin": origin.isoformat(), "timezone": str(origin.tz) if origin.tz else None,
                                     "source": "Multiple recording clocks"})
        bases = {key: (pd.Timestamp(value["origin"]) - origin).total_seconds() for key, value in clocks.items()}
    else:
        # Without comparable clocks, use an explicitly labelled file-order
        # display. No absolute dates or between-recording gaps are inferred.
        cursor = 0.
        for key, times in common.items():
            finite = times[np.isfinite(times)]
            start, end = (finite.min(), finite.max()) if len(finite) else (0., 0.)
            steps = np.diff(times)
            steps = steps[np.isfinite(steps) & (steps > 0)]
            bases[key] = cursor - start
            cursor += end - start + (float(np.median(steps)) if len(steps) else 1.)
    sections = results.get("metadata", {}).get("desktop_recordings", {}).get("sections", {})
    offsets = {}
    for file_key, key in sections.items():
        for module in settings.get("pipelines", []):
            offsets.setdefault(module, {})[file_key] = bases.get(key, 0.) + local_offsets.get(key, {}).get(module, 0.)
    return common, module_times, offsets, clock, bases
