"""Original raw samples with bounded, peak-preserving paths for the visible range."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import nullcontext
from typing import Any

import numpy as np
from matplotlib import rc_context
from matplotlib.artist import allow_rasterization
from matplotlib.lines import Line2D

from .plotting import time_coordinates

DISPLAY_POINTS = 20_000
SUMMARY_BYTES = 4 * 1024**2


def _take(values: Any, positions: slice | np.ndarray) -> Any:
    if hasattr(values, "iloc"):
        return values.iloc[positions]
    if isinstance(positions, slice) or hasattr(values, "dtype"):
        return values[positions]
    return np.asarray(values)[positions]


def _gap_edges(finite: np.ndarray) -> np.ndarray:
    changes = np.flatnonzero(finite[1:] != finite[:-1])
    return np.unique(np.r_[changes, changes + 1])


def _numeric_values(values: Any) -> np.ndarray:
    dtype = getattr(values, "dtype", None)
    if isinstance(dtype, np.dtype) and dtype.kind in "biuf":
        return np.asarray(values)
    if hasattr(values, "to_numpy"):
        return values.to_numpy(dtype=float, na_value=np.nan)
    return np.asarray(values, dtype=float)


class RawSignalTime:
    """Share coordinate conversion and range lookup between selected channels."""

    def __init__(self, values: Any) -> None:
        self.original = values
        self.coordinates = time_coordinates(values)
        finite = np.isfinite(self.coordinates)
        self.finite = None if finite.all() else finite
        self.ordered = bool(finite.all() and np.all(self.coordinates[1:] >= self.coordinates[:-1]))
        self.gaps = _gap_edges(finite)
        if self.ordered:
            self.extents = (
                np.array([0, len(values) - 1], dtype=np.intp)
                if len(values)
                else np.array([], dtype=np.intp)
            )
        else:
            positions = np.flatnonzero(finite)
            observed = self.coordinates[positions]
            self.extents = (
                positions[[observed.argmin(), observed.argmax()]] if len(positions) else positions
            )

    def positions(self, limits: tuple[float, float] | None) -> slice | np.ndarray:
        if limits is None:
            return slice(0, len(self.coordinates))
        low, high = sorted(limits)
        if self.ordered:
            # Retain neighbours so clipped line segments reach the viewport edge.
            begin = max(0, int(np.searchsorted(self.coordinates, low, side="left")) - 1)
            end = min(
                len(self.coordinates),
                int(np.searchsorted(self.coordinates, high, side="right")) + 1,
            )
            return slice(begin, end)
        xs = self.coordinates
        visible = (xs >= low) & (xs <= high)
        crossing = (np.minimum(xs[:-1], xs[1:]) <= high) & (np.maximum(xs[:-1], xs[1:]) >= low)
        visible[:-1] |= crossing
        visible[1:] |= crossing
        # Invalid time runs must still break paths between selected fragments.
        visible[self.gaps] = True
        return np.flatnonzero(visible)


def _block_extrema(
    values: np.ndarray, begin: int, end: int, step: int, all_finite: bool
) -> np.ndarray:
    blocks = values[begin:end].reshape(-1, step)
    if not len(blocks):
        return np.empty((0, 4), dtype=np.intp)
    if all_finite:
        lower, upper = blocks.argmin(axis=1), blocks.argmax(axis=1)
    else:
        finite = np.isfinite(blocks)
        lower = np.where(finite, blocks, np.inf).argmin(axis=1)
        upper = np.where(finite, blocks, -np.inf).argmax(axis=1)
    starts = np.arange(begin, end, step)
    return np.column_stack((starts, starts + lower, starts + upper, starts + step - 1))


class RawSignalLine(Line2D):
    """Retain source samples; replace only the temporary renderer path on draw."""

    def __init__(
        self, xs: Any, ys: Any, *, time_index: RawSignalTime | None = None, **kwargs: Any
    ) -> None:
        self._source_x: Any = []
        self._source_y: Any = []
        super().__init__([], [], **kwargs)
        self.set_source(time_index if time_index is not None else RawSignalTime(xs), ys)

    def set_source(self, time_index: RawSignalTime, values: Any) -> None:
        if len(time_index.original) != len(values):
            raise ValueError("Raw time coordinates and sensor samples must have the same length.")
        self.time_index = time_index
        self._source_x, self._source_y = time_index.original, values
        self._values = _numeric_values(values)
        self._summary_values = (
            self._values
            if time_index.finite is None
            else np.where(time_index.finite, self._values, np.nan)
        )
        finite = np.isfinite(self._values)
        self._all_finite = bool(finite.all() and time_index.finite is None)
        self._gaps = np.union1d(_gap_edges(finite), time_index.gaps)
        self._summaries: OrderedDict[int, np.ndarray] = OrderedDict()
        positions = self.sample_positions(None)
        positions = (
            np.union1d(positions, time_index.extents)
            if not isinstance(positions, slice)
            else positions
        )
        self._overview = _take(time_index.coordinates, positions), _take(self._values, positions)
        Line2D.set_data(self, *self._overview)

    def set_data(self, *args: Any) -> None:
        xs, ys = args[0] if len(args) == 1 else args
        self.set_source(RawSignalTime(xs), ys)

    def get_xdata(self, orig: bool = True) -> Any:
        return self._source_x if orig else super().get_xdata(orig=False)

    def get_ydata(self, orig: bool = True) -> Any:
        return self._source_y if orig else super().get_ydata(orig=False)

    @property
    def summary_bytes(self) -> int:
        return sum(summary.nbytes for summary in self._summaries.values())

    def _summary(self, begin: int, end: int, step: int) -> np.ndarray:
        groups = len(self._values) // step
        if step < 128 or groups * 4 * np.dtype(np.intp).itemsize > SUMMARY_BYTES:
            return _block_extrema(self._summary_values, begin, end, step, self._all_finite).ravel()
        if step not in self._summaries:
            self._summaries[step] = _block_extrema(
                self._summary_values, 0, groups * step, step, self._all_finite
            )
        self._summaries.move_to_end(step)
        selected = self._summaries[step][begin // step : end // step].ravel()
        while len(self._summaries) > 3 or self.summary_bytes > SUMMARY_BYTES:
            self._summaries.popitem(last=False)
        return selected

    def _fragment(self, begin: int, end: int) -> np.ndarray:
        if begin >= end:
            return np.array([], dtype=np.intp)
        return _block_extrema(
            self._summary_values, begin, end, end - begin, self._all_finite
        ).ravel()

    def sample_positions(
        self, limits: tuple[float, float] | None, *, full: bool = False, limit: int | None = None
    ) -> slice | np.ndarray:
        visible = self.time_index.positions(limits)
        count = visible.stop - visible.start if isinstance(visible, slice) else len(visible)
        if full or count <= DISPLAY_POINTS:
            return visible
        # Four original observations per block: first, minimum, maximum, last.
        # Sorting the positions preserves chronology without averaging values.
        step = 1 << int(np.ceil(np.log2(4 * count / (limit or DISPLAY_POINTS))))
        if not isinstance(visible, slice):
            end = count // step * step
            sampled = _block_extrema(
                self._summary_values[visible], 0, end, step, self._all_finite
            ).ravel()
            selected = np.r_[visible[sampled], visible[end:]]
            begin, end = int(visible[0]), int(visible[-1]) + 1
        else:
            begin, end = visible.start, visible.stop
            left = min(end, (begin + step - 1) // step * step)
            right = max(left, end // step * step)
            selected = np.r_[
                self._fragment(begin, left),
                self._summary(left, right, step),
                self._fragment(right, end),
            ]
        gaps = self._gaps[np.searchsorted(self._gaps, begin) : np.searchsorted(self._gaps, end)]
        return np.unique(np.r_[selected, gaps])

    @allow_rasterization
    def draw(self, renderer: Any) -> None:
        if not self.get_visible():
            return
        limits = self.axes.get_xlim() if self.axes is not None else None
        figure = self.get_figure(root=True)
        if figure is None:
            return
        canvas = figure.canvas
        width = self.axes.bbox.width if self.axes is not None else DISPLAY_POINTS / 4
        limit = min(DISPLAY_POINTS, max(512, int(np.ceil(width)) * 4))
        positions = self.sample_positions(limits, full=canvas.is_saving(), limit=limit)
        Line2D.set_data(
            self, _take(self.time_index.coordinates, positions), _take(self._values, positions)
        )
        try:
            context = (
                rc_context({"agg.path.chunksize": 20_000}) if canvas.is_saving() else nullcontext()
            )
            with context:
                super().draw(renderer)
        finally:
            # Keep a small full-extent path for relim/Home. Source getters retain
            # every original sample; exports render every visible observation.
            stale = self.stale
            Line2D.set_data(self, *self._overview)
            Line2D.recache(self)
            self.stale = stale


def update_raw_signal(line: Line2D, time_index: RawSignalTime, values: Any) -> None:
    """Replace navigation samples while retaining ordinary Line2D service support."""
    if isinstance(line, RawSignalLine):
        line.set_source(time_index, values)
    else:
        line.set_data(time_index.original, values)
