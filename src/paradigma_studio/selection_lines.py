"""One Results time-selector stroke, clipped separately to plots and their gaps."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from matplotlib.artist import Artist, allow_rasterization
from matplotlib.lines import Line2D
from matplotlib.path import Path
from matplotlib.transforms import IdentityTransform

if TYPE_CHECKING:
    from matplotlib.backend_bases import RendererBase
    from matplotlib.figure import Figure
    from matplotlib.transforms import Bbox


def _stack_bounds(figure: Figure) -> list[Bbox]:
    return sorted(
        [ax.bbox for ax in figure.axes if hasattr(ax, "_paradigma_dataset") and ax.get_visible()],
        key=lambda bounds: bounds.y0,
    )


def _shared_stroke(template: Line2D, stroke: Line2D, bounds: list[Bbox]) -> None:
    """Start every clipped section at the same pixel so dash phases cannot drift."""
    x = template.get_transform().transform((template.get_xdata()[0], 0))[0]
    stroke.update_from(template)
    stroke.set_transform(IdentityTransform())
    stroke.set_data([x, x], [bounds[0].y0, bounds[-1].y1])


class LinkedTimeSelectionLine(Line2D):
    """Retain an Axes-owned selector, drawing its portion of the shared stroke."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._stroke = Line2D([], [])

    @allow_rasterization
    def draw(self, renderer: RendererBase) -> None:
        if not self.get_visible():
            return
        bounds = _stack_bounds(self.get_figure(root=True))
        if not bounds:
            return
        _shared_stroke(self, self._stroke, bounds)
        self._stroke.draw(renderer)
        self.stale = False


class TimeSelectionBridges(Artist):
    """Draw only the gutters, leaving Axes markers above the line in exports."""

    def __init__(self, figure: Figure, template: Line2D) -> None:
        super().__init__()
        self._template = template
        self._stroke = Line2D([], [])
        self.set_gid("selected-result-time-bridges")
        self.set_zorder(template.get_zorder())
        self.set_animated(template.get_animated())
        self.set_in_layout(False)
        figure.add_artist(self)

    @allow_rasterization
    def draw(self, renderer: RendererBase) -> None:
        if not self.get_visible() or not self._template.get_visible():
            return
        figure = self.get_figure(root=True)
        bounds = _stack_bounds(figure)
        if len(bounds) < 2:
            return
        left, right = max(box.x0 for box in bounds), min(box.x1 for box in bounds)
        gaps = [
            [(left, lower.y1), (right, lower.y1), (right, upper.y0), (left, upper.y0)]
            for lower, upper in zip(bounds, bounds[1:], strict=False)
            if upper.y0 > lower.y1
        ]
        if not gaps:
            return
        _shared_stroke(self._template, self._stroke, bounds)
        self._stroke.set_clip_box(figure.bbox)
        self._stroke.set_clip_path(
            Path.make_compound_path_from_polys(np.asarray(gaps)), IdentityTransform()
        )
        self._stroke.draw(renderer)
        self.stale = False
