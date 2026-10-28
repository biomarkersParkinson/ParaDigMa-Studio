"""Frozen handles for graphics constructed only on first use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from PySide6.QtWidgets import QLabel, QLayout, QScrollArea, QWidget

    from ..plotting import ScrollableFigureCanvas, SelectionOverlay
    from ..raw_navigation import RawToolbar
    from ..result_canvas import ResultFigureCanvas
    from ..result_navigation import ResultsToolbar
    from ..time_axis import PinnedTimeAxis
    from ..time_navigation import TimeScroll
    from ..widgets import FigureActionBar


@dataclass(frozen=True)
class ChannelCanvasView:
    figure: Figure
    canvas: ScrollableFigureCanvas
    toolbar: RawToolbar


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
    result_time_scroll: TimeScroll
    time_axis: PinnedTimeAxis
