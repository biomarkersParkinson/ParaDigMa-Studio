"""Scientific plot presentation: original values, exact state timestamps, scrolling."""

from contextlib import contextmanager

import numpy as np
from matplotlib import dates
from matplotlib.artist import allow_rasterization
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.collections import PolyCollection
from matplotlib.lines import Line2D
from matplotlib.markers import MarkerStyle
from matplotlib.transforms import Affine2D


def time_selection_triangle():
    """Place the triangle tip, rather than its centre, on the time-axis baseline."""
    return MarkerStyle("v", transform=Affine2D().translate(0, 0.5))


def time_selection_line(ax, x, *, animated=False):
    """Shared time-selection style for result graphs and original sensor context."""
    line = Line2D(
        [x, x],
        [0, 1],
        transform=ax.get_xaxis_transform(),
        color="#465B73",
        linewidth=1.1,
        linestyle=(0, (3, 3)),
        alpha=0.75,
        zorder=7,
    )
    line.set_gid("selected-result-time")
    line.set_animated(animated)
    ax.add_artist(line)
    return line


class ViewportPolyCollection(PolyCollection):
    """Render visible rectangles while retaining every original interval and value."""

    def __init__(self, vertices, *, merge_presence=False, **kwargs):
        super().__init__(vertices, **kwargs)
        vertices = np.asarray(vertices)
        self._render_paths = self._paths
        if merge_presence and len(vertices):
            # Uniform opaque presence rectangles can share one drawing path
            # across touching intervals. Retain the individual original paths
            # for inspection; union only the exact area that is already filled.
            intervals = np.column_stack(
                (vertices[:, :, 0].min(axis=1), vertices[:, :, 0].max(axis=1))
            )
            intervals = intervals[np.argsort(intervals[:, 0], kind="stable")]
            ends = np.maximum.accumulate(intervals[:, 1])
            groups = np.r_[0, np.flatnonzero(intervals[1:, 0] > ends[:-1]) + 1]
            if len(groups) < len(vertices):
                left, right = intervals[groups, 0], np.maximum.reduceat(intervals[:, 1], groups)
                merged = np.empty((len(groups), 4, 2))
                merged[:, :, 0] = np.column_stack((left, left, right, right))
                merged[:, :, 1] = vertices[0, :, 1]
                vertices = merged
                self._render_paths = PolyCollection(merged).get_paths()
        self._starts = vertices[:, :, 0].min(axis=1) if len(vertices) else np.array([])
        self._ends = vertices[:, :, 0].max(axis=1) if len(vertices) else np.array([])
        self._bottoms = vertices[:, :, 1].min(axis=1) if len(vertices) else np.array([])
        self._tops = vertices[:, :, 1].max(axis=1) if len(vertices) else np.array([])
        self._ordered_intervals = (np.diff(self._starts) >= 0).all() and (
            np.diff(self._ends) >= 0
        ).all()

    def _pixel_envelope(self, visible):
        if self.axes is None or self.axes.get_xscale() != "linear":
            return None
        canvas = self.get_figure(root=True).canvas
        if canvas.is_saving() or not (
            getattr(canvas, "_result_dense_display", False)
            or getattr(canvas, "time_scrolling", False)
            and canvas.panning
        ):
            return None
        left = self._starts if visible is None else self._starts[visible]
        right = self._ends if visible is None else self._ends[visible]
        count = len(left)
        columns = max(1, int(np.ceil(self.axes.bbox.width)))
        if count <= max(512, columns * 2):
            return None
        low, high = sorted(self.axes.get_xlim())
        step = (high - low) / columns
        short = right - left <= step
        if np.count_nonzero(short) < count / 2:
            return None
        # Use the same envelope at rest and during Results navigation: individual
        # subpixel rectangles can otherwise vanish when the gesture finishes.
        # Only intervals narrower than a physical pixel enter the envelope.
        # Longer intervals retain their original bounds, including real gaps.
        first = np.clip(np.floor((left[short] - low) / step).astype(int), 0, columns - 1)
        last = np.clip(np.ceil((right[short] - low) / step).astype(int) - 1, 0, columns - 1)
        indices = np.r_[first, last]
        bottoms = self._bottoms if visible is None else self._bottoms[visible]
        tops = self._tops if visible is None else self._tops[visible]
        lower, upper = np.full(columns, np.inf), np.full(columns, -np.inf)
        np.minimum.at(lower, indices, np.tile(bottoms[short], 2))
        np.maximum.at(upper, indices, np.tile(tops[short], 2))
        occupied = np.flatnonzero(np.isfinite(lower))
        starts = low + occupied * step
        left = np.r_[starts, left[~short]]
        right = np.r_[starts + step, right[~short]]
        lower = np.r_[lower[occupied], bottoms[~short]]
        upper = np.r_[upper[occupied], tops[~short]]
        preview = np.empty((len(left), 4, 2))
        preview[:, :, 0] = np.column_stack((left, left, right, right))
        preview[:, :, 1] = np.column_stack((lower, upper, upper, lower))
        return PolyCollection(preview).get_paths()

    def _visible_intervals(self, low, high):
        if self._ordered_intervals:
            return slice(
                np.searchsorted(self._ends, low, side="left"),
                np.searchsorted(self._starts, high, side="right"),
            )
        return (self._ends >= low) & (self._starts <= high)

    @allow_rasterization
    def draw(self, renderer):
        paths = self._paths
        draw_paths = self._render_paths
        visible = None
        if self.axes is not None and len(draw_paths) >= 512:
            low, high = sorted(self.axes.get_xlim())
            visible = self._visible_intervals(low, high)
            if isinstance(visible, slice):
                draw_paths = draw_paths[visible]
            elif not visible.all():
                draw_paths = [draw_paths[index] for index in np.flatnonzero(visible)]
        envelope = self._pixel_envelope(visible)
        self._paths = draw_paths if envelope is None else envelope
        try:
            return super().draw(renderer)
        finally:
            self._paths = paths


