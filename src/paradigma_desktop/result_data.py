"""Qt-independent derived views of official results; original tables stay unchanged."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .availability import availability_views
from .recordings import timeline_offsets
from .results_view import (
    aggregation_tables,
    binary_interval_ends,
    clock_times,
    detail_tables,
    detail_timing,
    plot_tables,
)


@dataclass(frozen=True, slots=True)
class ResultData:
    tables: dict[str, pd.DataFrame]
    aggregates: dict[str, pd.DataFrame]
    plot_frames: dict[str, pd.DataFrame]
    plot_labels: dict[tuple[str, str], str]
    timings: dict[str, pd.DataFrame]
    interval_ends: dict[str, np.ndarray]
    bar_bounds: dict[str, tuple[np.ndarray, np.ndarray]]
    coverage: dict[str, pd.DataFrame]
    coverage_labels: dict[tuple[str, str], str]


def prepare_result_data(results: dict[str, Any], offsets: dict[str, Any]) -> ResultData:
    """Prepare presentation timing and coverage without changing scientific outputs."""
    tables = detail_tables(results)
    plot_frames, plot_labels = plot_tables(tables)
    aggregates = aggregation_tables(results)
    timings = {name: detail_timing(results, name, frame) for name, frame in tables.items()}
    for name, timing in timings.items():
        timing["Timeline time (s)"] = timing["Analysis time (s)"] + timeline_offsets(
            name, tables[name], offsets
        )
    interval_ends = {
        name: binary_interval_ends(name, tables[name], timing["Timeline time (s)"])
        for name, timing in timings.items()
    }
    bar_bounds = {}
    for name, timing in timings.items():
        starts = timing["Timeline time (s)"].to_numpy().copy()
        ends = interval_ends[name].copy()
        gaps = np.diff(np.unique(starts[np.isfinite(starts)]))
        if len(gaps):
            # Isolated participant/file groups can still use the observed
            # output cadence; values must not disappear from bar plots.
            ends = np.where(ends > starts, ends, starts + np.median(gaps))
        if name.startswith("quantifications/gait/") and "time" not in tables[name]:
            frame = tables[name]
            keys = [key for key in ("file_key", "gait_segment_nr") if key in frame]
            counts = (
                frame.groupby(keys, dropna=False)[keys[0]].transform("size").to_numpy()
                if keys
                else np.full(len(frame), len(frame))
            )
            width = (
                timing["Segment end (s)"].to_numpy() - timing["Segment start (s)"].to_numpy()
            ) / np.maximum(counts, 1)
            starts -= width / 2
            ends = starts + width
        bar_bounds[name] = starts, ends
    coverage, labels = availability_views(results, offsets)
    plot_frames.update(coverage)
    plot_labels.update(labels)
    for name, frame in coverage.items():
        timings[name] = pd.DataFrame({"Timeline time (s)": frame.time})
        interval_ends[name] = frame.end.to_numpy()

    return ResultData(
        tables,
        aggregates,
        plot_frames,
        plot_labels,
        timings,
        interval_ends,
        bar_bounds,
        coverage,
        labels,
    )


def detail_table_view(frame, name, timing, offsets, clock):
    """Optional presentation columns, preserving every original value and heading."""
    view = frame.copy(deep=False)
    if timing is None:
        return view
    fields = {
        "Analysis time (s)": timing["Analysis time (s)"].to_numpy(),
        "Time basis": timing["Time basis"].to_numpy(),
    }
    if any(offset != 0.0 for offset in offsets.values()):
        fields = {"Timeline time (s)": timing["Timeline time (s)"].to_numpy(), **fields}
    if clock is not None:
        fields = {
            "Recording date/time": clock_times(timing["Timeline time (s)"].to_numpy(), clock),
            **fields,
        }
    if name.startswith("quantifications/gait/"):
        fields.update(
            {
                "Segment start (s)": timing["Segment start (s)"].to_numpy(),
                "Segment end (s)": timing["Segment end (s)"].to_numpy(),
            }
        )
    for field, values in reversed(list(fields.items())):
        field_name = field if field not in view else f"Display · {field}"
        view.insert(0, field_name, values)
    return view
