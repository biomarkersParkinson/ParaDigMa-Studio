"""Compact coverage of the actual prepared frames handed to the toolbox."""

import json

import numpy as np


def prepared_availability(inputs, pipelines):
    frames = inputs if isinstance(inputs, dict) else {"df_1": inputs}
    sections = {}
    for key, frame in frames.items():
        times = frame["time"].to_numpy(dtype=float)
        positive = np.diff(times)
        positive = positive[np.isfinite(positive) & (positive > 0)]
        step = float(np.median(positive)) if len(positive) else 0.0
        boundaries = np.r_[0, np.flatnonzero(np.diff(times) > step * 1.5) + 1]
        lasts = np.r_[boundaries[1:] - 1, len(times) - 1]
        intervals = (
            np.column_stack((times[boundaries], times[lasts] + step)).tolist() if len(times) else []
        )
        sections[key] = {"samples": len(frame), "sample_interval_s": step, "intervals": intervals}
    return dict.fromkeys(pipelines, sections)


def availability_views(results, offsets):
    """Group identical prepared inputs; dates/offsets remain display-only."""
    from .recordings import timeline_offsets
    from .results_view import MODULE_NAMES

    groups = {}
    for module, sections in results.get("metadata", {}).get("desktop_availability", {}).items():
        import pandas as pd

        rows = [
            {"time": start, "end": end, "available": 1.0, "file_key": key}
            for key, section in sections.items()
            for start, end in section.get("intervals", [])
        ]
        frame = pd.DataFrame(rows, columns=["time", "end", "available", "file_key"])
        shift = timeline_offsets(f"preparation/{module}", frame, offsets)
        frame["time"] += shift
        frame["end"] += shift
        signature = json.dumps(frame.to_dict(orient="records"), sort_keys=True)
        group = groups.setdefault(
            signature,
            {
                "modules": [],
                "frame": frame,
                "samples": sum(s.get("samples", 0) for s in sections.values()),
            },
        )
        group["modules"].append(module)
    views, labels = {}, {}
    for group in groups.values():
        name = "preparation/" + "_".join(group["modules"])
        views[name] = group["frame"]
        labels[(name, "available")] = ", ".join(MODULE_NAMES.get(m, m) for m in group["modules"])
    return views, labels
