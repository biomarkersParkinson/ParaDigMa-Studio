"""Time-only navigation for Results, independent of raw sensor controls."""

import math
from copy import copy

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QScrollBar

from .assets import DATA_DIRECTORY
from .plot_controls import GraphToolbar
from .theme import tooltip_text


class ResultsToolbar(GraphToolbar):
    toolitems = tuple(item for item in GraphToolbar.toolitems if item[0] != "Pan")

    def __init__(self, canvas, parent):
        super().__init__(canvas, parent)
        self.scrolling_time = False
        self.time_scroll = None
        self._actions["zoom"].setText("Select time interval")
        self._actions["zoom"].setIcon(QIcon(str(DATA_DIRECTORY / "select-interval.svg")))
        self._actions["zoom"].setToolTip("Select a time interval to zoom into all linked graphs")
        self.add_time_zoom_actions(lambda factor: self.time_scroll.zoom(factor))

    def pan(self, *args):
        """Results use the time scrollbar; raw graph toolbars retain panning."""

    def home(self, *args):
        self.stop_navigation()
        super().home(*args)

    def back(self, *args):
        self.stop_navigation()
        super().back(*args)

    def forward(self, *args):
        self.stop_navigation()
        super().forward(*args)

    def press_zoom(self, event):
        self.stop_navigation()
        event = self._interval_event(event)
        if event.inaxes is not None and self._nav_stack() is None:
            # Save Home before GraphToolbar captures automatic Y axes. A
            # time-only selection needs no Y refit or graph redraw on press.
            self.push_current()
        super().press_zoom(event)

    def _interval_event(self, event):
        if event.inaxes is not None or event.x is None or event.y is None:
            return event
        axes = [ax for ax in self.canvas.figure.axes if ax.get_navigate() and ax.can_zoom()]
        if not axes:
            return event
        source = axes[0]
        bottom, top = min(ax.bbox.y0 for ax in axes), max(ax.bbox.y1 for ax in axes)
        if not (source.bbox.x0 <= event.x <= source.bbox.x1 and bottom <= event.y <= top):
            return event
        # Project a gutter press onto the shared time axis without changing the
        # event received by row selection and other canvas callbacks.
        projected = copy(event)
        projected.inaxes = source
        projected.y = (source.bbox.y0 + source.bbox.y1) / 2
        projected.xdata, projected.ydata = source.transData.inverted().transform(
            (projected.x, projected.y)
        )
        return projected

    def _update_cursor(self, event):
        if self.mode.name == "ZOOM":
            event = self._interval_event(event)
        super()._update_cursor(event)

    def drag_zoom(self, event):
        event = copy(event)
        event.key = "x"
        super().drag_zoom(event)

    def release_zoom(self, event):
        if event is not None:
            event = copy(event)
            event.key = "x"
        super().release_zoom(event)

    def draw_rubberband(self, event, x0, y0, x1, y1):
        bounds = [ax.bbox for ax in self.canvas.figure.axes]
        bottom, top = min(box.y0 for box in bounds), max(box.y1 for box in bounds)
        self.canvas.drawRectangle(
            (min(x0, x1), self.canvas.figure.bbox.height - top, abs(x1 - x0), top - bottom)
        )

    def remove_rubberband(self):
        self.canvas.drawRectangle(None)

    def _cleanup_post_zoom(self):
        super()._cleanup_post_zoom()
        # Time-only zoom leaves Y autoscaling enabled throughout the gesture.
        self._automatic_bar_y = []

    def push_current(self):
        if self.time_scroll is not None:
            self.time_scroll.constrain_view()
        super().push_current()

    def _update_view(self):
        super()._update_view()
        if self.time_scroll is not None:
            self.time_scroll.constrain_view()

    def begin_time_scroll(self):
        if self.scrolling_time or not self.canvas.figure.axes:
            return
        if self._zoom_info is not None:
            self._cleanup_post_zoom()
        self._push_changed_view()
        self.scrolling_time = self.canvas.panning = self.canvas.time_scrolling = True
        self._automatic_bar_y = [
            ax
            for ax in self.canvas.figure.axes
            if getattr(ax, "_paradigma_bars", False) and ax.get_autoscaley_on()
        ]
        for ax in self._automatic_bar_y:
            ax.set_autoscaley_on(False)
        self.canvas.prepare_time_scroll()

    def end_time_scroll(self):
        if not self.scrolling_time:
            return
        self.scrolling_time = self.canvas.panning = self.canvas.time_scrolling = False
        self.canvas.finish_time_scroll()
        self.restore_automatic_bar_y()
        self._automatic_bar_y = []
        self._push_changed_view()
        if self.settings_action.isChecked():
            self.settings.read_axes()

    def _push_changed_view(self):
        # Do not add duplicate history entries between successive scroll gestures.
        current = self._nav_stack()
        if current is None or any(
            ax not in current or current[ax][0] != ax._get_view() for ax in self.canvas.figure.axes
        ):
            self.push_current()

    def stop_navigation(self):
        if self.time_scroll is not None:
            self.time_scroll.finish_gesture()
        else:
            self.end_time_scroll()
        if self._zoom_info is not None:
            self._cleanup_post_zoom()

    def refresh(self):
        self.stop_navigation()
        super().refresh()


