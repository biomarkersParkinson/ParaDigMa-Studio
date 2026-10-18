"""Bounded reuse of original bar geometry, without retaining detached Axes."""

from __future__ import annotations

import sys
import weakref
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd
    from matplotlib.axes import Axes
    from matplotlib.path import Path

    from .plotting import ViewportPolyCollection


@dataclass(frozen=True)
class RectangleGeometry:
    paths: list[Path]
    render_paths: list[Path]
    starts: np.ndarray
    ends: np.ndarray
    bottoms: np.ndarray
    tops: np.ndarray
    ordered: bool

    @classmethod
    def capture(cls, collection: ViewportPolyCollection) -> RectangleGeometry:
        return cls(
            collection.get_paths(),
            collection._render_paths,
            collection._starts,
            collection._ends,
            collection._bottoms,
            collection._tops,
            collection._ordered_intervals,
        )

    def install(self, collection: ViewportPolyCollection) -> None:
        # PolyCollection has no setter accepting existing Path objects. Keep
        # this pinned-Matplotlib adapter beside the existing draw-time adapter.
        collection._paths, collection._render_paths = self.paths, self.render_paths
        collection._starts, collection._ends = self.starts, self.ends
        collection._bottoms, collection._tops = self.bottoms, self.tops
        collection._ordered_intervals = self.ordered


@dataclass(frozen=True)
class CachedBars:
    data: tuple[np.ndarray, np.ndarray, np.ndarray]
    geometry: RectangleGeometry
    color: tuple[float, ...]
    edges: np.ndarray
    linewidth: float
    summary: pd.DataFrame | None
    size: int


@dataclass(frozen=True)
class CachedCoordinates:
    sources: tuple[weakref.ReferenceType, ...]
    clock: str
    arrays: tuple[np.ndarray, ...]
    size: int


def _array_bytes(value: Any, seen: set[int]) -> int:
    if value is None or id(value) in seen:
        return 0
    seen.add(id(value))
    return sys.getsizeof(value) + _array_bytes(getattr(value, "base", None), seen)


def _geometry_bytes(geometry: RectangleGeometry, data: tuple) -> int:
    seen: set[int] = set()
    size = sum(
        _array_bytes(value, seen)
        for value in (
            *data,
            geometry.starts,
            geometry.ends,
            geometry.bottoms,
            geometry.tops,
        )
    )
    for paths in (geometry.paths, geometry.render_paths):
        if id(paths) in seen:
            continue
        seen.add(id(paths))
        size += sys.getsizeof(paths)
        if paths:
            # plot_bars builds uniform, closed rectangles sharing one vertex
            # buffer. Account for every Path/dict/view, and count shared codes
            # conservatively per rectangle. Never scan 150,000 Python objects
            # on the GUI thread just to remove a graph.
            path = paths[0]
            per_path = sum(
                sys.getsizeof(value)
                for value in (
                    path,
                    vars(path),
                    path.vertices,
                    path.codes,
                )
            )
            size += len(paths) * per_path
            size += _array_bytes(path.vertices.base, seen)
    return size


class ResultPlotCache:
    """Bounded original bar geometry and shared display coordinates."""

    MAX_BYTES = 128 * 1024**2
    MAX_ENTRIES = 4
    MAX_COORDINATE_ENTRIES = 4
    MAX_COORDINATE_BYTES = 32 * 1024**2  # Within the shared 128 MiB budget.

    def __init__(self) -> None:
        self._entries: OrderedDict[tuple, CachedBars] = OrderedDict()
        self._coordinates: OrderedDict[tuple, CachedCoordinates] = OrderedDict()
        self._sources: dict[str, weakref.ReferenceType] = {}
        self._context: tuple = ()
        self.memory_bytes = 0
        self.coordinate_bytes = 0

    def clear(self) -> None:
        self._entries.clear()
        self._coordinates.clear()
        self._sources.clear()
        self._context = ()
        self.memory_bytes = 0
        self.coordinate_bytes = 0

    def coordinates(
        self,
        key: tuple,
        sources: tuple,
        clock: Mapping | None,
        prepare: Callable[[], tuple[np.ndarray, ...]],
    ) -> tuple[np.ndarray, ...]:
        """Reuse conversion only while every source object and clock still match."""
        self._trim()
        cached = self._coordinates.get(key)
        if (
            cached is not None
            and cached.clock == repr(clock)
            and len(cached.sources) == len(sources)
            and all(ref() is source for ref, source in zip(cached.sources, sources, strict=True))
        ):
            self._coordinates.move_to_end(key)
            return cached.arrays
        if cached is not None:
            self._coordinates.pop(key)
            self.coordinate_bytes -= cached.size
        arrays = prepare()
        seen: set[int] = set()
        size = sum(_array_bytes(array, seen) for array in arrays)
        if size <= min(self.MAX_COORDINATE_BYTES, self.MAX_BYTES):
            self._coordinates[key] = CachedCoordinates(
                tuple(weakref.ref(source) for source in sources), repr(clock), arrays, size
            )
            self.coordinate_bytes += size
            self._trim()
        return arrays

    def _trim(self) -> None:
        while len(self._coordinates) > self.MAX_COORDINATE_ENTRIES or self.coordinate_bytes > min(
            self.MAX_COORDINATE_BYTES, self.MAX_BYTES
        ):
            _, previous = self._coordinates.popitem(last=False)
            self.coordinate_bytes -= previous.size
        while self._entries and (
            len(self._entries) > self.MAX_ENTRIES
            or self.memory_bytes + self.coordinate_bytes > self.MAX_BYTES
        ):
            _, bars = self._entries.popitem(last=False)
            self.memory_bytes -= bars.size

    def bind(self, tables: dict, mode: int, clock: Mapping | None, *, reset: bool) -> None:
        context = mode, repr(clock)
        same = len(tables) == len(self._sources) and all(
            reference() is tables.get(name) for name, reference in self._sources.items()
        )
        if reset or not same or context != self._context:
            self.clear()
            self._sources = {name: weakref.ref(frame) for name, frame in tables.items()}
            self._context = context

    def capture(self, key: tuple, axes: Axes) -> None:
        from .plotting import ViewportPolyCollection

        if not getattr(axes, "_paradigma_bars", False) or axes.texts:
            return
        collection = next(
            (c for c in axes.collections if isinstance(c, ViewportPolyCollection)), None
        )
        if collection is None:
            return
        geometry = RectangleGeometry.capture(collection)
        data = axes._paradigma_bar_data
        summary = getattr(axes, "_paradigma_epoch_data", None)
        size = _geometry_bytes(geometry, data)
        if summary is not None:
            size += int(summary.memory_usage(index=True, deep=True).sum())
        if size > self.MAX_BYTES:
            return
        previous = self._entries.pop(key, None)
        self.memory_bytes -= previous.size if previous is not None else 0
        self._entries[key] = CachedBars(
            data,
            geometry,
            tuple(collection.get_facecolor()[0][:3]),
            collection.get_edgecolor().copy(),
            float(collection.get_linewidth()[0]),
            summary,
            size,
        )
        self.memory_bytes += size
        self._trim()

    def restore(self, key: tuple, axes: Axes) -> bool:
        from .plotting import plot_bars

        cached = self._entries.pop(key, None)
        if cached is None:
            return False
        self.memory_bytes -= cached.size
        collection = plot_bars(axes, *cached.data, cached.color, geometry=cached.geometry)
        collection.set_edgecolor(cached.edges if len(cached.edges) else "none")
        collection.set_linewidth(cached.linewidth)
        if cached.summary is not None:
            axes._paradigma_epoch_data = cached.summary
        return True
