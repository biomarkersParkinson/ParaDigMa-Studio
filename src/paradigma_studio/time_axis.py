"""A recording-time ruler outside the Results scrolling viewport."""

from matplotlib import dates, ticker
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from PySide6.QtCore import QPoint, Signal

from .day_axis import RecordingDayFormatter, RecordingDayLocator
from .epoch_axis import style_epoch_axis
from .plotting import time_selection_triangle
from .profile_axis import style_profile_axis


class RecordingDateLocator(dates.AutoDateLocator):
    """Reuse identical tick positions across the shared graphs in one view.

    Matplotlib queries a locator repeatedly while drawing ticks and spines.
    Calendar ticks depend on the time limits; a new range recomputes them.
    """

    def __call__(self):
        limits = tuple(self.axis.get_view_interval())
        if limits != getattr(self, "_cached_limits", None):
            locations = super().__call__()
            self._cached_limits, self._cached_locations = limits, locations
        return self._cached_locations


class RecordingTimeFormatter(ticker.Formatter):
    """Time on the first line; date at the first visible tick and day changes."""

    def __init__(self, timezone=None, *, show_date=True):
        self.timezone = timezone
        self.show_date = show_date
        self._dates = {}
        self._offset_ticks = set()
        self._subsecond = False
        self._layout_key = None
        self._labels = {}

    def set_locs(self, locs):
        super().set_locs(locs)
        low, high = sorted(self.axis.get_view_interval())
        key = tuple(locs), low, high
        if key == self._layout_key:
            return
        self._layout_key = key
        self._labels.clear()
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
        self._subsecond = any(
            0 < (second - first) * 86400 < 0.999
            for first, second in zip(ticks, ticks[1:], strict=False)
        )
        self._offset_ticks = {
            value
            for value, stamp in visible.items()
            if len(offsets[stamp.strftime("%Y-%m-%d %H:%M")]) > 1
        }

    def __call__(self, value, pos=None):
        low, high = sorted(self.axis.get_view_interval())
        if self._layout_key is None or self._layout_key[1:] != (low, high):
            self.set_locs(self.locs)
        if float(value) in self._labels:
            return self._labels[float(value)]
        span = abs(self.axis.get_view_interval()[1] - self.axis.get_view_interval()[0]) * 86400
        stamp = dates.num2date(value, tz=self.timezone)
        time = stamp.strftime("%H:%M:%S" if span < 120 else "%H:%M")
        if span < 2 or self._subsecond:
            time += stamp.strftime(".%f")[:4]
        # Offset distinguishes repeated local times at a daylight-saving change.
        if float(value) in self._offset_ticks:
            time += stamp.strftime(" %z")
        text = time + "\n" + self._dates.get(float(value), "") if self.show_date else time
        self._labels[float(value)] = text
        return text