GRAPH_COLORS = (
    "#2864A5",
    "#168B82",
    "#C78235",
    "#7D64AB",
    "#C05F74",
    "#527E94",
    "#8C843C",
    "#A65D40",
    "#6474B1",
    "#498B64",
)


class SelectionOverlay:
    """Reuse the static plot image when only the linked row marker changes."""

    def __init__(self, canvas, artists):
        self.canvas, self.artists = canvas, artists
        self.background = None
        canvas.mpl_connect("draw_event", self.drawn)

    def invalidate(self):
        self.background = None

    @contextmanager
    def edit(self):
        # Adding/removing an animated marker dirties Axes even though its
        # static content is unchanged. Preserve pre-existing real changes.
        figure = self.canvas.figure
        dirty = figure.stale
        axes_dirty = [(ax, ax.stale) for ax in figure.axes]
        try:
            yield
        finally:
            for ax, stale in axes_dirty:
                ax.stale = stale
            figure.stale = dirty

    def drawn(self, event):
        if event.canvas is not self.canvas or self.canvas.is_saving():
            return
        bounds = self.canvas.figure.bbox
        if self.canvas.supports_blit and bounds.width * bounds.height * 4 <= 32 * 1024**2:
            self.background = self.canvas.copy_from_bbox(bounds)
        else:
            self.background = None
        # Animated artists are excluded from the base draw. They still need
        # painting when the image exceeds the background memory budget.
        self.paint(restore=False)

    def paint(self, *, restore=True):
        if restore and (
            self.background is None or self.canvas.figure.stale or not self.canvas.isVisible()
        ):
            self.canvas.draw_idle()
            return
        if restore:
            self.canvas.restore_region(self.background)
        for artist in self.artists():
            self.canvas.figure.draw_artist(artist)
        if restore:
            self.canvas.blit(self.canvas.figure.bbox)
        # A normal draw already schedules Qt painting. Repainting inside its
        # draw_event can recurse when Qt initiated that draw from paintEvent.


