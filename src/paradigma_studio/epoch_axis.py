"""Grouped day/time axes for epoch graphs, retaining the original bars."""

import numpy as np
from matplotlib import dates, ticker
from matplotlib.artist import Artist, allow_rasterization
from matplotlib.collections import LineCollection

from .daily import DAY_SECONDS
from .day_axis import RecordingDayFormatter, RecordingDayLocator, _visible_days


class EpochHourLocator(ticker.Locator):
    """Subday clock ticks only when there is space for meaningful hour labels."""

    def __init__(self, timezone=None, *, calendar=True):
        self.timezone, self.calendar = timezone, calendar
        self._layout_key = None

    def __call__(self):
        low, high = sorted(self.axis.get_view_interval())
        width = self.axis.axes.bbox.width / (self.axis.axes.figure.dpi / 100)
        key = low, high, width
        if key != self._layout_key:
            self._layout_key = key
            self._locations = self._hour_locations(low, high, width)
        return self._locations

    def _hour_locations(self, low, high, width):
        if not np.isfinite([low, high]).all() or high <= low:
            return np.array([])
        capacity = max(2, min(30, int(width // 65)))
        if self.calendar:
            locator = dates.AutoDateLocator(
                tz=self.timezone, minticks=max(3, capacity // 2), maxticks=capacity
            )
            locator.set_axis(self.axis)
            locations = locator()
            if locator._freq <= dates.DAILY:
                return np.array([])
        else:
            steps = np.array(
                [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200]
            )
            target = (high - low) / capacity
            if target > steps[-1]:
                return np.array([])
            step = steps[np.searchsorted(steps, target)]
            locations = np.arange(np.ceil(low / step), np.floor(high / step) + 1) * step
        return locations[(locations >= low) & (locations <= high)]


class ElapsedHourFormatter(ticker.Formatter):
    def __call__(self, value, pos=None):
        seconds = round(value) % int(DAY_SECONDS)
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def _midnight_positions(low, high, width, timezone, calendar):
    starts, ends, numbers = _visible_days(low, high, timezone, calendar)
    stride = max(1, int(np.ceil(len(starts) * 4 / max(1, width))))
    positions = np.r_[starts[numbers % stride == 0], ends[-1:]]
    return positions[(positions >= low) & (positions <= high)]


class MidnightSeparators(Artist):
    """Lightweight midnight lines that never change data limits or bar geometry."""

    def __init__(self, axes, timezone=None, *, calendar=True):
        super().__init__()
        self.timezone, self.calendar = timezone, calendar
        self._geometry_key = None
        self.lines = LineCollection([], colors="#B9CADA", linewidths=0.9)
        self.lines.set_figure(axes.figure)
        self.lines.axes = axes
        self.lines.set_transform(axes.get_xaxis_transform())
        self.lines.set_clip_path(axes.patch)
        self.set_zorder(1.7)
        self.set_in_layout(False)
        self.set_gid("midnight-separators")
        axes.add_artist(self)

    @allow_rasterization
    def draw(self, renderer):
        if not self.get_visible():
            return
        low, high = sorted(self.axes.get_xlim())
        if not np.isfinite([low, high]).all() or high <= low:
            return
        key = low, high, self.axes.bbox.width
        if key != self._geometry_key:
            self._geometry_key = key
            positions = _midnight_positions(
                low, high, self.axes.bbox.width, self.timezone, self.calendar
            )
            segments = np.zeros((len(positions), 2, 2))
            segments[:, :, 0] = positions[:, None]
            segments[:, 1, 1] = 1
            self.lines.set_segments(segments)
        self.lines.draw(renderer)
        self.stale = False


class MidnightBridges(Artist):
    """Connect the plot separators through their gutters, behind the headings.

    Plot-local lines stay behind the bars. These figure-local segments fill
    only the gaps, so the combined line is continuous without covering data.
    Read settled geometry at draw time to follow resizing, panning and exports.
    """

    def __init__(self, figure, timezone=None, *, calendar=True):
        super().__init__()
        self.timezone, self.calendar = timezone, calendar
        self._geometry_key = None
        self.lines = LineCollection([], colors="#B9CADA", linewidths=0.9)
        self.lines.set_figure(figure)
        self.lines.set_transform(figure.transFigure)
        self.set_zorder(-1)
        self.set_in_layout(False)
        self.set_gid("midnight-bridges")
        figure.add_artist(self)

    @allow_rasterization
    def draw(self, renderer):
        axes = [ax for ax in self.figure.axes if getattr(ax, "_paradigma_day_groups", False)]
        if not self.get_visible() or not axes:
            return
        low, high = sorted(axes[0].get_xlim())
        if not np.isfinite([low, high]).all() or high <= low:
            return
        key = low, high, tuple(ax.bbox.bounds for ax in axes), self.figure.bbox.bounds
        if key != self._geometry_key:
            self._geometry_key = key
            self.lines.set_segments(self._gap_segments(axes, low, high))
        self.lines.draw(renderer)
        self.stale = False

    def _gap_segments(self, axes, low, high):
        positions = _midnight_positions(low, high, axes[0].bbox.width, self.timezone, self.calendar)
        points = (
            axes[0].get_xaxis_transform().transform(np.column_stack((positions, positions * 0)))
        )
        x = self.figure.transFigure.inverted().transform(points)[:, 0]
        bounds = sorted(
            (ax.bbox.transformed(self.figure.transFigure.inverted()) for ax in axes),
            key=lambda box: box.y0,
        )
        gaps = [(lower.y1, upper.y0) for lower, upper in zip(bounds, bounds[1:], strict=False)]
        return [((value, bottom), (value, top)) for bottom, top in gaps for value in x]


def style_epoch_axis(axis, timezone, *, calendar, clock_formatter, labels=False):
    """Dates and hours occupy separate rows; do not add a shaded background."""
    axis.xaxis.set_major_locator(
        RecordingDayLocator(timezone, calendar=calendar, split_year=False, first_at_start=True)
    )
    axis.xaxis.set_major_formatter(
        RecordingDayFormatter(timezone, calendar=calendar, split_year=False, first_at_start=True)
    )
    axis.xaxis.set_minor_locator(EpochHourLocator(timezone, calendar=calendar))
    axis.xaxis.set_minor_formatter(clock_formatter if calendar else ElapsedHourFormatter())
    axis.xaxis.remove_overlapping_locs = False
    axis.tick_params(
        axis="x", which="major", labelbottom=labels, labelsize=9, colors="#465B73", pad=20, length=0
    )
    axis.tick_params(
        axis="x", which="minor", labelbottom=labels, labelsize=8, colors="#7C8EA3", pad=6, length=3
    )
    axis.grid(False, axis="x", which="both")
