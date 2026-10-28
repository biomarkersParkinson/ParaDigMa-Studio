"""Time navigation and visible-sample scaling for original sensor graphs."""

from contextlib import contextmanager

from .raw_signals import autoscale_raw_signals
from .time_navigation import TimeScroll, TimeToolbar


class RawToolbar(TimeToolbar):
    def __init__(self, canvas, parent):
        super().__init__(canvas, parent, time_selection=False)
        self._full_time_limits = None
        self._time_axes = self._time_connection = None
        self.time_scroll: TimeScroll = TimeScroll(self, accessible_name="Raw sensor time scrollbar")
        self.time_scroll.watch(canvas)
        self.zoom()

    def _disconnect_time_axis(self):
        if self._time_axes is not None:
            self._time_axes.callbacks.disconnect(self._time_connection)
        self._time_axes = self._time_connection = None

    def _fit_time_view(self, *_):
        if self.scrolling_time or not self.canvas.figure.axes:
            return
        limits = self.canvas.figure.axes[0].get_xlim()
        for ax in self.canvas.figure.axes:
            autoscale_raw_signals(ax, limits)

    def refresh(self):
        super().refresh()
        self._disconnect_time_axis()
        axes = self.canvas.figure.axes
        first = axes[0] if axes and any(ax.has_data() for ax in axes) else None
        if (
            self._full_time_limits is not None
            and self._full_time_limits[0] == self._full_time_limits[1]
        ):
            first = None
        self.time_scroll.bind(first, limits=self._full_time_limits)
        if first is not None:
            self._time_axes = first
            # Sensor-context sample loading connects before this observer, so
            # Y bounds use the newly loaded originals, not the previous window.
            self._time_connection = first.callbacks.connect("xlim_changed", self._fit_time_view)
        self._fit_time_view()

    @contextmanager
    def redraw_channels(self, *, preserve_view=False, time_limits=None):
        """Keep time and manual sensor-group limits while rebuilding channels."""
        self.stop_navigation()
        axes = self.canvas.figure.axes
        active_group = (
            self.active_axes.get_label() if preserve_view and self.active_axes in axes else None
        )
        view = None
        if (
            preserve_view
            and axes
            and any(not ax.get_autoscalex_on() or not ax.get_autoscaley_on() for ax in axes)
        ):
            view = (
                axes[0].get_xlim(),
                axes[0].get_autoscalex_on(),
                {ax.get_label(): ax.get_ylim() for ax in axes if not ax.get_autoscaley_on()},
            )
        self.time_scroll.bind(None)
        self._disconnect_time_axis()
        yield
        self._full_time_limits = time_limits
        self.refresh()
        if active_group is not None:
            self.active_axes = next(
                (ax for ax in self.canvas.figure.axes if ax.get_label() == active_group), None
            )
        if view is not None:
            # Seed Home before restoring the zoom; every history entry must
            # reference the new axes created for the current channel selection.
            self.push_current()
            x_limits, automatic_x, y_limits = view
            for ax in self.canvas.figure.axes:
                ax.set_xlim(*x_limits, auto=automatic_x, emit=False)
                if ax.get_label() in y_limits:
                    ax.set_ylim(*y_limits[ax.get_label()])
            self.push_current()
        self.time_scroll.synchronize()
        if self.settings_action.isChecked():
            self.settings.read_axes()