class ScrollableFigureCanvas(FigureCanvasQTAgg):
    """Qt canvas wheel events scroll the enclosing Results workspace."""

    scroll_area = None
    outer_scroll_area = None
    pinned_time_axis = False
    exporting_time_axis = False
    _wheel_remainder = 0.0
    defer_when_hidden = False
    _deferred_draw = False
    panning = False

    def draw(self):
        if not self.panning or self.is_saving():
            return super().draw()
        # A drag changes limits, not the page layout. Keep settled axes in
        # place and paint only the portion that Qt can display. Release paints
        # the complete figure with its original layout engine again.
        figure = self.figure
        engine = figure.get_layout_engine()
        region = self.visibleRegion().boundingRect()
        ratio = self.device_pixel_ratio
        bottom = (self.height() - region.y() - region.height()) * ratio
        top = (self.height() - region.y()) * ratio
        padding = figure.dpi * 0.35  # Include headings above a barely offscreen plot.
        hidden = [
            ax
            for ax in figure.axes
            if ax.get_visible() and (ax.bbox.y1 + padding < bottom or ax.bbox.y0 - padding > top)
        ]
        for ax in hidden:
            ax.set_visible(False)
        figure.set_layout_engine("none")
        try:
            return super().draw()
        finally:
            clean = not figure.stale
            for ax in hidden:
                ax.set_visible(True)
            figure.set_layout_engine(engine)
            if clean:
                figure.stale = False

    def draw_idle(self):
        if self.defer_when_hidden and not self.isVisible():
            self._deferred_draw = True
            return
        super().draw_idle()

    def showEvent(self, event):
        super().showEvent(event)
        if self._deferred_draw:
            self._deferred_draw = False
            super().draw_idle()

    def wheelEvent(self, event):
        if self.scroll_area is None:
            return super().wheelEvent(event)
        bar = self.scroll_area.verticalScrollBar()
        delta = event.pixelDelta().y() or event.angleDelta().y() / 120 * bar.singleStep() * 3
        if delta:
            if self.outer_scroll_area is not None and (
                delta > 0
                and bar.value() == bar.minimum()
                or delta < 0
                and bar.value() == bar.maximum()
            ):
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
        original_size = self.figure.get_size_inches().copy()
        self.exporting_time_axis = True
        axis.tick_params(axis="x", which="both", labelbottom=True)
        axis.xaxis.label.set_visible(True)
        axis.xaxis.offsetText.set_visible(True)
        try:
            if getattr(axis, "_paradigma_day_groups", False):
                # Compact indicator tracks have no live axis below them. Reserve
                # its two rows in exports without resizing the Qt canvas.
                self.figure.set_size_inches(original_size + [0, 0.65], forward=False)
            return super().print_figure(*args, **kwargs)
        finally:
            self.figure.set_size_inches(original_size, forward=False)
            axis.tick_params(axis="x", which="both", labelbottom=False)
            axis.xaxis.label.set_visible(False)
            axis.xaxis.offsetText.set_visible(False)
            self.exporting_time_axis = False
            self.draw_idle()


def binary_indicator(series, metric):
    """Recognize discrete states; keep probabilities and continuous metrics numeric."""
    import pandas as pd

    name = str(metric).lower()
    if name.startswith(("accelerometer_", "gyroscope_")) or name == "green":
        return False
    if any(
        word in name
        for word in ("proba", "probability", "confidence", "power", "velocity", "range_of_motion")
    ):
        return False
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    observed = values[np.isfinite(values)]
    if not len(observed) or not np.isin(observed, [0.0, 1.0]).all():
        return False
    labelled = (
        name == "available"
        or name.startswith(("pred_", "is_", "has_"))
        or any(word in name for word in ("flag", "indicator", "detected"))
    )
    return pd.api.types.is_bool_dtype(series.dtype) or labelled or len(np.unique(observed)) == 2


def time_coordinates(values):
    import pandas as pd

    if isinstance(values, (pd.DatetimeIndex, pd.Series)) and pd.api.types.is_datetime64_any_dtype(
        values.dtype
    ):
        # NumPy datetime coordinates avoid a Python object for every sample;
        # timezone-aware arrays convert to UTC while preserving nanoseconds.
        return np.asarray(
            dates.date2num(pd.DatetimeIndex(values).to_numpy(dtype="datetime64[ns]")), dtype=float
        )
    return np.asarray(values, dtype=float)


def plot_states(ax, xs, ys, color, *, label=None, ends=None):
    """Presence at observed timestamps; blank space does not infer absence."""
    xs, ys = time_coordinates(xs), np.asarray(ys, dtype=float)
    finite_time = np.isfinite(xs)
    present = finite_time & (ys == 1.0)
    ax._paradigma_binary = True
    if ends is None:
        ax.scatter(
            xs[present],
            ys[present],
            color=color,
            marker="|",
            s=64,
            linewidths=0.9,
            zorder=3,
            label=label,
            rasterized=len(xs) > 2000,
        )
    else:
        ends = time_coordinates(ends)
        valid = present & np.isfinite(ends) & (ends > xs)
        vertices = np.empty((valid.sum(), 4, 2))
        vertices[:, :, 0] = np.column_stack((xs[valid], xs[valid], ends[valid], ends[valid]))
        vertices[:, :, 1] = [0.76, 1.24, 1.24, 0.76]
        ax.add_collection(
            ViewportPolyCollection(
                vertices,
                facecolors=color,
                edgecolors="none",
                zorder=3,
                label=label,
                rasterized=len(xs) > 2000,
                merge_presence=True,
            ),
            autolim=False,
        )
        if valid.any():
            ax.update_datalim([(xs[valid].min(), 0.76), (ends[valid].max(), 1.24)])
        points = present & ~valid
        if points.any():
            ax.scatter(
                xs[points],
                ys[points],
                color=color,
                marker="|",
                s=64,
                linewidths=0.9,
                zorder=3,
                rasterized=len(xs) > 2000,
            )
    # Keep the recording extent, including zero/missing-state timestamps, even
    # when this selection has no detections. Do not invent continuous intervals.
    if finite_time.any():
        ax.update_datalim([(xs[finite_time].min(), 1.0), (xs[finite_time].max(), 1.0)])
        ax.autoscale_view(scaley=False)
    ax.set_yticks([])
    ax.set_ylim(0.65, 1.35)
    ax.set_ylabel("")
    ax.spines["left"].set_visible(False)
    ax.grid(False, axis="y")
    ax.margins(x=0.025)