class ResultTimeScroll(QScrollBar):
    """Map the shared visible time range to a scrollbar without copying plot data."""

    STEPS = 1_000_000_000

    def __init__(self, toolbar, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.toolbar = toolbar
        toolbar.time_scroll = self
        self._source = self._connection = None
        self._setting_limits = False
        self._wheel_position = None
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.setInterval(200)
        self._wheel_timer.timeout.connect(self._finish_wheel)
        self.setAccessibleName("Results time scrollbar")
        self.setToolTip(
            tooltip_text("Zoom into a time interval, then scroll through the full time range.")
        )
        self.setFocusPolicy(Qt.StrongFocus)
        self.setInvertedControls(False)
        self.sliderPressed.connect(toolbar.begin_time_scroll)
        self.sliderReleased.connect(toolbar.end_time_scroll)
        self.valueChanged.connect(self._move)
        self.bind(None)

    def bind(self, source):
        self.finish_gesture()
        if self._source is not None and self._connection is not None:
            self._source.callbacks.disconnect(self._connection)
        with QSignalBlocker(self):
            self.setSliderDown(False)
        self._source, self._connection = source, None
        if source is not None:
            self._full_limits = sorted(source.get_xlim())
            self._connection = source.callbacks.connect("xlim_changed", self.synchronize)
        self.synchronize()

    def synchronize(self, *_):
        if self._setting_limits:
            return
        with QSignalBlocker(self):
            if self._source is None:
                self.setRange(0, 0)
                self.setEnabled(False)
                self.hide()
                self.toolbar._actions["zoom_in"].setEnabled(False)
                self.toolbar._actions["zoom_out"].setEnabled(False)
                return
            left, right = sorted(self._source.get_xlim())
            self._domain = self._full_limits
            duration = self._domain[1] - self._domain[0]
            self._span = min(right - left, duration)
            movable = duration > 0 and not math.isclose(self._span, duration, rel_tol=1e-9)
            page = max(1, round(self.STEPS * self._span / duration)) if movable else self.STEPS
            self.setRange(0, self.STEPS - page)
            self.setPageStep(page)
            self.setSingleStep(max(1, page // 10))
            travel = duration - self._span
            position = round((left - self._domain[0]) / travel * self.maximum()) if movable else 0
            self.setValue(position)
            self.setEnabled(movable)
            self.setVisible(movable)
            self.toolbar._actions["zoom_in"].setEnabled(True)
            self.toolbar._actions["zoom_out"].setEnabled(movable)

    def zoom(self, factor):
        if self._source is None:
            return
        self.finish_gesture()
        self.toolbar._push_changed_view()
        limits = self._source.get_xlim()
        low, high = sorted(limits)
        center = (low + high) / 2
        span = max((high - low) * factor, math.ulp(center) * 16)
        bounds = center - span / 2, center + span / 2
        self._source.set_xlim(*(bounds if limits[0] < limits[1] else bounds[::-1]))
        self.toolbar.push_current()
        self.toolbar.canvas.draw_idle()

    def constrain_view(self):
        if self._source is None:
            return
        limits = self._source.get_xlim()
        low, high = sorted(limits)
        first, last = self._full_limits
        if first <= low and high <= last:
            return
        span = high - low
        if span >= last - first:
            bounded = first, last
        elif low < first:
            bounded = first, first + span
        else:
            bounded = last - span, last
        if limits[0] > limits[1]:
            bounded = bounded[::-1]
        if bounded != limits:
            # Limit changes have finished propagating through the shared axes
            # before the toolbar saves a view or restores navigation history.
            self._source.set_xlim(*bounded, auto=self._source.get_autoscalex_on())

    def watch(self, *widgets):
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel and self._scroll_wheel(event):
            return True
        return super().eventFilter(watched, event)

    def _scroll_wheel(self, event):
        if event.phase() == Qt.ScrollEnd and self._wheel_position is not None:
            self._finish_wheel()
            event.accept()
            return True
        delta = event.pixelDelta() if not event.pixelDelta().isNull() else event.angleDelta()
        horizontal = bool(delta.x()) and abs(delta.x()) >= abs(delta.y())
        shifted = bool(event.modifiers() & Qt.ShiftModifier) and not delta.x() and delta.y()
        if not horizontal and not shifted:
            return False
        event.accept()
        if self._source is None or not self.maximum():
            return True
        if self._wheel_position is None:
            self.toolbar.begin_time_scroll()
            self._wheel_position = float(self.value())
        pixels = delta.x() if horizontal else delta.y()
        if event.pixelDelta().isNull():
            pixels *= 40 / 120
        width = max(1, self._source.bbox.width / self.toolbar.canvas.device_pixel_ratio)
        travel = self._domain[1] - self._domain[0] - self._span
        steps = pixels / width * self._span / travel * self.maximum()
        self._wheel_position = min(self.maximum(), max(0.0, self._wheel_position - steps))
        self.setValue(round(self._wheel_position))
        self._wheel_timer.start()
        return True

    def _finish_wheel(self):
        self._wheel_timer.stop()
        if self._wheel_position is not None:
            self._wheel_position = None
            self.toolbar.end_time_scroll()

    def finish_gesture(self):
        self._finish_wheel()
        self.setSliderDown(False)
        self.toolbar.end_time_scroll()

    def _move(self, value):
        if self._source is None or not self.maximum():
            return
        single_action = not self.toolbar.scrolling_time
        if single_action:
            self.toolbar.begin_time_scroll()
        try:
            travel = self._domain[1] - self._domain[0] - self._span
            left = self._domain[0] + value / self.maximum() * travel
            limits = left, left + self._span
            if self._source.xaxis_inverted():
                limits = limits[::-1]
            self._setting_limits = True
            try:
                self._source.set_xlim(*limits)
            finally:
                self._setting_limits = False
            self.toolbar.canvas.draw_idle()
        finally:
            if single_action:
                self.toolbar.end_time_scroll()

    def hideEvent(self, event):
        self.finish_gesture()
        super().hideEvent(event)
