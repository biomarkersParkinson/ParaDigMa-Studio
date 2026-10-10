"""Indexed navigation through original sensor samples without rebuilding axes."""

import numpy as np

from .plotting import time_coordinates
from .results_view import clock_times


class SensorTimeIndex:
    """Index elapsed timestamps once; defer calendar conversion to visible samples."""

    def __init__(self, times):
        self.times = np.asarray(times, dtype=float)
        finite = np.flatnonzero(np.isfinite(self.times))
        observed = self.times[finite]
        ordered = np.all(observed[1:] >= observed[:-1])
        if ordered and len(finite) == len(self.times):
            self.order = None
            self.sorted_times = self.times
        else:
            self.order = finite if ordered else finite[np.argsort(observed, kind="stable")]
            self.sorted_times = self.times[self.order]

    def positions(self, low, high):
        begin = np.searchsorted(self.sorted_times, low, side="left")
        end = np.searchsorted(self.sorted_times, high, side="right")
        return np.arange(begin, end) if self.order is None else np.sort(self.order[begin:end])


class SensorNavigator:
    def __init__(self, context, clock, *, index=None):
        self.context = context
        self.clock = dict(clock) if clock is not None else None
        self.index = index if index is not None else SensorTimeIndex(context.display_times)
        self.anchor = self.coordinates_at([context.selected_time])[0]
        paired = np.flatnonzero(
            np.isfinite(context.analysis_times) & np.isfinite(context.display_times)
        )
        offset = (
            (context.display_times[paired[0]] - context.analysis_times[paired[0]])
            if len(paired)
            else 0.0
        )
        self.initial_limits = tuple(
            self.coordinates_at(np.array([context.start, context.end]) + offset)
        )
        times = self.index.sorted_times
        self.source_limits = tuple(self.coordinates_at(times[[0, -1]])) if len(times) else None
        self.origin = self.coordinates_at([0.0])[0] if clock is not None else 0.0
        self.limits = None
        self.home_limits = None

    def coordinates_at(self, times):
        return time_coordinates(clock_times(times, self.clock))

    def bounded_limits(self, limits):
        low, high = sorted(limits)
        if self.source_limits is None:
            return low, high
        start, end = self.source_limits
        span = high - low
        if span >= end - start:
            return start, end if end > start else start + 1
        low = min(max(low, start), end - span)
        return low, low + span

    def positions(self, limits):
        low, high = limits
        if self.clock is None:
            return self.index.positions(low, high)
        # Float date coordinates lose sub-microsecond precision. Use a generous
        # search margin, then compare the candidates with the original calendar
        # conversion, preserving exact endpoint inclusion and duplicate rows.
        seconds = (np.asarray(limits) - self.origin) * 86400
        margin = max(1e-6, np.spacing(max(abs(low), abs(high), abs(self.origin))) * 86400 * 8)
        positions = self.index.positions(seconds[0] - margin, seconds[1] + margin)
        coordinates = self.coordinates_at(self.context.display_times[positions])
        return positions[(coordinates >= low) & (coordinates <= high)]
