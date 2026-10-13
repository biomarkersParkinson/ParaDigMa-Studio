"""Display-only calendar-day summaries gated by valid metric coverage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from .gait_presence import union
from .results_view import clock_origin

if TYPE_CHECKING:
    import pandas as pd
    from numpy.typing import ArrayLike

    from .contracts import FloatArray

DAY_SECONDS = 86400.0
MIN_DAY_DATA_SECONDS = DAY_SECONDS * 0.01


def day_edges(clock: dict[str, Any] | None, starts: ArrayLike, ends: ArrayLike) -> FloatArray:
    """Midnight boundaries in recording time; elapsed 24-hour bins without a clock."""
    import pandas as pd

    limits = np.concatenate((np.asarray(starts, dtype=float), np.asarray(ends, dtype=float)))
    limits = limits[np.isfinite(limits)]
    if not len(limits):
        return np.array([], dtype=float)
    low, high = float(limits.min()), float(limits.max())
    if clock is None:
        first = np.floor(low / DAY_SECONDS)
        last = max(first + 1, np.ceil(high / DAY_SECONDS))
        return np.arange(first, last + 1) * DAY_SECONDS
    origin = clock_origin(clock)
    first, last = (origin + pd.to_timedelta([low, high], unit="s")).normalize()
    last += pd.DateOffset(days=1)
    boundaries = pd.date_range(first, last, freq="D")
    edges = (boundaries - origin).total_seconds().to_numpy(dtype=float)
    stop = max(2, np.searchsorted(edges, high, side="left") + 1)
    return edges[:stop]


def day_coverage(edges: ArrayLike, starts: ArrayLike, ends: ArrayLike) -> FloatArray:
    """Union valid intervals, split at midnight, and never bridge recording gaps."""
    edges = np.asarray(edges, dtype=float)
    count = max(0, len(edges) - 1)
    covered = np.zeros(count)
    if not count:
        return covered
    starts, ends = np.asarray(starts, dtype=float), np.asarray(ends, dtype=float)
    valid = np.isfinite(starts) & np.isfinite(ends) & (ends > starts)
    pairs = union(
        np.column_stack((np.maximum(starts[valid], edges[0]), np.minimum(ends[valid], edges[-1])))
    )
    if not len(pairs):
        return covered
    starts, ends = pairs.T
    left = np.searchsorted(edges, starts, side="right") - 1
    right = np.searchsorted(edges, ends, side="left") - 1
    same = left == right
    np.add.at(covered, left[same], ends[same] - starts[same])
    cross = ~same
    np.add.at(covered, left[cross], edges[left[cross] + 1] - starts[cross])
    np.add.at(covered, right[cross], ends[cross] - edges[right[cross]])
    difference = np.zeros(count + 1)
    np.add.at(difference, left[cross] + 1, 1)
    np.add.at(difference, right[cross], -1)
    covered += np.cumsum(difference[:-1]) * np.diff(edges)
    return covered


def _daily_frame(edges, values, data_seconds, observations=None):
    import pandas as pd

    values = np.asarray(values, dtype=float).copy()
    values[np.asarray(data_seconds) < MIN_DAY_DATA_SECONDS - 1e-9] = np.nan
    result = pd.DataFrame(
        {"start_s": edges[:-1], "end_s": edges[1:], "value": values, "data_s": data_seconds}
    )
    if observations is not None:
        result["n_observations"] = observations
    return result


def daily_summary(
    times: ArrayLike,
    values: ArrayLike,
    starts: ArrayLike,
    ends: ArrayLike,
    clock: dict[str, Any] | None,
    *,
    binary: bool = False,
) -> pd.DataFrame:
    """Median or binary percentage, with at least 864 s of finite metric support."""
    import pandas as pd

    times, values = np.asarray(times, dtype=float), np.asarray(values, dtype=float)
    starts, ends = np.asarray(starts, dtype=float), np.asarray(ends, dtype=float)
    edges = day_edges(clock, starts, ends)
    count = max(0, len(edges) - 1)
    valid = np.isfinite(times) & np.isfinite(values)
    if binary:
        valid &= np.isin(values, [0.0, 1.0])
    bins = np.searchsorted(edges, times[valid], side="right") - 1
    frame = pd.DataFrame({"day": bins, "value": values[valid]})
    grouped = (
        frame.groupby("day", sort=True)
        .agg(value=("value", "mean" if binary else "median"), n_observations=("value", "count"))
        .reindex(range(count))
    )
    return _daily_frame(
        edges,
        grouped.value.to_numpy() * (100 if binary else 1),
        day_coverage(edges, starts[valid], ends[valid]),
        grouped.n_observations.fillna(0).to_numpy(dtype=int),
    )


def daily_availability_summary(
    starts: ArrayLike, ends: ArrayLike, clock: dict[str, Any] | None
) -> pd.DataFrame:
    """Prepared input time as a percentage of the full calendar day."""
    edges = day_edges(clock, starts, ends)
    covered = day_coverage(edges, starts, ends)
    return _daily_frame(edges, covered / np.diff(edges) * 100, covered)


def gait_daily_summaries(
    intervals: dict[str, FloatArray], clock: dict[str, Any] | None
) -> dict[str, pd.DataFrame]:
    """Gait percentages share observed time, preserving the filtered subset."""
    domain = intervals["domain"]
    edges = day_edges(clock, domain[:, 0], domain[:, 1])
    observed = intervals["observed"]
    data = day_coverage(edges, observed[:, 0], observed[:, 1])
    output = {}
    for kind in ("gait", "filtered"):
        pairs = intervals[kind]
        positive = day_coverage(edges, pairs[:, 0], pairs[:, 1])
        values = np.divide(positive * 100, data, out=np.full(len(data), np.nan), where=data > 0)
        output[kind] = _daily_frame(edges, values, data)
    return output
