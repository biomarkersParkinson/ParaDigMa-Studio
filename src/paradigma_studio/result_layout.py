"""Stable Results plot columns with automatic vertical spacing."""

from collections import OrderedDict

from matplotlib.layout_engine import ConstrainedLayoutEngine


class ResultLayoutEngine(ConstrainedLayoutEngine):
    """Reserve the same label column for every Results graph selection."""

    # Physical units keep the label column stable on resize and scale it with
    # display/export DPI. Include room for signed ticks and two-line Y labels.
    LEFT_MARGIN_INCHES = 1.1
    RIGHT_MARGIN_INCHES = 0.15
    MAX_LAYOUTS = 32

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._positions = OrderedDict()
        self._text_sizes = OrderedDict()

    def clear(self):
        self._positions.clear()
        self._text_sizes.clear()

    def invalidate(self):
        """Require a full solve after navigation without discarding font metrics."""
        self._positions.clear()

    def _layout_key(self, figure):
        # Only immutable geometry/style values enter the cache: never retain
        # Figures, Axes, locators or result arrays after a run is discarded.
        if figure.texts or any(
            ax.legend_ is not None or ax.texts or ax.get_aspect() != "auto" for ax in figure.axes
        ):
            return None
        axes = tuple(self._axes_key(ax) for ax in figure.axes)
        return tuple(figure.get_size_inches()), figure.dpi, tuple(sorted(self.get().items())), axes

    def _axes_key(self, ax):
        spec = ax.get_subplotspec()
        if spec is None:
            return None
        grid = spec.get_gridspec()
        labels = (ax.title, ax._left_title, ax._right_title, ax.xaxis.label, ax.yaxis.label)
        return (
            grid.get_geometry(),
            tuple(grid.get_height_ratios()),
            tuple(grid.get_width_ratios()),
            spec.num1,
            spec.num2,
            ax.get_visible(),
            ax.get_in_layout(),
            ax.get_xscale(),
            ax.get_yscale(),
            tuple(self._text_key(label) for label in (*labels, *ax.texts)),
            tuple(self._axis_key(axis) for axis in (ax.xaxis, ax.yaxis)),
            ax.xaxis.labelpad,
            ax.yaxis.labelpad,
            ax.titleOffsetTrans.get_matrix().tobytes(),
        )

    def _text_key(self, text):
        if not text.get_visible():
            return None
        patch = text.get_bbox_patch()
        box = None if patch is None else repr(vars(patch.get_boxstyle()))
        style = (
            text.get_text(),
            text.get_visible(),
            str(text.get_fontproperties()),
            text.get_rotation(),
            text.get_horizontalalignment(),
            text.get_verticalalignment(),
            # Matplotlib exposes a setter but no getter for line spacing.
            text._linespacing,
            box,
        )
        return self._text_size(text, style), style[1:]

    def _text_size(self, text, style):
        figure = text.get_figure(root=True)
        key = figure.dpi, style
        if key not in self._text_sizes:
            box = text.get_window_extent(figure.canvas.get_renderer())
            self._text_sizes[key] = round(box.width, 6), round(box.height, 6)
            while len(self._text_sizes) > 2048:
                self._text_sizes.popitem(last=False)
        else:
            self._text_sizes.move_to_end(key)
        return self._text_sizes[key]

    def _tick_sizes(self, labels, values):
        from copy import copy

        # A formatter's new labels are measured without changing the live ticks.
        template = labels[0]
        sizes = []
        for value in values:
            text = copy(template)
            text.stale_callback = None
            text.set_text(value)
            sizes.append(self._text_key(text))
        return tuple(sizes)

    def _axis_key(self, axis):
        if not axis.get_visible():
            return None
        groups = []
        for which in ("major", "minor"):
            ticks = getattr(axis, f"{which}Ticks")
            labels = [
                label
                for tick in ticks
                for label in (tick.label1, tick.label2)
                if label.get_visible()
            ]
            if not labels:
                groups.append(None)
                continue
            formatter = getattr(axis, f"get_{which}_formatter")()
            locations = getattr(axis, f"get_{which}_locator")()()
            groups.append(
                (
                    self._tick_sizes(labels, formatter.format_ticks(locations)),
                    tuple(sorted({str(label.get_fontproperties()) for label in labels})),
                    formatter.get_offset(),
                )
            )
        return tuple(groups), self._text_key(axis.offsetText)

    def execute(self, figure):
        key = None if figure.canvas.is_saving() else self._layout_key(figure)
        cached = self._positions.get(key) if key is not None else None
        if cached is not None:
            self._positions.move_to_end(key)
            for axes, position in zip(figure.axes, cached, strict=True):
                axes.set_position(position)
                axes.set_in_layout(True)
            return None
        layout = super().execute(figure)
        width = figure.get_figwidth()
        left = self.LEFT_MARGIN_INCHES / width
        right = 1 - self.RIGHT_MARGIN_INCHES / width
        for axes in figure.axes:
            if not axes.get_in_layout():
                continue
            position = axes.get_position()
            axes.set_position((left, position.y0, max(0.01, right - left), position.height))
            # set_position opts out of layout by default. Retain automatic
            # heading/row spacing on the next draw and in saved figures.
            axes.set_in_layout(True)
        if key is not None:
            # Tick creation and offset formatting may settle during the solve.
            key = self._layout_key(figure)
            self._positions[key] = tuple(ax.get_position().bounds for ax in figure.axes)
            self._positions.move_to_end(key)
            while len(self._positions) > self.MAX_LAYOUTS:
                self._positions.popitem(last=False)
        return layout