class PinnedTimeAxis(FigureCanvasQTAgg):
    label_changed = Signal(str)

    def __init__(self, source_canvas, label_source):
        super().__init__(Figure(figsize=(8, 0.82)))
        self.setFixedHeight(42)
        self.setAccessibleName("Pinned recording time axis")
        self.source_canvas = source_canvas
        self.label_source = label_source
        self.figure.set_facecolor("white")
        self.axes = self.figure.add_axes((0.1, 0.62, 0.85, 0.1))
        # The ruler has no native title or caption. Its caption occupies a Qt
        # row, so automatic title/label placement only repeats tick-bound scans.
        self.axes.set_title("", y=1.0)
        self.axes.xaxis.set_label_coords(0.5, 0)
        self.axes.yaxis.set_visible(False)
        for side in ("top", "right", "left"):
            self.axes.spines[side].set_visible(False)
        self.axes.spines["bottom"].set_color("#DFE6EF")
        self.axes.tick_params(axis="x", colors="#60728A", labelsize=9, length=3, pad=6)
        self.axes.xaxis.label.set_color("#465B73")
        self.axes.xaxis.label.set_size(10)
        # The live label shares a Qt row with sensor inspection. Figure exports
        # retain the original Matplotlib axis label on the source canvas.
        self.axes.xaxis.label.set_visible(False)
        self._label_text = ""
        self._source = None
        self._source_connection = None
        self._format_state = None
        self._defer_source_draw = False
        self._sync_state = None
        self._selection_state = None
        self._deferred_draw = False
        self._date_timezone = None
        self.selection_marker = Line2D(
            [],
            [],
            marker=time_selection_triangle(),
            markersize=6,
            color="#465B73",
            linestyle="none",
            transform=self.axes.get_xaxis_transform(),
            clip_on=False,
            zorder=5,
        )
        self.axes.add_artist(self.selection_marker)
        self.selection_label = self.axes.text(
            1,
            0.9,
            "",
            transform=self.axes.transAxes,
            ha="right",
            va="bottom",
            fontsize=8.5,
            color="#465B73",
        )
        self._selected_x = None
        self.set_selection(None)
        source_canvas.mpl_connect("draw_event", self._source_drawn)

    @staticmethod
    def _source_format(source):
        locator = source.xaxis.get_major_locator()
        return (
            bool(getattr(source, "_paradigma_profile", False)),
            bool(getattr(source, "_paradigma_day_groups", False)),
            isinstance(locator, RecordingDayLocator),
            isinstance(locator, dates.DateLocator),
            str(getattr(locator, "timezone", getattr(locator, "tz", None))),
            getattr(locator, "calendar", None),
            getattr(locator, "split_year", None),
        )

    def bind(self, source, *, defer=False):
        self._defer_source_draw = defer
        state = self._source_format(source) if source is not None else None
        if source is not None and source is self._source and state == self._format_state:
            self.synchronize()
            return
        if self._source is not None and self._source_connection is not None:
            self._source.callbacks.disconnect(self._source_connection)
        self._source = source
        self._source_connection = None
        self._sync_state = None
        self.set_selection(None)
        self.axes.set_visible(source is not None)
        if source is not None:
            self._source_connection = source.callbacks.connect("xlim_changed", self.synchronize)
            if state != self._format_state:
                self._configure_source(source)
        else:
            self._label_text = ""
            self.label_changed.emit("")
            self.draw_idle()
        self._format_state = state
        self.synchronize()

    def _configure_source(self, source):
        self.axes.xaxis.set_minor_locator(ticker.NullLocator())
        self.axes.xaxis.set_minor_formatter(ticker.NullFormatter())
        self.axes.xaxis.remove_overlapping_locs = True
        self.axes.tick_params(axis="x", which="major", colors="#60728A", length=3, pad=6)
        locator = source.xaxis.get_major_locator()
        if getattr(source, "_paradigma_profile", False):
            self._date_timezone = None
            style_profile_axis(self.axes, labels=True)
            self.setFixedHeight(42)
        elif getattr(source, "_paradigma_day_groups", False):
            self._date_timezone = locator.timezone if locator.calendar else None
            style_epoch_axis(
                self.axes,
                locator.timezone,
                calendar=locator.calendar,
                clock_formatter=RecordingTimeFormatter(locator.timezone, show_date=False),
                labels=True,
            )
            self.setFixedHeight(62)
        elif isinstance(locator, RecordingDayLocator):
            self._date_timezone = locator.timezone if locator.calendar else None
            self.axes.xaxis.set_major_locator(
                RecordingDayLocator(
                    locator.timezone, calendar=locator.calendar, split_year=locator.split_year
                )
            )
            self.axes.xaxis.set_major_formatter(
                RecordingDayFormatter(
                    locator.timezone, calendar=locator.calendar, split_year=locator.split_year
                )
            )
            self.setFixedHeight(62 if locator.calendar else 42)
        elif isinstance(locator, dates.DateLocator):
            self._date_timezone = locator.tz
            locator = RecordingDateLocator(tz=locator.tz, minticks=3, maxticks=7)
            self.axes.xaxis.set_major_locator(locator)
            self.axes.xaxis.set_major_formatter(RecordingTimeFormatter(locator.tz))
            self.setFixedHeight(62)
        else:
            self._date_timezone = None
            self.setFixedHeight(42)
            self.axes.xaxis.set_major_locator(ticker.MaxNLocator(nbins=6))
            self.axes.xaxis.set_major_formatter(ticker.ScalarFormatter(useOffset=False))

    def _source_drawn(self, *_):
        if self.source_canvas.exporting_time_axis:
            return
        pending = self._defer_source_draw
        self._defer_source_draw = False
        self.synchronize()
        if pending:
            self.draw_idle()

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
        visible = (
            self._source is not None
            and self._selected_x is not None
            and low <= self._selected_x <= high
        )
        self.selection_marker.set_visible(visible)

    def synchronize(self, *_):
        if self._source is None or self.source_canvas.exporting_time_axis:
            return
        source = self._source
        origin = self.mapFromGlobal(self.source_canvas.mapToGlobal(QPoint(0, 0))).x()
        # get_position() reapplies aspect and marks an otherwise unchanged
        # source figure stale. The pinned ruler is only reading its geometry.
        old_bounds = source._position.bounds
        axis_dirty, figure_dirty = source.stale, source.figure.stale
        bounds = source.get_position()
        if old_bounds == bounds.bounds:
            source.stale = axis_dirty
            source.figure.stale = figure_dirty
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
        # Two-line calendar ticks need more room below the baseline; the
        # selected timestamp sits above it inside the same fixed-height ruler.
        bottom = 0.70 if self.height() == 62 else 0.62
        self.axes.set_position((left, bottom, max(0.01, right - left), 0.1))
        self.axes.set_xlim(limits, emit=False)
        self._update_selection_visibility()
        self.axes.set_xlabel(text, labelpad=8)
        self.axes.xaxis.label.set_visible(False)
        if text != self._label_text:
            self._label_text = text
            self.label_changed.emit(text)
        self.draw_idle()

    def draw_idle(self):
        if self._defer_source_draw:
            return
        if not self.isVisible():
            self._deferred_draw = True
            return
        super().draw_idle()

    def draw(self):
        # A timer queued before a selection batch must not paint its temporary
        # ruler geometry. The source draw schedules the final ruler afterward.
        if not self._defer_source_draw or self.is_saving():
            return super().draw()

    def showEvent(self, event):
        super().showEvent(event)
        if self._deferred_draw:
            self._deferred_draw = False
            self.draw_idle()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.synchronize()
