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
    """One centered date per day when measured label widths permit it."""

    def __init__(self, timezone=None, *, calendar=True):
        self.timezone, self.calendar = timezone, calendar
        self._layout_key = None

    def __call__(self):
        low, high = sorted(self.axis.get_view_interval())
        axes = self.axis.axes
        font = self.axis.get_major_ticks(1)[0].label1.get_fontproperties()
        key = low, high, axes.bbox.width, axes.figure.dpi, str(font)
        if key != self._layout_key:
            self._layout_key = key
            self._locations = self._day_locations(low, high, font)
        return self._locations

    def _day_locations(self, low, high, font):
        if not np.isfinite([low, high]).all() or high <= low:
            return np.array([])
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

    def _label_width(self, font, centers):
        formatter = RecordingDayFormatter(self.timezone, calendar=self.calendar)
        labels = [
            line
            for value in centers[:1].tolist() + centers[-1:].tolist()
            for line in formatter(value).splitlines()
        ]
        if self.calendar:
            # Bound measurement work even when thousands of days are visible;
            # the widest month and year determine the date-label footprint.
            labels.extend(datetime(2026, month, 28).strftime("%d %b") for month in range(1, 13))
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
    def __init__(self, timezone=None, *, calendar=True):
        self.timezone, self.calendar = timezone, calendar

    def __call__(self, value, pos=None):
        if self.calendar:
            return dates.num2date(value, tz=self.timezone).strftime("%d %b\n%Y")
        return f"Day {int(np.floor(value / DAY_SECONDS)) + 1}"
