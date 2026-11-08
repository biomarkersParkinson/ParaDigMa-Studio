"""Shared time-only selection, history and scrolling for linked graphs."""

from __future__ import annotations

import math
from copy import copy
from typing import TYPE_CHECKING, cast

from matplotlib.backend_bases import MouseButton
from matplotlib.backend_tools import Cursors
from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QHideEvent, QIcon, QWheelEvent
from PySide6.QtWidgets import QScrollBar

from .assets import DATA_DIRECTORY
from .contracts import TimeLimits
from .plot_controls import GraphToolbar
from .theme import tooltip_text

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.backend_bases import Event, MouseEvent
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from PySide6.QtWidgets import QWidget

    class _DragMouseEvent(MouseEvent):
        # Matplotlib 3.10 provides held buttons; its stubs omit this attribute.
        buttons: set[MouseButton]


class TimeToolbar(GraphToolbar):
    # Matplotlib registers these handlers only for mouse events, despite the
    # broader Event signatures in its base-class stubs.
    canvas: FigureCanvasQTAgg

    def __init__(
        self, canvas: FigureCanvasQTAgg, parent: QWidget | None, *, time_selection: bool = True
    ) -> None:
        super().__init__(canvas, parent, time_selection=time_selection)
        self.scrolling_time = False
        self.time_scroll: TimeScroll | None = None
        self._time_pan: tuple[float, tuple[float, float], float] | None = None
        self._actions["pan"].setText("Drag time")
        self._actions["pan"].setIcon(QIcon(str(DATA_DIRECTORY / "drag-time.svg")))
        self._actions["pan"].setToolTip("Drag left or right to move all linked graphs through time")
        self._actions["zoom"].setText("Select time interval")
        self._actions["zoom"].setIcon(QIcon(str(DATA_DIRECTORY / "select-interval.svg")))
        self._actions["zoom"].setToolTip("Select a time interval to zoom into all linked graphs")
        self.add_time_zoom_actions(self.zoom_time)

    def zoom_time(self, factor: float) -> None:
        if self.time_scroll is not None:
            self.time_scroll.zoom(factor)

    def pan(self, *args: object) -> None:
        self.stop_navigation()
        super().pan(*args)
        self._last_cursor = Cursors.MOVE if self.mode.name == "PAN" else Cursors.POINTER
        self.canvas.set_cursor(self._last_cursor)

    def zoom(self, *args: object) -> None:
        self.stop_navigation()
        super().zoom(*args)
        self._last_cursor = Cursors.SELECT_REGION if self.mode.name == "ZOOM" else Cursors.POINTER
        self.canvas.set_cursor(self._last_cursor)

    def press_pan(self, event: Event) -> None:
        event = cast("MouseEvent", event)
        self.stop_navigation()
        event = self._time_event(event)
        bar = self.time_scroll
        if (
            event.button != MouseButton.LEFT
            or event.inaxes is None
            or bar is None
            or bar._source is None
            or not bar.maximum()
        ):
            return
        self.begin_time_scroll()
        super().press_pan(event)
        if self._pan_info is None:
            self.end_time_scroll()
            return
        self._time_pan = event.x, bar._source.get_xlim(), event.inaxes.bbox.width
        self.canvas.set_cursor(Cursors.MOVE)

    def drag_pan(self, event: Event) -> None:
        event = cast("MouseEvent", event)
        if self._time_pan is None:
            return
        if cast("_DragMouseEvent", event).buttons != {MouseButton.LEFT}:
            self.release_pan(None)
            return
        if event.x is None:
            return
        bar = self.time_scroll
        if bar is not None and bar._source is not None:
            start, (left, right), width = self._time_pan
            delta = (start - event.x) / width * (right - left)
            limits = bar.bounded_limits((left + delta, right + delta))
            if limits != bar._source.get_xlim():
                # Only X changes: Axes.drag_pan would also mark Y as manual.
                bar._source.set_xlim(*limits)
                self.canvas.draw_idle()

    def release_pan(self, event: Event | None) -> None:
        event = cast("MouseEvent | None", event)
        if self._pan_info is None:
            return
        self._time_pan = None
        super().release_pan(cast("Event", event))
        self.end_time_scroll()
        if event is not None:
            self._update_cursor(event)
        self.canvas.set_cursor(self._last_cursor)

    def home(self, *args: object) -> None:
        self.stop_navigation()
        super().home(*args)

    def back(self, *args: object) -> None:
        self.stop_navigation()
        super().back(*args)

    def forward(self, *args: object) -> None:
        self.stop_navigation()
        super().forward(*args)

    def press_zoom(self, event: Event) -> None:
        event = cast("MouseEvent", event)
        self.stop_navigation()
        event = self._time_event(event)
        if event.inaxes is not None and self._nav_stack() is None:
            # Save Home before GraphToolbar captures automatic Y axes. A
            # time-only selection needs no Y refit or graph redraw on press.
            self.push_current()
        super().press_zoom(event)

    def _time_event(self, event: MouseEvent) -> MouseEvent:
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

    def _update_cursor(self, event: MouseEvent) -> None:
        if self.mode.name in ("PAN", "ZOOM"):
            event = self._time_event(event)
        super()._update_cursor(event)

    def drag_zoom(self, event: Event) -> None:
        event = cast("MouseEvent", event)
        event = copy(event)
        event.key = "x"
        super().drag_zoom(event)

    def release_zoom(self, event: Event | None) -> None:
        event = cast("MouseEvent | None", event)
        if event is not None:
            event = copy(event)
            event.key = "x"
        super().release_zoom(event)

    def draw_rubberband(self, event: Event, x0: float, y0: float, x1: float, y1: float) -> None:
        bounds = [ax.bbox for ax in self.canvas.figure.axes]
        bottom, top = min(box.y0 for box in bounds), max(box.y1 for box in bounds)
        self.canvas.drawRectangle(
            (min(x0, x1), self.canvas.figure.bbox.height - top, abs(x1 - x0), top - bottom)
        )

    def remove_rubberband(self) -> None:
        self.canvas.drawRectangle(None)

    def _cleanup_post_zoom(self) -> None:
        super()._cleanup_post_zoom()
        # Time-only zoom leaves Y autoscaling enabled throughout the gesture.
        self._automatic_bar_y = []

    def push_current(self) -> None:
        # Matplotlib releases its mouse capture before asking to save the pan.
        # Save once, after end_time_scroll restores automatic Y limits instead.
        if self.scrolling_time:
            return
        if self.time_scroll is not None:
            self.time_scroll.constrain_view()
        self._fit_time_view()
        super().push_current()

    def _update_view(self) -> None:
        super()._update_view()
        if self.time_scroll is not None:
            self.time_scroll.constrain_view()
        self._fit_time_view()

    def _fit_time_view(self) -> None:
        """Refit automatic axes after a settled time change, if required."""

    def autoscale_axis(self, ax: Axes, axis: str) -> None:
        if axis == "x" and self.time_scroll is not None and self.time_scroll._source is not None:
            # Sensor context loads only a window. Its current data limits do
            # not describe the full recording available to the time controls.
            ax.set_xlim(*self.time_scroll._full_limits, auto=True)
        else:
            super().autoscale_axis(ax, axis)

    def begin_time_scroll(self) -> None:
        if self.scrolling_time or not self.canvas.figure.axes:
            return
        if self._zoom_info is not None:
            self._cleanup_post_zoom()
        self._push_changed_view()
        self.scrolling_time = True
        self._prepare_time_scroll()

    def _prepare_time_scroll(self) -> None:
        """Allow a renderer to hold automatic Y limits stable during a drag."""

    def end_time_scroll(self) -> None:
        if not self.scrolling_time:
            return
        self.scrolling_time = False
        self._finish_time_scroll()
        self._push_changed_view()
        if self.settings_action.isChecked():
            self.settings.read_axes()

    def _finish_time_scroll(self) -> None:
        self._fit_time_view()
        self.canvas.draw_idle()

    def _push_changed_view(self) -> None:
        # Do not add duplicate history entries between successive scroll gestures.
        current = self._nav_stack()
        if current is None or any(
            # Matplotlib's history uses this view snapshot but omits its type stub.
            ax not in current or current[ax][0] != ax._get_view()  # type: ignore[attr-defined]
            for ax in self.canvas.figure.axes
        ):
            self.push_current()

    def stop_navigation(self) -> None:
        if self.time_scroll is not None:
            self.time_scroll.finish_gesture()
        else:
            self.end_time_scroll()
        if self._zoom_info is not None:
            self._cleanup_post_zoom()

    def refresh(self) -> None:
        self.stop_navigation()
        super().refresh()


