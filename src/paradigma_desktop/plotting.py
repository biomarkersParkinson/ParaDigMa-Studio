"""Scientific plot presentation: original values, exact state timestamps, scrolling."""
import numpy as np
import pandas as pd
from matplotlib import dates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg


GRAPH_COLORS = ("#2864A5", "#168B82", "#C78235", "#7D64AB", "#C05F74",
                "#527E94", "#8C843C", "#A65D40", "#6474B1", "#498B64")


class ScrollableFigureCanvas(FigureCanvasQTAgg):
    """Qt canvas wheel events scroll the enclosing Results workspace."""
    scroll_area = None
    outer_scroll_area = None
    pinned_time_axis = False
    exporting_time_axis = False
    _wheel_remainder = 0.

    def wheelEvent(self, event):
        if self.scroll_area is None:
            return super().wheelEvent(event)
        bar = self.scroll_area.verticalScrollBar()
        delta = event.pixelDelta().y() or event.angleDelta().y() / 120 * bar.singleStep() * 3
        if delta:
            if self.outer_scroll_area is not None and (
                    delta > 0 and bar.value() == bar.minimum()
                    or delta < 0 and bar.value() == bar.maximum()):
                bar = self.outer_scroll_area.verticalScrollBar()
            self._wheel_remainder += delta
            movement = round(self._wheel_remainder)
            self._wheel_remainder -= movement
            bar.setValue(bar.value() - movement)
            event.accept()
        else:
            event.ignore()

    def print_figure(self, *args, **kwargs):
        # The workspace has a separate, pinned axis. Saved figures must remain
        # self-contained and include that axis within the exported image.
        if not self.pinned_time_axis or not self.figure.axes:
            return super().print_figure(*args, **kwargs)
        axis = self.figure.axes[-1]
        self.exporting_time_axis = True
        axis.tick_params(axis="x", labelbottom=True)
        axis.xaxis.label.set_visible(True)
        axis.xaxis.offsetText.set_visible(True)
        try:
            return super().print_figure(*args, **kwargs)
        finally:
            axis.tick_params(axis="x", labelbottom=False)
            axis.xaxis.label.set_visible(False)
            axis.xaxis.offsetText.set_visible(False)
            self.exporting_time_axis = False
            self.draw_idle()


def binary_indicator(series, metric):
    """Recognize discrete states; keep probabilities and continuous metrics numeric."""
    name = str(metric).lower()
    if name.startswith(("accelerometer_", "gyroscope_")) or name == "green":
        return False
    if any(word in name for word in ("proba", "probability", "confidence", "power", "velocity", "range_of_motion")):
        return False
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    observed = values[np.isfinite(values)]
    if not len(observed) or not np.isin(observed, [0., 1.]).all():
        return False
    labelled = name.startswith(("pred_", "is_", "has_")) or any(word in name for word in ("flag", "indicator", "detected"))
    return pd.api.types.is_bool_dtype(series.dtype) or labelled or len(np.unique(observed)) == 2


def time_coordinates(values):
    if isinstance(values, (pd.DatetimeIndex, pd.Series)) and pd.api.types.is_datetime64_any_dtype(values.dtype):
        return np.asarray(dates.date2num(pd.DatetimeIndex(values).to_pydatetime()), dtype=float)
    return np.asarray(values, dtype=float)


def plot_states(ax, xs, ys, color, *, label=None, ends=None):
    """Presence at observed timestamps; blank space does not infer absence."""
    xs, ys = time_coordinates(xs), np.asarray(ys, dtype=float)
    finite_time = np.isfinite(xs)
    present = finite_time & (ys == 1.)
    ax._paradigma_binary = True
    if ends is None:
        ax.scatter(xs[present], ys[present], color=color, marker="|", s=64,
                   linewidths=.9, zorder=3, label=label, rasterized=len(xs) > 2000)
    else:
        ends = time_coordinates(ends)
        valid = present & np.isfinite(ends) & (ends > xs)
        ax.broken_barh(list(zip(xs[valid], ends[valid] - xs[valid])), (.88, .24),
                       facecolors=color, edgecolors="none", zorder=3, label=label,
                       rasterized=len(xs) > 2000)
        points = present & ~valid
        if points.any():
            ax.scatter(xs[points], ys[points], color=color, marker="|", s=64,
                       linewidths=.9, zorder=3, rasterized=len(xs) > 2000)
    # Keep the recording extent, including zero/missing-state timestamps, even
    # when this selection has no detections. Do not invent continuous intervals.
    if finite_time.any():
        ax.update_datalim([(xs[finite_time].min(), 1.), (xs[finite_time].max(), 1.)])
        ax.autoscale_view(scaley=False)
    ax.set_yticks([])
    ax.set_ylim(.65, 1.35)
    ax.set_ylabel("")
    ax.grid(False, axis="y")
    ax.margins(x=.025)


def plot_signal(ax, xs, ys, color, *, label=None, points_only=False, sparse=False):
    return ax.plot(xs, ys, color=color, label=label, linewidth=0 if points_only else 1.35,
                   alpha=.9, marker="o" if points_only or sparse else None, markersize=3.5,
                   markeredgewidth=0, solid_capstyle="round", solid_joinstyle="round", zorder=3)
