"""Stable Results plot columns with automatic vertical spacing."""

from matplotlib.layout_engine import ConstrainedLayoutEngine


class ResultLayoutEngine(ConstrainedLayoutEngine):
    """Reserve the same label column for every Results graph selection."""

    # Physical units keep the label column stable on resize and scale it with
    # display/export DPI. Include room for signed ticks and two-line Y labels.
    LEFT_MARGIN_INCHES = 1.1
    RIGHT_MARGIN_INCHES = 0.15

    def execute(self, figure):
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
        return layout
