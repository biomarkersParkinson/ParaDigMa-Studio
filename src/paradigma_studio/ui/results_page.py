"""Results page construction and frozen views, with deferred result canvases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLayout,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..result_workspace_controller import ResultWorkspaceView, set_results_tab
from ..results_view import MODULE_NAMES
from ..theme import light_palette, tooltip_text
from ..widgets import FigureActionBar, ModuleTabBar, SeriesTree, button, combo, field, label, table
from ..workspace_state import GraphState, ResultState
from .deferred import DeferredWidget, deferred_attribute
from .graph_views import ChannelCanvasView, ResultCanvasView
from .result_graphs import ResultGraphView
from .workspace_callbacks import WorkspaceCallbacks

if TYPE_CHECKING:
    from .data_page import ChannelGraphBuilder


@dataclass(frozen=True)
class ResultsPageHost:
    parent: QMainWindow
    layout: QVBoxLayout
    channel_graph: ChannelGraphBuilder
    sensor_graphics: Callable[[], ChannelCanvasView]


class ResultsPage:
    """Own Results widgets and canvases without access to WorkspaceLayout."""

    figure = deferred_attribute("graph_view")
    canvas = deferred_attribute("graph_view")
    plot_toolbar = deferred_attribute("graph_view")
    result_overlay = deferred_attribute("graph_view")
    figure_actions = deferred_attribute("graph_view")
    figure_actions_layout = deferred_attribute("graph_view")
    graphs_workspace = deferred_attribute("graph_view")
    graph_scroll = deferred_attribute("graph_view")
    time_axis = deferred_attribute("graph_view")
    result_time_scroll = deferred_attribute("graph_view")
    recording_time_label = deferred_attribute("graph_view")

    combo = staticmethod(combo)

    def __init__(
        self,
        host: ResultsPageHost,
        callbacks: WorkspaceCallbacks,
        graphs: GraphState,
        results: ResultState,
    ) -> None:
        self.parent, self.callbacks = host.parent, callbacks
        self.graphs, self.results = graphs, results
        self.channel_graph, self.sensor_graphics = host.channel_graph, host.sensor_graphics
        self._result_canvas_view: ResultCanvasView | None = None
        self._build_results(host.layout)

    def _build_results(self, layout: QVBoxLayout) -> None:
        self.result_tabs = QTabWidget()
        self.result_tabs.tabBar().setExpanding(False)
        self.result_tabs.setMinimumHeight(200)
        layout.addWidget(self.result_tabs, 1)
        self._result_view_layouts: list[QVBoxLayout] = []
        self._result_view_scrolls: list[QScrollArea] = []

        self._build_result_header()
        self._build_result_table_controls()
        self._build_result_overview_view()
        self._build_result_graph_view()
        self._build_result_tables_view()
        self._build_sensor_context_view()
        self._build_context_action()

    def _result_view(self, title, pinned=False):
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(12)
        body_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        scroll.setWidget(body)
        if pinned:
            self.graph_view = DeferredWidget(self._initialize_result_graph)
            self.graph_view_layout = QVBoxLayout(self.graph_view)
            self.graph_view_layout.setContentsMargins(0, 0, 0, 0)
            self.graph_view_layout.setSpacing(0)
            self.graph_view_layout.addWidget(scroll, 1)
            self.result_tabs.addTab(self.graph_view, title)
        else:
            self.result_tabs.addTab(scroll, title)
        self._result_view_layouts.append(body_layout)
        self._result_view_scrolls.append(scroll)
        return scroll, body_layout

    def _build_result_header(self):
        self.results_header = QWidget()
        header = QHBoxLayout(self.results_header)
        header.setContentsMargins(0, 0, 0, 0)
        self.results_source = label("No analysis results", "muted")
        header.addWidget(self.results_source, 1)
        self.sensor_close = button("Close", self.callbacks.hide_sensor_context)
        self.sensor_close.setAccessibleName("Close sensor context")
        header.addWidget(self.sensor_close)
        actions = QWidget()
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(12, 0, 0, 0)
        self.save_results_button = button("Save results", self.callbacks.save_results)
        self.save_results_button.setAccessibleName("Save complete run results locally")
        self.save_results_button.setToolTip("Save all results locally for reopening from Runs.")
        self.save_results_button.setShortcut("Ctrl+S")
        self.save_results_button.setEnabled(False)
        action_layout.addWidget(self.save_results_button)
        self.export_button = button("Export…", self.callbacks.choose_export)
        self.export_button.setAccessibleName("Export results")
        self.export_button.setEnabled(False)
        action_layout.addWidget(self.export_button)
        self.result_tabs.setCornerWidget(actions, Qt.Corner.TopRightCorner)

    def _build_result_table_controls(self):
        self.detail_controls = QWidget()
        controls_layout = QVBoxLayout(self.detail_controls)
        controls_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        settings = QHBoxLayout()
        self.table_actions_layout = settings
        self.dataset = self.combo()
        self.dataset.setParent(self.detail_controls)
        self.dataset.hide()  # Linked graph/table state; the visible selector is scoped by output type.
        self.table_dataset = self.combo()
        self.table_dataset.setMinimumWidth(180)
        self.dataset_field = field("Output table", self.table_dataset)
        settings.addWidget(self.dataset_field, 2)
        self.timing_toggle = QCheckBox("Timing details")
        self.timing_toggle.setToolTip(
            tooltip_text(
                "Add display-only dates and gait timing estimates; original output columns stay unchanged."
            )
        )
        settings.addWidget(self.timing_toggle)
        self.y_column = self.combo()
        # Kept as internal metric state for linked table/graph inspection.
        # Plot series is the user-facing metric selector.
        self.y_column.setParent(self.detail_controls)
        self.y_column.hide()
        settings.addStretch()
        controls_layout.addLayout(settings)
        self.selection_note = label("No detailed output", "muted")
        controls_layout.addWidget(self.selection_note)
        self.table_module_tabs = ModuleTabBar()
        self.table_module_tabs.setExpanding(False)
        for title in MODULE_NAMES.values():
            self.table_module_tabs.addTab(title)
        self.table_module_tabs.setCurrentIndex(0)
        controls_layout.insertWidget(0, self.table_module_tabs)

    def _build_result_overview_view(self):
        self.overview_scroll, overview_body = self._result_view("Overview")
        self.overview_content = QWidget()
        self.overview_layout = QVBoxLayout(self.overview_content)
        self.overview_layout.setContentsMargins(0, 0, 0, 0)
        self.overview_layout.setSpacing(16)
        overview_body.addWidget(self.overview_content, 1)

    def _build_result_graph_view(self):
        self._result_view("Graphs", pinned=True)
        self.graph_view_controls = QWidget(self.graph_view)
        view_row = QHBoxLayout(self.graph_view_controls)
        view_row.setContentsMargins(0, 0, 0, 0)
        view_row.addWidget(label("View", "muted"))
        self.result_graph_view = self.combo(
            ["Detailed", "30-minute epochs", "Day", "24-hour profile"]
        )
        self.result_graph_view.setAccessibleName("Graph time view for all selected series")
        self.result_graph_view.setMinimumWidth(190)
        self.result_graph_view.setToolTip(
            tooltip_text(
                "Binary predictions show percentages; continuous outcomes show medians.\n"
                "Gait and filtered gait share the same observed-time denominator.\n"
                "Gait range of motion / peak velocity and tremor power require 90 seconds of presence per epoch.\n"
                "Day: calendar days in recording time; each metric requires 1% valid data (14 min 24 s).\n"
                "24-hour profile: mean of valid 30-minute summaries at each time of day, with equal weight per day.\n"
                "Coverage shows prepared input time. Missing outcomes stay blank.\n"
                "Epochs align to calendar half-hours; first/last epochs may be partial."
            )
        )
        view_row.addWidget(self.result_graph_view)
        self.result_series = SeriesTree(self.graph_view)
        self.result_series.setIndentation(6)
        self.result_series.setStyleSheet("QTreeWidget::item { padding: 5px 0px; }")
        self.result_series.setHeaderLabel("Plot series")
        self.result_series.setPalette(light_palette())
        self.result_series.setMinimumWidth(190)
        self.result_series.setMaximumWidth(285)
        self.result_series.setWordWrap(True)
        self.result_series.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.result_series.setAccessibleName("Results to plot simultaneously")
        self.graph_footer = QWidget(self.graph_view)
        self.graph_footer_layout = QHBoxLayout(self.graph_footer)
        self.graph_footer_layout.setContentsMargins(0, 0, 12, 0)

    def _initialize_result_graph(self):
        graph_body = self._result_view_layouts[1]
        self._build_result_canvas(graph_body)
        self._build_pinned_graph_workspace(graph_body)
        self.canvas.mpl_connect("button_press_event", self.callbacks.graph_clicked)
        if not self.callbacks.selected_result_series():
            self.callbacks.plot()

    def _build_result_canvas(self, graph_body):
        from matplotlib.figure import Figure

        from ..plotting import SelectionOverlay
        from ..result_canvas import ResultFigureCanvas
        from ..result_layout import ResultLayoutEngine
        from ..result_navigation import ResultsToolbar

        graphs = QWidget()
        # The plot scroll area handles tall figures without spilling over the ruler.
        graphs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        graph_layout = QHBoxLayout(graphs)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph = QWidget()
        plots = QVBoxLayout(graph)
        plots.setContentsMargins(0, 0, 0, 0)
        self.figure = Figure(layout=ResultLayoutEngine())
        self.canvas = ResultFigureCanvas(self.figure)
        self.canvas.defer_when_hidden = True
        self.result_overlay = SelectionOverlay(
            self.canvas, lambda: self.graphs._result_selection_artists
        )
        self.canvas.bind_viewport_overlay(self.result_overlay)
        self.canvas.pinned_time_axis = True
        self.plot_toolbar = ResultsToolbar(self.canvas, self.parent)
        self.figure_actions = FigureActionBar(self.plot_toolbar)
        # A newly shown graph already has its final width. Arrange the toolbar
        # at that width before adding controls, avoiding a stale wrapped height.
        self.figure_actions.resize(self.graph_view.width(), self.figure_actions.sizeHint().height())
        self.figure_actions.set_context(self.graph_view_controls)
        self.figure_actions_layout = self.figure_actions.primary
        graph_body.addWidget(self.figure_actions)
        graph_body.addWidget(self.plot_toolbar.settings)
        graph_scroll = QScrollArea()
        graph_scroll.setFrameShape(QFrame.Shape.NoFrame)
        graph_scroll.setWidgetResizable(True)
        graph_scroll.setWidget(self.canvas)
        self.graph_scroll = graph_scroll
        self.result_graph_view.wheel_scroll_target = graph_scroll
        for _, lower, upper in self.plot_toolbar.settings.bounds.values():
            lower.wheel_scroll_target = upper.wheel_scroll_target = graph_scroll
        self.canvas.scroll_area = graph_scroll
        self.canvas.outer_scroll_area = self._result_view_scrolls[1]
        plots.addWidget(graph_scroll, 1)
        graph_layout.addWidget(graph, 1)
        graphs.setMinimumHeight(310)
        self.graphs_workspace = graphs
        graph_body.addWidget(graphs, 1)

    def _build_pinned_graph_workspace(self, graph_body):
        from ..result_navigation import ResultTimeScroll
        from ..time_axis import PinnedTimeAxis

        self.time_axis = PinnedTimeAxis(self.canvas, lambda: self.plot_toolbar.settings.axes())
        # The selector spans the plot viewport and its pinned time ruler.
        # It must not end above a blank rectangle the height of the ruler.
        plot_view = QWidget()
        plot_view_layout = QVBoxLayout(plot_view)
        plot_view_layout.setContentsMargins(0, 0, 0, 0)
        plot_view_layout.setSpacing(0)
        scroll = self._result_view_scrolls[1]
        self.graph_view_layout.removeWidget(scroll)
        # Figure actions retain the full page width, including at 960 px.
        # Otherwise the selector can hide the toolbar's settings/save buttons.
        graph_body.removeWidget(self.figure_actions)
        graph_body.removeWidget(self.plot_toolbar.settings)
        self.graph_view_layout.addWidget(self.figure_actions)
        self.graph_view_layout.addWidget(self.plot_toolbar.settings)
        plot_view_layout.addWidget(scroll, 1)
        plot_view_layout.addWidget(self.time_axis)
        self.result_time_scroll = ResultTimeScroll(self.plot_toolbar)
        self.result_time_scroll.watch(self.canvas, self.graph_scroll.viewport(), self.time_axis)
        plot_view_layout.addWidget(self.result_time_scroll)
        self.recording_time_label = label("", "muted")
        self.recording_time_label.setWordWrap(True)
        self.recording_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recording_time_label.setAccessibleName("Recording time axis label")
        self.graph_footer_layout.insertWidget(0, self.recording_time_label, 1)
        self.time_axis.label_changed.connect(self.recording_time_label.setText)
        plot_view_layout.addWidget(self.graph_footer)
        workspace = QWidget()
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(12, 0, 0, 12)
        workspace_layout.setSpacing(10)
        workspace_layout.addWidget(self.result_series)
        workspace_layout.addWidget(plot_view, 1)
        self.graph_view_layout.addWidget(workspace, 1)
        graph_body.setContentsMargins(0, 0, 12, 0)
        self.graph_scroll.verticalScrollBar().valueChanged.connect(self.time_axis.synchronize)
        self.graph_scroll.verticalScrollBar().valueChanged.connect(self.canvas.redraw_viewport)
        self._result_view_scrolls[1].verticalScrollBar().valueChanged.connect(
            self.time_axis.synchronize
        )
        self._result_view_scrolls[1].verticalScrollBar().valueChanged.connect(
            self.canvas.redraw_viewport
        )

    def _build_result_tables_view(self):
        _, table_body = self._result_view("Tables")
        self.result_table = table()
        self.result_table.setMinimumHeight(200)
        self.aggregation_table = table()
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.result_table)
        self.table_stack.addWidget(self.aggregation_table)
        table_body.addWidget(self.table_stack, 1)

    def _build_sensor_context_view(self):
        self.sensor_tabs = QTabWidget()
        self.sensor_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        (
            sensor_graph,
            self.sensor_channels,
            self._sensor_graph,
        ) = self.channel_graph(
            self.callbacks.set_sensor_channels, "Original sensor channels to plot", "sensor"
        )
        # The shared channel-graph builder installs its layout before returning.
        cast("QLayout", sensor_graph.layout()).setContentsMargins(6, 6, 6, 6)
        self.sensor_tabs.addTab(sensor_graph, "Graphs")
        self.sensor_table = table()
        self.sensor_tabs.addTab(self.sensor_table, "Tables")
        _, sensor_body = self._result_view("Sensor context")
        sensor_body.setSpacing(6)
        sensor_body.addWidget(self.sensor_tabs, 1)
        self.sensor_tab_index = 3
        self.result_tabs.setTabVisible(self.sensor_tab_index, False)

    def _build_context_action(self):
        context = QHBoxLayout()
        context.setContentsMargins(0, 0, 0, 0)
        self.context_button = button(
            "Inspect sensor context", self.callbacks.inspect_sensor_context
        )
        self.context_button.setEnabled(False)
        self.context_button.setToolTip("Select a result row or click a graph point")
        context.addWidget(self.context_button)
        self.context_controls = QWidget()
        self.context_controls.setLayout(context)
        self.result_tabs.currentChanged.connect(self.callbacks.results_tab_changed)
        set_results_tab(
            self.results, self.workspace_view(), self.callbacks.update_context_action, 0
        )

    def result_graphics(self) -> ResultCanvasView:
        self.graph_view.initialize()
        if self._result_canvas_view is None:
            self._result_canvas_view = ResultCanvasView(
                canvas=self.canvas,
                figure=self.figure,
                figure_actions=self.figure_actions,
                figure_actions_layout=self.figure_actions_layout,
                graph_scroll=self.graph_scroll,
                graphs_workspace=self.graphs_workspace,
                plot_toolbar=self.plot_toolbar,
                recording_time_label=self.recording_time_label,
                result_overlay=self.result_overlay,
                result_time_scroll=self.result_time_scroll,
                time_axis=self.time_axis,
            )
        return self._result_canvas_view

    def workspace_view(self) -> ResultWorkspaceView:
        return ResultWorkspaceView(
            parent=self.parent,
            _result_view_layouts=self._result_view_layouts,
            _result_view_scrolls=self._result_view_scrolls,
            aggregation_table=self.aggregation_table,
            context_button=self.context_button,
            context_controls=self.context_controls,
            dataset=self.dataset,
            dataset_field=self.dataset_field,
            detail_controls=self.detail_controls,
            export_button=self.export_button,
            graph_footer_layout=self.graph_footer_layout,
            result_series=self.result_series,
            result_table=self.result_table,
            result_tabs=self.result_tabs,
            results_header=self.results_header,
            save_results_button=self.save_results_button,
            selection_note=self.selection_note,
            sensor_close=self.sensor_close,
            sensor_tab_index=self.sensor_tab_index,
            sensor_table=self.sensor_table,
            table_actions_layout=self.table_actions_layout,
            table_dataset=self.table_dataset,
            table_module_tabs=self.table_module_tabs,
            table_stack=self.table_stack,
            timing_toggle=self.timing_toggle,
            y_column=self.y_column,
            result_graphics=self.result_graphics,
            sensor_graphics=self.sensor_graphics,
        )

    def graph_view_model(self) -> ResultGraphView:
        return ResultGraphView(
            parent=self.parent,
            context_button=self.context_button,
            dataset=self.dataset,
            graph_view=self.graph_view,
            result_graph_view=self.result_graph_view,
            result_table=self.result_table,
            result_tabs=self.result_tabs,
            y_column=self.y_column,
            result_graphics=self.result_graphics,
        )
