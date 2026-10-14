"""Results-only canvas rendering; raw data keeps its existing canvas."""

from contextlib import contextmanager

from matplotlib.ticker import NullFormatter, NullLocator
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPen

from .plotting import ScrollableFigureCanvas


class ResultFigureCanvas(ScrollableFigureCanvas):
    """Direct interval painting and bounded rendering during Results scrolling."""

    zoom_rectangle = None
    time_scrolling = False

    def draw(self):
        if not self.time_scrolling or not self.panning or self.is_saving():
            return super().draw()
        # Heading geometry is settled before a scroll. Avoid recalculating the
        # unused native title positions and all their axis-label bounds per frame.
        titles = [(ax, ax._autotitlepos) for ax in self.figure.axes]
        for ax, _ in titles:
            ax._autotitlepos = False
        try:
            with self._fixed_y_axes(), self._hidden_x_labels():
                result = super().draw()
            self.prepare_time_scroll()
            return result
        finally:
            for ax, automatic in titles:
                ax._autotitlepos = automatic

    def prepare_time_scroll(self):
        previous = getattr(self, "_scroll_y_ticks", {})
        self._scroll_y_ticks = {}
        for ax in self.figure.axes:
            if not ax.yaxis.stale:
                state = self._y_state(ax)
                cached = previous.get(ax)
                self._scroll_y_ticks[ax] = (
                    cached
                    if cached is not None and cached[0] == state
                    else (state, ax.yaxis._update_ticks())
                )

    def finish_time_scroll(self):
        self._scroll_y_ticks = {}

    @staticmethod
    def _y_state(ax):
        return (
            ax.get_ylim(),
            ax.bbox.bounds,
            id(ax.yaxis.get_major_locator()),
            id(ax.yaxis.get_minor_locator()),
            id(ax.yaxis.get_major_formatter()),
            id(ax.yaxis.get_minor_formatter()),
        )

    @staticmethod
    def _draw_fixed_y(axis, ticks, renderer):
        if not axis.get_visible():
            return
        for tick in ticks:
            tick.draw(renderer)
        axis.label.draw(renderer)
        axis.offsetText.draw(renderer)
        axis.stale = False

    @contextmanager
    def _fixed_y_axes(self):
        original = {}
        for ax, (state, ticks) in getattr(self, "_scroll_y_ticks", {}).items():
            if state == self._y_state(ax) and not ax.yaxis.stale:
                axis = ax.yaxis
                original[axis] = axis.draw
                axis.draw = lambda renderer, axis=axis, ticks=ticks: self._draw_fixed_y(
                    axis, ticks, renderer
                )
        try:
            yield
        finally:
            for axis, draw in original.items():
                axis.draw = draw

    @contextmanager
    def _hidden_x_labels(self):
        original = {}
        labels = [(ax.xaxis, ax.xaxis._autolabelpos) for ax in self.figure.axes]
        for axis, _ in labels:
            if not axis.label.get_visible():
                axis._autolabelpos = False
        for ax in self.figure.axes:
            for name in ("major", "minor"):
                group = getattr(ax.xaxis, name)
                ticks = getattr(ax.xaxis, f"{name}Ticks")
                hidden = all(
                    not tick.label1.get_visible() and not tick.label2.get_visible()
                    for tick in ticks
                )
                if group not in original and hidden:
                    original[group] = group.locator, group.formatter
                    group.formatter = NullFormatter()
                    if not any(self._tick_has_marks(tick) for tick in ticks):
                        group.locator = NullLocator()
        try:
            yield
        finally:
            for group, (locator, formatter) in original.items():
                group.locator, group.formatter = locator, formatter
            for axis, automatic in labels:
                axis._autolabelpos = automatic

    @staticmethod
    def _tick_has_marks(tick):
        return tick.gridline.get_visible() or any(
            line.get_visible() and line.get_markersize()
            for line in (tick.tick1line, tick.tick2line)
        )

    def drawRectangle(self, rect):
        previous = self.zoom_rectangle
        self.zoom_rectangle = (
            QRectF(*(value / self.device_pixel_ratio for value in rect)).normalized()
            if rect is not None
            else None
        )
        # This is the Qt backend's native rubberband painting hook. The band
        # never enters the Agg image, data limits, layout or exported figure.
        self._draw_rect_callback = self._paint_time_interval
        dirty = self.zoom_rectangle
        if previous is not None:
            dirty = previous.united(dirty) if dirty is not None else previous
        if dirty is not None:
            self.update(dirty.toAlignedRect().adjusted(-1, -1, 1, 1))

    def _paint_time_interval(self, painter):
        if self.zoom_rectangle is None:
            return
        color = QColor(71, 125, 163, 51)
        painter.save()
        painter.setPen(QPen(color, 1 / self.device_pixel_ratio))
        painter.setBrush(color)
        painter.drawRect(self.zoom_rectangle)
        painter.restore()