def plot_signal(ax, xs, ys, color, *, label=None, points_only=False, sparse=False):
    return ax.plot(
        xs,
        ys,
        color=color,
        label=label,
        linewidth=0 if points_only else 1.35,
        alpha=0.9,
        marker="o" if points_only or sparse else None,
        markersize=3.5,
        markeredgewidth=0,
        solid_capstyle="round",
        solid_joinstyle="round",
        zorder=3,
    )


def plot_bars(ax, starts, ends, values, color):
    """One bar per finite output: missing estimates leave real gaps."""
    from matplotlib.collections import LineCollection

    starts, ends = time_coordinates(starts), time_coordinates(ends)
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(starts) & np.isfinite(ends) & np.isfinite(values) & (ends > starts)
    left, right, heights = starts[valid], ends[valid], values[valid]
    inset = (right - left) * 0.08
    left, right = left + inset, right - inset
    vertices = np.zeros((len(left), 4, 2))
    vertices[:, :, 0] = np.column_stack((left, left, right, right))
    vertices[:, :, 1] = np.column_stack(
        (np.zeros(len(left)), heights, heights, np.zeros(len(left)))
    )
    collection = ViewportPolyCollection(
        vertices,
        facecolors=color,
        edgecolors="none",
        alpha=0.85,
        rasterized=len(left) > 2000,
        zorder=3,
    )
    # Bounds are calculated from the arrays below. Matplotlib's collection
    # scan otherwise visits every rectangle again before the first draw.
    ax.add_collection(collection, autolim=False)
    zero = heights == 0
    if zero.any():
        segments = np.stack(
            (
                np.column_stack((left[zero], heights[zero])),
                np.column_stack((right[zero], heights[zero])),
            ),
            axis=1,
        )
        ax.add_collection(
            LineCollection(segments, colors=color, linewidths=1, zorder=3), autolim=False
        )
    isolated = np.isfinite(starts) & np.isfinite(ends) & np.isfinite(values) & (ends == starts)
    if isolated.any():
        # No known cadence: retain the value at its timestamp without inventing
        # a scientific duration or joining it to another recording.
        ax.scatter(starts[isolated], values[isolated], color=color, marker="s", s=18, zorder=3)
    if valid.any():
        ax.update_datalim(np.column_stack((starts[valid], values[valid])))
        ax.update_datalim(np.column_stack((ends[valid], np.zeros(valid.sum()))))
        ax.autoscale_view()
    timed = np.isfinite(starts) & np.isfinite(ends)
    if timed.any():
        ax.update_datalim([(starts[timed].min(), 0.0), (ends[timed].max(), 0.0)])
        ax.autoscale_view()
    ax._paradigma_bars = True
    ax._paradigma_bar_data = starts, ends, values
    inset = (ends - starts) * 0.08
    finite = np.isfinite(starts) & np.isfinite(ends) & np.isfinite(values)
    ax._paradigma_bar_extents = (
        starts + inset,
        ends - inset,
        finite & (ends > starts),
        finite & (ends == starts),
    )
    ax._paradigma_y_cache = None
    ax.callbacks.connect("xlim_changed", autoscale_bars)
    autoscale_bars(ax)
    return collection


def autoscale_bars(ax):
    """Fit automatic Y limits to every bar intersecting the visible time range."""
    if not getattr(ax, "_paradigma_bars", False) or not ax.get_autoscaley_on():
        return
    starts, ends, values = ax._paradigma_bar_data
    low, high = sorted(ax.get_xlim())
    cached = ax._paradigma_y_cache
    if cached is not None and cached[0] == (low, high):
        limits = cached[1]
    else:
        left, right, intervals, points = ax._paradigma_bar_extents
        visible = (intervals & (right > low) & (left < high)) | (
            points & (starts >= low) & (starts <= high)
        )
        present = values[visible]
        lower = min(0.0, float(present.min())) if len(present) else 0.0
        upper = max(0.0, float(present.max())) if len(present) else 0.0
        margin = (upper - lower) * 0.08
        if margin == 0:
            upper, margin = 1.0, 0.0
        limits = lower - margin if lower < 0 else lower, upper + margin if upper > 0 else upper
        ax._paradigma_y_cache = (low, high), limits
    if ax.get_ylim() != limits:
        ax.set_ylim(*limits, auto=True, emit=False)