class TimeScroll(QScrollBar):
    """Map the shared visible time range to a scrollbar without copying plot data."""

    STEPS = 1_000_000_000

    def __init__(
        self,
        toolbar: TimeToolbar,
        parent: QWidget | None = None,
        *,
        accessible_name: str = "Time scrollbar",
    ) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.toolbar = toolbar
        toolbar.time_scroll = self
        self._source: Axes | None = None
        self._connection: int | None = None
        self._setting_limits = False
        self._wheel_position: float | None = None
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.setInterval(200)
        self._wheel_timer.timeout.connect(self._finish_wheel)
        self.setAccessibleName(accessible_name)
        self.setToolTip(
            tooltip_text("Zoom into a time interval, then scroll through the full time range.")
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setInvertedControls(False)
        self.sliderPressed.connect(toolbar.begin_time_scroll)
        self.sliderReleased.connect(toolbar.end_time_scroll)
        self.valueChanged.connect(self._move)
        self.bind(None)

    def bind(self, source: Axes | None, *, limits: TimeLimits | None = None) -> None:
        self.finish_gesture()
        if self._source is not None and self._connection is not None:
            self._source.callbacks.disconnect(self._connection)
        with QSignalBlocker(self):
            self.setSliderDown(False)
        self._source, self._connection = source, None
        if source is not None:
            self._full_limits = sorted(source.get_xlim() if limits is None else limits)
            self._connection = source.callbacks.connect("xlim_changed", self.synchronize)
        self.synchronize()

    def synchronize(self, *_: object) -> None:
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
            minimum = self._minimum_span(left, right)
            self.toolbar._actions["zoom_in"].setEnabled(bool(right - left > minimum * (1 + 1e-9)))
            self.toolbar._actions["zoom_out"].setEnabled(movable)

    def _minimum_span(self, low: float, high: float) -> float:
        return math.ulp(max(abs(low), abs(high), *(abs(x) for x in self._full_limits), 1.0)) * 16

    def zoom(self, factor: float) -> None:
        if self._source is None:
            return
        self.toolbar.stop_navigation()
        self.toolbar._push_changed_view()
        limits = self._source.get_xlim()
        low, high = sorted(limits)
        center = (low + high) / 2
        span = max((high - low) * factor, self._minimum_span(low, high))
        bounds = center - span / 2, center + span / 2
        self._source.set_xlim(*(bounds if limits[0] < limits[1] else bounds[::-1]))
        self.toolbar.push_current()
        self.toolbar.canvas.draw_idle()

    def constrain_view(self) -> None:
        if self._source is None:
            return
        limits = self._source.get_xlim()
        bounded = self.bounded_limits(limits)
        if bounded != limits:
            # Limit changes have finished propagating through the shared axes
            # before the toolbar saves a view or restores navigation history.
            self._source.set_xlim(*bounded, auto=self._source.get_autoscalex_on())

    def bounded_limits(self, limits: TimeLimits) -> TimeLimits:
        """Clamp a time window before notifying renderers or loading raw samples."""
        low, high = sorted(limits)
        first, last = self._full_limits
        if first <= low and high <= last:
            return limits
        span = high - low
        if span >= last - first:
            bounded = first, last
        elif low < first:
            bounded = first, first + span
        else:
            bounded = last - span, last
        if limits[0] > limits[1]:
            bounded = bounded[::-1]
        return bounded

    def watch(self, *widgets: QWidget) -> None:
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel and self._scroll_wheel(cast(QWheelEvent, event)):
            return True
        return super().eventFilter(watched, event)

    def _scroll_wheel(self, event: QWheelEvent) -> bool:
        if event.phase() == Qt.ScrollPhase.ScrollEnd and self._wheel_position is not None:
            self._finish_wheel()
            event.accept()
            return True
        delta = event.pixelDelta() if not event.pixelDelta().isNull() else event.angleDelta()
        horizontal = bool(delta.x()) and abs(delta.x()) >= abs(delta.y())
        shifted = (
            bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            and not delta.x()
            and delta.y()
        )
        if not horizontal and not shifted:
            return False
        event.accept()
        if self._source is None or not self.maximum():
            return True
        if self._wheel_position is None:
            self.toolbar.begin_time_scroll()
            self._wheel_position = float(self.value())
        pixels: float = delta.x() if horizontal else delta.y()
        if event.pixelDelta().isNull():
            pixels *= 40 / 120
        width = max(1, self._source.bbox.width / self.toolbar.canvas.device_pixel_ratio)
        travel = self._domain[1] - self._domain[0] - self._span
        steps = pixels / width * self._span / travel * self.maximum()
        self._wheel_position = min(self.maximum(), max(0.0, self._wheel_position - steps))
        self.setValue(round(self._wheel_position))
        self._wheel_timer.start()
        return True

    def _finish_wheel(self) -> None:
        self._wheel_timer.stop()
        if self._wheel_position is not None:
            self._wheel_position = None
            self.toolbar.end_time_scroll()

    def finish_gesture(self) -> None:
        self.toolbar.release_pan(None)
        self._finish_wheel()
        self.setSliderDown(False)
        self.toolbar.end_time_scroll()

    def _move(self, value: int) -> None:
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

    def hideEvent(self, event: QHideEvent) -> None:
        self.finish_gesture()
        super().hideEvent(event)
