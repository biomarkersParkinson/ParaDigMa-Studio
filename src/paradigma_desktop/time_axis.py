"""A recording-time ruler outside the Results scrolling viewport."""
from matplotlib import dates, ticker
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from PySide6.QtCore import QPoint


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
        self._source = source
        self.set_selection(None)
        self.axes.set_visible(source is not None)
        if source is not None:
            source.callbacks.connect("xlim_changed", self.synchronize)
            locator = source.xaxis.get_major_locator()
            if isinstance(locator, dates.DateLocator):
                self._date_timezone = locator.tz
                locator = dates.AutoDateLocator(tz=locator.tz, minticks=3, maxticks=7)
                self.axes.xaxis.set_major_locator(locator)
                self.axes.xaxis.set_major_formatter(dates.ConciseDateFormatter(locator, tz=locator.tz))
            else:
                self._date_timezone = None
                self.axes.xaxis.set_major_locator(ticker.MaxNLocator(nbins=6))
                self.axes.xaxis.set_major_formatter(ticker.ScalarFormatter(useOffset=False))
        self.synchronize()

    def set_selection(self, x, label=""):
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
            self.draw_idle()
            return
        source = self._source
        origin = self.mapFromGlobal(self.source_canvas.mapToGlobal(QPoint(0, 0))).x()
        bounds = source.get_position()
        width = max(1, self.width())
        left = (origin + bounds.x0 * self.source_canvas.width()) / width
        right = (origin + bounds.x1 * self.source_canvas.width()) / width
        self.axes.set_position((left, .78, max(.01, right - left), .1))
        self.axes.set_xlim(source.get_xlim(), emit=False)
        self._update_selection_visibility()
        label = self.label_source()
        self.axes.set_xlabel(label.get_xlabel() if label is not None else source.get_xlabel(), labelpad=8)
        self.draw_idle()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.synchronize()
