"""Indexed navigation through original sensor samples without rebuilding axes."""

import numpy as np

from .plotting import time_coordinates
from .results_view import clock_times


class SensorNavigator:
    def __init__(self, context, clock):
        self.context = context
        self.clock = dict(clock) if clock is not None else None
        self.coordinates = time_coordinates(clock_times(context.display_times, clock))
        finite = np.flatnonzero(np.isfinite(self.coordinates))
        self.order = finite[np.argsort(self.coordinates[finite], kind="stable")]
        self.sorted_times = self.coordinates[self.order]
        self.anchor = time_coordinates(clock_times([context.selected_time], clock))[0]
        paired = np.flatnonzero(
            np.isfinite(context.analysis_times) & np.isfinite(context.display_times)
        )
        offset = (
            (context.display_times[paired[0]] - context.analysis_times[paired[0]])
            if len(paired)
            else 0.0
        )
        self.initial_limits = tuple(
            time_coordinates(clock_times(np.array([context.start, context.end]) + offset, clock))
        )
        self.limits = None

    def bounded_limits(self, limits):
        low, high = sorted(limits)
        if not len(self.sorted_times):
            return low, high
        start, end = self.sorted_times[[0, -1]]
        span = high - low
        if span >= end - start:
            return start, end if end > start else start + 1
        low = min(max(low, start), end - span)
        return low, low + span

    def positions(self, limits):
        low, high = limits
        begin = np.searchsorted(self.sorted_times, low, side="left")
        end = np.searchsorted(self.sorted_times, high, side="right")
        # Preserve the source file's row order, including duplicate timestamps.
        return np.sort(self.order[begin:end])
