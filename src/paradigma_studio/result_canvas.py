"""Results-only canvas rendering; raw data keeps its existing canvas."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from weakref import WeakSet

from matplotlib.backend_bases import DrawEvent
from matplotlib.ticker import NullFormatter, NullLocator
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPen

from .plotting import ScrollableFigureCanvas

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.figure import Figure

    from .plotting import SelectionOverlay


class ResultFigureCanvas(ScrollableFigureCanvas):
    """Direct interval painting and viewport-bounded Results rendering."""

    zoom_rectangle = None
    time_scrolling = False

    def __init__(self, figure: Figure) -> None:
        super().__init__(figure)
        self._painted_axes: WeakSet[Axes] = WeakSet()
        self._viewport_renderer: RendererAgg | None = None
        self._viewport_pending = False
        self._viewport_overlay: SelectionOverlay | None = None

    def bind_viewport_overlay(self, overlay: SelectionOverlay) -> None:
        """Share the existing bounded static image, without another pixel cache."""
        self._viewport_overlay = overlay

    def redraw_viewport(self, *_: object) -> None:
        self._viewport_pending = True
        self.draw_idle()

    def draw(self):
        viewport_only = self._viewport_pending
        self._viewport_pending = False
        if viewport_only and self._extend_viewport():
            return
        self._painted_axes.clear()
        self._viewport_renderer = None
        if self.is_saving() or not self.isVisible():
            return super().draw()
        if not self.time_scrolling or not self.panning:
            with self._viewport_axes():
                return super().draw()
        # Heading geometry is settled before a scroll. Avoid recalculating the
        # unused native title positions and all their axis-label bounds per frame.
        titles = [(ax, ax._autotitlepos) for ax in self.figure.axes]
        for ax, _ in titles:
            ax._autotitlepos = False
        try:
            with self._viewport_axes(), self._fixed_y_axes(), self._hidden_x_labels():
                result = super().draw()
            self.prepare_time_scroll()
            return result
        finally:
            for ax, automatic in titles:
                ax._autotitlepos = automatic

    def _viewport_bounds(self):
        region = self.visibleRegion().boundingRect()
        ratio = self.device_pixel_ratio
        return (
            (self.height() - region.y() - region.height()) * ratio,
            (self.height() - region.y()) * ratio,
        )

    def _intersects_viewport(self, ax, bottom, top):
        padding = self.figure.dpi * 0.35
        return ax.bbox.y1 + padding >= bottom and ax.bbox.y0 - padding <= top

    def _extend_viewport(self):
        overlay = self._viewport_overlay
        if (
            self.panning
            or self.is_saving()
            or not self.isVisible()
            or self.figure.stale
            or overlay is None
            or overlay.background is None
            or self.get_renderer() is not self._viewport_renderer
        ):
            return False
        bottom, top = self._viewport_bounds()
        missing = [
            ax
            for ax in self.figure.axes
            if ax not in self._painted_axes and self._intersects_viewport(ax, bottom, top)
        ]
        if missing:
            # The overlay image excludes animated row markers. Restore it before
            # extending, so the next snapshot cannot bake in obsolete markers.
            self.restore_region(overlay.background)
            try:
                for ax in missing:
                    ax.draw(self._viewport_renderer)
                self._painted_axes.update(missing)
                self.figure.stale = False
                DrawEvent("draw_event", self, self._viewport_renderer)._process()
            except Exception:
                # Drawing/observer code is third party. Restore cache validity
                # for a fresh draw and propagate its complete original traceback.
                self._viewport_renderer = None
                overlay.invalidate()
                raise
        self.update()
        return True

    @contextmanager
    def _viewport_axes(self):
        bottom, top = self._viewport_bounds()
        original = {ax: ax.draw for ax in self.figure.axes}

        def draw_visible(ax, draw, renderer):
            # Figure.draw runs the complete layout first. Check the resulting
            # positions here, keeping offscreen axes visible to layout, shared
            # navigation, settings, selection and all full-precision exports.
            if self._intersects_viewport(ax, bottom, top):
                draw(renderer)
                self._painted_axes.add(ax)

        for ax, draw in original.items():
            ax.draw = lambda renderer, ax=ax, draw=draw: draw_visible(ax, draw, renderer)
        try:
            yield
            self._viewport_renderer = self.get_renderer()
        finally:
            for ax, draw in original.items():
                ax.draw = draw

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
