"""Responsive day/date labels shared by live and exported graphs."""

from datetime import datetime
from functools import lru_cache

import numpy as np
from matplotlib import dates, ticker

from .daily import DAY_SECONDS


@lru_cache(maxsize=16)
def _visible_days(low, high, timezone, calendar):
    """Reuse midnight geometry across graphs; never involve metric values."""
    if calendar:
        import pandas as pd

        first = pd.Timestamp(dates.num2date(low, tz=timezone)).normalize()
        last = pd.Timestamp(dates.num2date(high, tz=timezone)).normalize()
        boundaries = pd.date_range(first, last + pd.DateOffset(days=1), freq="D")
        edges = dates.date2num(boundaries.to_numpy(dtype="datetime64[ns]"))
        numbers = first.date().toordinal() + np.arange(len(edges) - 1)
    else:
        first, last = np.floor(low / DAY_SECONDS), np.floor(high / DAY_SECONDS) + 1
        edges = np.arange(first, last + 1) * DAY_SECONDS
        numbers = np.arange(first, last, dtype=int)
    visible = (edges[:-1] < high) & (edges[1:] > low)
    starts, ends, numbers = edges[:-1][visible], edges[1:][visible], numbers[visible]
    for values in (starts, ends, numbers):
        values.flags.writeable = False
    return starts, ends, numbers


class RecordingDayLocator(ticker.Locator):
    """Spaced dates with an optional centered/left/hidden first-day label."""

    def __init__(self, timezone=None, *, calendar=True, split_year=True, adaptive_first=False):
        self.timezone, self.calendar = timezone, calendar
        self.split_year = split_year
        self.adaptive_first = adaptive_first
        self._layout_key = None
        self._left_label = None

    def __call__(self):
        low, high = sorted(self.axis.get_view_interval())
        axes = self.axis.axes
        font = self.axis.get_major_ticks(1)[0].label1.get_fontproperties()
        key = low, high, axes.bbox.width, axes.figure.dpi, str(font)
        if key != self._layout_key:
            self._layout_key = key
            self._left_label = None
            self._locations = self._day_locations(low, high, font)
        return self._locations

    def _day_locations(self, low, high, font):
        if not np.isfinite([low, high]).all() or high <= low:
            return np.array([])
        if self.adaptive_first:
            return self._grouped_locations(low, high, font)
        starts, ends, numbers = _visible_days(low, high, self.timezone, self.calendar)
        centers = (np.maximum(starts, low) + np.minimum(ends, high)) / 2
        width = max(1, self.axis.axes.bbox.width)
        pixels = (centers - low) / (high - low) * width
        label_width = self._label_width(font, centers) + 12
        fitting = (pixels >= label_width / 2) & (pixels <= width - label_width / 2)
        centers, numbers, pixels = centers[fitting], numbers[fitting], pixels[fitting]
        if not len(centers):
            return np.array([(low + high) / 2])
        spacing = np.min(np.diff(pixels)) if len(pixels) > 1 else width
        stride = max(1, int(np.ceil(label_width / max(1, spacing))))
        selected = numbers % stride == 0
        return centers[selected] if selected.any() else centers[:1]

    def _grouped_locations(self, low, high, font):
        starts, ends, numbers = _visible_days(low, high, self.timezone, self.calendar)
        centers = (np.maximum(starts, low) + np.minimum(ends, high)) / 2
        centers[0] = (starts[0] + ends[0]) / 2
        width = max(1, self.axis.axes.bbox.width)
        scale = width / (high - low)
        pixels = (centers - low) * scale
        label_width = self._label_width(font, centers) + 12
        half = label_width / 2
        fitting = (pixels >= half) & (pixels <= width - half)
        first_end = (min(ends[0], high) - low) * scale
        fitting[0] &= pixels[0] + half <= first_end
        if not fitting[0] and first_end >= label_width:
            centers[0], pixels[0], fitting[0] = low, 0, True
            self._left_label = low
        # Use full day widths, so hiding the first date cannot change which
        # subsequent dates are selected or move them from their normal centers.
        spacing = max(1, np.min(ends - starts) * scale)
        stride = max(1, int(np.ceil(label_width / spacing)))
        indices = np.flatnonzero(fitting & (numbers % stride == 0))
        if len(indices) > 1:
            first, second = indices[:2]
            first_right = (
                label_width if centers[first] == self._left_label else pixels[first] + half
            )
            if first == 0 and first_right > pixels[second] - half:
                indices = indices[1:]
        if len(indices) > 1 and pixels[indices[-1]] - pixels[indices[-2]] < label_width:
            indices = indices[:-1]
        return centers[indices]

    def _label_width(self, font, centers):
        formatter = RecordingDayFormatter(
            self.timezone, calendar=self.calendar, split_year=self.split_year
        )
        labels = [
            line
            for value in centers[:1].tolist() + centers[-1:].tolist()
            for line in formatter(value).splitlines()
        ]
        if self.calendar:
            # Bound measurement work even when thousands of days are visible;
            # the widest month and year determine the date-label footprint.
            pattern = "%d %b" if self.split_year else "%d %b %Y"
            labels.extend(datetime(2026, month, 28).strftime(pattern) for month in range(1, 13))
        renderer = getattr(self.axis.axes.figure.canvas, "get_renderer", None)
        if renderer is None:
            dpi = self.axis.axes.figure.dpi
            return max(map(len, labels), default=6) * font.get_size() * dpi / 72 * 0.65
        renderer = renderer()
        return max(
            (renderer.get_text_width_height_descent(label, font, False)[0] for label in labels),
            default=0,
        )


class RecordingDayFormatter(ticker.Formatter):
    def __init__(self, timezone=None, *, calendar=True, split_year=True):
        self.timezone, self.calendar = timezone, calendar
        self.split_year = split_year

    def set_locs(self, locs):
        super().set_locs(locs)
        locator = self.axis.get_major_locator()
        left_label = getattr(locator, "_left_label", None)
        for value, tick in zip(locs, self.axis.get_major_ticks(len(locs)), strict=True):
            tick.label1.set_horizontalalignment("left" if value == left_label else "center")

    def __call__(self, value, pos=None):
        if self.calendar:
            pattern = "%d %b\n%Y" if self.split_year else "%d %b %Y"
            return dates.num2date(value, tz=self.timezone).strftime(pattern)
        return f"Day {int(np.floor(value / DAY_SECONDS)) + 1}"
