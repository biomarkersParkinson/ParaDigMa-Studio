"""Frozen handles for graphics constructed only on first use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from PySide6.QtWidgets import QLabel, QLayout, QScrollArea, QWidget

    from ..plot_controls import GraphToolbar
    from ..plotting import ScrollableFigureCanvas, SelectionOverlay
    from ..result_canvas import ResultFigureCanvas
    from ..result_navigation import ResultsToolbar, ResultTimeScroll
    from ..time_axis import PinnedTimeAxis
    from ..widgets import FigureActionBar


@dataclass(frozen=True)
class ChannelCanvasView:
    figure: Figure
    canvas: ScrollableFigureCanvas
    toolbar: GraphToolbar


@dataclass(frozen=True)
class ResultCanvasView:
    canvas: ResultFigureCanvas
    figure: Figure
    figure_actions: FigureActionBar
    figure_actions_layout: QLayout
    graph_scroll: QScrollArea
    graphs_workspace: QWidget
    plot_toolbar: ResultsToolbar
    recording_time_label: QLabel
    result_overlay: SelectionOverlay
    result_time_scroll: ResultTimeScroll
    time_axis: PinnedTimeAxis
