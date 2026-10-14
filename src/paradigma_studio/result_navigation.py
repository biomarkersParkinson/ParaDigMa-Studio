"""Time-only navigation for Results, independent of raw sensor controls."""

import math
from copy import copy

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QScrollBar

from .plot_controls import GraphToolbar
from .theme import tooltip_text


class ResultsToolbar(GraphToolbar):
    toolitems = tuple(item for item in GraphToolbar.toolitems if item[0] != "Pan")

    def __init__(self, canvas, parent):
        super().__init__(canvas, parent)
        self.scrolling_time = False
        self._actions["zoom"].setToolTip("Select a time interval to zoom into all linked graphs")

    def pan(self, *args):
        """Results use the time scrollbar; raw graph toolbars retain panning."""

    def drag_zoom(self, event):
        event = copy(event)
        event.key = "x"
        super().drag_zoom(event)

    def release_zoom(self, event):
        if event is not None:
            event = copy(event)
            event.key = "x"
        super().release_zoom(event)

    def begin_time_scroll(self):
        if self.scrolling_time or not self.canvas.figure.axes:
            return
        if self._zoom_info is not None:
            self._cleanup_post_zoom()
        self._push_changed_view()
        self.scrolling_time = self.canvas.panning = True
        self._automatic_bar_y = [
            ax
            for ax in self.canvas.figure.axes
            if getattr(ax, "_paradigma_bars", False) and ax.get_autoscaley_on()
        ]
        for ax in self._automatic_bar_y:
            ax.set_autoscaley_on(False)

    def end_time_scroll(self):
        if not self.scrolling_time:
            return
        self.scrolling_time = self.canvas.panning = False
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

    def refresh(self):
        self.end_time_scroll()
        if self._zoom_info is not None:
            self._cleanup_post_zoom()
            self._automatic_bar_y = []
        super().refresh()


class ResultTimeScroll(QScrollBar):
    """Map the shared visible time range to a scrollbar without copying plot data."""

    STEPS = 1_000_000_000

    def __init__(self, toolbar, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.toolbar = toolbar
        self._source = self._connection = None
        self._setting_limits = False
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
        self.toolbar.end_time_scroll()
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
                return
            left, right = sorted(self._source.get_xlim())
            # Explicit axis limits may extend outside the recording. Retain that
            # view and include it in the scrollable range until limits change.
            self._domain = min(left, self._full_limits[0]), max(right, self._full_limits[1])
            self._span = right - left
            duration = self._domain[1] - self._domain[0]
            movable = duration > 0 and not math.isclose(self._span, duration, rel_tol=1e-9)
            page = max(1, round(self.STEPS * self._span / duration)) if movable else self.STEPS
            self.setRange(0, self.STEPS - page)
            self.setPageStep(page)
            self.setSingleStep(max(1, page // 10))
            travel = duration - self._span
            position = round((left - self._domain[0]) / travel * self.maximum()) if movable else 0
            self.setValue(position)
            self.setEnabled(movable)

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
        self.setSliderDown(False)
        self.toolbar.end_time_scroll()
        super().hideEvent(event)
