"""A recording-time ruler outside the Results scrolling viewport."""
from matplotlib import dates, ticker
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from PySide6.QtCore import QPoint


class RecordingTimeFormatter(ticker.Formatter):
    """Time on the first line; date at the first visible tick and day changes."""
    def __init__(self, timezone=None):
        self.timezone = timezone
        self._dates = {}
        self._offset_ticks = set()
        self._subsecond = False

    def set_locs(self, locs):
        super().set_locs(locs)
        low, high = sorted(self.axis.get_view_interval())
        previous = None
        self._dates = {}
        visible = {}
        for value in locs:
            if low <= value <= high:
                stamp = dates.num2date(value, tz=self.timezone)
                visible[float(value)] = stamp
                day = stamp.date()
                self._dates[float(value)] = stamp.strftime("%d %b %Y") if day != previous else ""
                previous = day
        offsets = {}
        for stamp in visible.values():
            offsets.setdefault(stamp.strftime("%Y-%m-%d %H:%M"), set()).add(stamp.utcoffset())
        ticks = sorted(visible)
        self._subsecond = any(0 < (second - first) * 86400 < .999
                              for first, second in zip(ticks, ticks[1:]))
        self._offset_ticks = {value for value, stamp in visible.items()
                              if len(offsets[stamp.strftime("%Y-%m-%d %H:%M")]) > 1}

    def __call__(self, value, pos=None):
        span = abs(self.axis.get_view_interval()[1] - self.axis.get_view_interval()[0]) * 86400
        stamp = dates.num2date(value, tz=self.timezone)
        time = stamp.strftime("%H:%M:%S" if span < 120 else "%H:%M")
        if span < 2 or self._subsecond:
            time += stamp.strftime(".%f")[:4]
        # Offset distinguishes repeated local times at a daylight-saving change.
        if float(value) in self._offset_ticks:
            time += stamp.strftime(" %z")
        return time + "\n" + self._dates.get(float(value), "")


class PinnedTimeAxis(FigureCanvasQTAgg):
    def __init__(self, source_canvas, label_source):
        super().__init__(Figure(figsize=(8, .82)))
        self.setFixedHeight(82)
        self.setAccessibleName("Pinned recording time axis")
        self.source_canvas = source_canvas
        self.label_source = label_source
        self.figure.set_facecolor("white")
        self.axes = self.figure.add_axes((.1, .78, .85, .1))
        self.axes.yaxis.set_visible(False)
        for side in ("top", "right", "left"):
            self.axes.spines[side].set_visible(False)
        self.axes.spines["bottom"].set_color("#DFE6EF")
        self.axes.tick_params(axis="x", colors="#60728A", labelsize=9, length=3, pad=6)
        self.axes.xaxis.label.set_color("#465B73")
        self.axes.xaxis.label.set_size(10)
        self._source = None
        self._source_connection = None
        self._sync_state = None
        self._selection_state = None
        self._deferred_draw = False
        self._date_timezone = None
        self.selection_marker = Line2D([], [], marker="v", markersize=6, color="#465B73",
                                       linestyle="none", transform=self.axes.get_xaxis_transform(), clip_on=False, zorder=5)
        self.axes.add_artist(self.selection_marker)
        self.selection_label = self.axes.text(1, 1.8, "", transform=self.axes.transAxes,
                                              ha="right", va="top", fontsize=8.5, color="#465B73")
        self._selected_x = None
        self.set_selection(None)
        source_canvas.mpl_connect("draw_event", self.synchronize)

    def bind(self, source):
        if self._source is not None and self._source_connection is not None:
            self._source.callbacks.disconnect(self._source_connection)
        self._source = source
        self._source_connection = None
        self._sync_state = None
        self.set_selection(None)
        self.axes.set_visible(source is not None)
        if source is not None:
            self._source_connection = source.callbacks.connect("xlim_changed", self.synchronize)
            locator = source.xaxis.get_major_locator()
            if isinstance(locator, dates.DateLocator):
                self._date_timezone = locator.tz
                locator = dates.AutoDateLocator(tz=locator.tz, minticks=3, maxticks=7)
                self.axes.xaxis.set_major_locator(locator)
                self.axes.xaxis.set_major_formatter(RecordingTimeFormatter(locator.tz))
                self.setFixedHeight(102)
            else:
                self._date_timezone = None
                self.setFixedHeight(82)
                self.axes.xaxis.set_major_locator(ticker.MaxNLocator(nbins=6))
                self.axes.xaxis.set_major_formatter(ticker.ScalarFormatter(useOffset=False))
        else:
            self.draw_idle()
        self.synchronize()

    def set_selection(self, x, label=""):
        state = x, label, self._source is not None
        if state == self._selection_state:
            return
        self._selection_state = state
        self._selected_x = x
        visible = x is not None and self._source is not None
        self._update_selection_visibility()
        self.selection_label.set_visible(visible)
        self.selection_marker.set_data([] if x is None else [x], [] if x is None else [0])
        self.selection_label.set_text(label)
        self.draw_idle()

    def _update_selection_visibility(self):
        low, high = sorted(self.axes.get_xlim())
        visible = self._source is not None and self._selected_x is not None and low <= self._selected_x <= high
        self.selection_marker.set_visible(visible)

    def synchronize(self, *_):
        if self._source is None or self.source_canvas.exporting_time_axis:
            return
        source = self._source
        origin = self.mapFromGlobal(self.source_canvas.mapToGlobal(QPoint(0, 0))).x()
        bounds = source.get_position()
        width = max(1, self.width())
        left = (origin + bounds.x0 * self.source_canvas.width()) / width
        right = (origin + bounds.x1 * self.source_canvas.width()) / width
        limits = source.get_xlim()
        label = self.label_source()
        text = label.get_xlabel() if label is not None else source.get_xlabel()
        state = left, right, width, self.height(), limits, text
        if state == self._sync_state:
            return
        self._sync_state = state
        self.axes.set_position((left, .78, max(.01, right - left), .1))
        self.axes.set_xlim(limits, emit=False)
        self._update_selection_visibility()
        self.axes.set_xlabel(text, labelpad=8)
        self.draw_idle()

    def draw_idle(self):
        if not self.isVisible():
            self._deferred_draw = True
            return
        super().draw_idle()

    def showEvent(self, event):
        super().showEvent(event)
        if self._deferred_draw:
            self._deferred_draw = False
            super().draw_idle()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.synchronize()
