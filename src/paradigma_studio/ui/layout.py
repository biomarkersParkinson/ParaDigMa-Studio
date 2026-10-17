"""Page construction and shared layout helpers for the existing main-window controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLayout,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..analysis_controller import AnalysisView
from ..branding import APP_NAME
from ..data_controller import DataView
from ..export_controller import ExportView
from ..job_controller import JobView
from ..result_workspace_controller import ResultWorkspaceView, set_results_tab
from ..results_view import MODULE_NAMES
from ..shell_controller import ShellView
from ..theme import light_palette, tooltip_text
from ..widgets import (
    CheckLabelDelegate,
    FigureActionBar,
    HoverSidebar,
    ModuleTabBar,
    SeriesTree,
    button,
    card,
    combo,
    field,
    label,
    readout,
    table,
)
from ..workspace_state import GraphState, ResultState, ShellState
from .analysis_page import AnalysisFooterView, AnalysisPage
from .component_ports import component_attribute
from .data_page import DataPage, DataPageHost
from .deferred import DeferredWidget, deferred_attribute
from .graph_views import ChannelCanvasView, ResultCanvasView
from .result_graphs import ResultGraphView
from .workspace_callbacks import WorkspaceCallbacks as WorkspaceCallbacks


class WorkspaceLayout:
    """Own widget construction; expose frozen page views and explicit callbacks."""

    acc = component_attribute("_analysis_page")
    analysis_controls = component_attribute("_analysis_page")
    analysis_help = component_attribute("_analysis_page")
    analysis_help_panel = component_attribute("_analysis_page")
    analysis_help_sections = component_attribute("_analysis_page")
    analysis_input = component_attribute("_analysis_page")
    analysis_input_detail = component_attribute("_analysis_page")
    analysis_parameter_fields = component_attribute("_analysis_page")
    analysis_scroll = component_attribute("_analysis_page")
    clock_input = component_attribute("_analysis_page")
    drop_missing = component_attribute("_analysis_page")
    gaps = component_attribute("_analysis_page")
    gyro = component_attribute("_analysis_page")
    mapping = component_attribute("_analysis_page")
    max_gap = component_attribute("_analysis_page")
    min_segment = component_attribute("_analysis_page")
    module_buttons = component_attribute("_analysis_page")
    module_requirements = component_attribute("_analysis_page")
    orientation = component_attribute("_analysis_page")
    origin_reset = component_attribute("_analysis_page")
    prepared = component_attribute("_analysis_page")
    run_button = component_attribute("_analysis_page")
    section_reset_buttons = component_attribute("_analysis_page")
    segmentation_controls = component_attribute("_analysis_page")
    settings_panel = component_attribute("_analysis_page")
    side = component_attribute("_analysis_page")
    stop_button = component_attribute("_analysis_page")
    time = component_attribute("_analysis_page")

    _data_graph = component_attribute("_data_page")
    channel_table = component_attribute("_data_page")
    continue_button = component_attribute("_data_page")
    data_channels = component_attribute("_data_page")
    data_details = component_attribute("_data_page")
    data_tabs = component_attribute("_data_page")
    data_time_channel = component_attribute("_data_page")
    data_time_unit = component_attribute("_data_page")
    data_values = component_attribute("_data_page")
    file_label = component_attribute("_data_page")
    input_recording = component_attribute("_data_page")
    input_table = component_attribute("_data_page")
    open_action = component_attribute("_data_page")
    open_button = component_attribute("_data_page")
    time_table = component_attribute("_data_page")

    data_figure = deferred_attribute("_data_graph")
    data_canvas = deferred_attribute("_data_graph")
    data_toolbar = deferred_attribute("_data_graph")
    sensor_figure = deferred_attribute("_sensor_graph")
    sensor_canvas = deferred_attribute("_sensor_graph")
    sensor_toolbar = deferred_attribute("_sensor_graph")
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

    def __init__(
        self,
        parent: QMainWindow,
        callbacks: WorkspaceCallbacks,
        graphs: GraphState,
        shell: ShellState,
        results: ResultState,
        history_directory: Path,
        sections: tuple[str, ...],
        modules: dict[str, str],
    ) -> None:
        self.parent, self.callbacks = parent, callbacks
        self.graphs, self.shell, self.results = graphs, shell, results
        self.history_directory = history_directory
        self.sections, self.modules = sections, modules
        self._data_canvas_view: ChannelCanvasView | None = None
        self._sensor_canvas_view: ChannelCanvasView | None = None
        self._result_canvas_view: ResultCanvasView | None = None
        self._build_shell()
        self._build_data()
        self._build_analyze()
        self._build_results()
        self._build_runs()

    combo = staticmethod(combo)

    def _build_shell(self):
        root = QWidget()
        root.setObjectName("workspace")
        self.parent.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self._build_sidebar(root, shell)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(24, 20, 20, 12)
        center_layout.setSpacing(14)
        heading = QHBoxLayout()
        self.page_title = label("", "pageTitle")
        heading.addWidget(self.page_title, 1)
        center_layout.addLayout(heading)
        self.notice = label("", "notice")
        self.notice.hide()
        center_layout.addWidget(self.notice)
        self.pages = QStackedWidget()
        center_layout.addWidget(self.pages, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        center_layout.addWidget(self.progress)
        self.status = label("Open a sensor file.", "muted")
        self.status_row = QWidget()
        self.status_layout = QHBoxLayout(self.status_row)
        self.status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_layout.setSpacing(10)
        self.status_layout.addWidget(self.status, 1)
        center_layout.addWidget(self.status_row)
        shell.addWidget(center, 1)
        self.sidebar.raise_()

    def _build_sidebar(self, root: QWidget, shell: QHBoxLayout) -> None:
        self.sidebar = HoverSidebar(root)
        self.sidebar.setObjectName("sidebar")
        navigation = QVBoxLayout(self.sidebar.content)
        navigation.setContentsMargins(12, 20, 12, 18)
        navigation.setSpacing(8)
        brand_row = QHBoxLayout()
        self.brand_icon = label()
        self.brand_icon.setPixmap(self.parent.windowIcon().pixmap(28, 28))
        self.brand_icon.setFixedSize(28, 28)
        brand_row.addWidget(self.brand_icon)
        self.brand = label(APP_NAME, "brand")
        self.brand.setWordWrap(False)
        brand_row.addWidget(self.brand, 1)
        navigation.addLayout(brand_row)
        policy = self.brand.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.brand.setSizePolicy(policy)
        navigation.addSpacing(24)
        self.nav_buttons = []
        for index, section in enumerate(self.sections):
            item = button(
                f"{index + 1}    {section}",
                lambda checked=False, i=index: self.callbacks.navigate(i),
            )
            item.setCheckable(True)
            item.setAccessibleName(section)
            item.setShortcut(f"Alt+{index + 1}")
            navigation.addWidget(item)
            self.nav_buttons.append(item)
        navigation.addStretch()
        self.about_button = button("About", self.callbacks.show_acknowledgements)
        self.about_button.setObjectName("about")
        self.about_button.setShortcut("F1")
        navigation.addWidget(self.about_button)
        rail = QWidget()
        rail.setFixedWidth(self.sidebar.rail_width)
        shell.addWidget(rail)
        self.sidebar.fit_content()
        self.sidebar.expandedChanged.connect(self.sidebar_expanded)
        self.sidebar_expanded(False)

    def page(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.pages.addWidget(widget)
        return layout

    def _build_data(self):
        self._data_page = DataPage(
            DataPageHost(self.parent, self.page(), self.status_layout),
            self.callbacks,
            self.channel_graph,
        )

    def channel_graph(self, select_channels, accessible_name, prefix):
        """Shared raw-sensor workspace: a channel list beside a fitted graph."""
        preview = QWidget()
        preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        preview_layout = QHBoxLayout(preview)
        channels = QWidget()
        channels.setMinimumWidth(190)
        channels.setMaximumWidth(260)
        channel_layout = QVBoxLayout(channels)
        heading = label("Channels", "sectionTitle")
        heading.setWordWrap(False)
        channel_layout.addWidget(heading)
        selection = QHBoxLayout()
        channel_list = QListWidget()
        channel_list.setItemDelegate(CheckLabelDelegate(channel_list))
        selection.addWidget(
            button(
                "Select all",
                lambda: select_channels(
                    [
                        channel_list.item(i).data(Qt.ItemDataRole.UserRole)
                        for i in range(channel_list.count())
                    ]
                ),
            )
        )
        selection.addWidget(button("Clear", lambda: select_channels([])))
        channel_layout.addLayout(selection)
        channel_list.setPalette(light_palette())
        channel_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        channel_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        channel_list.setAccessibleName(accessible_name)
        channel_layout.addWidget(channel_list, 1)
        preview_layout.addWidget(channels)
        graph = DeferredWidget(lambda: self._build_channel_canvas(graph, prefix))
        preview_layout.addWidget(graph, 1)
        return preview, channel_list, graph

    def _build_channel_canvas(self, graph, prefix):
        from matplotlib.figure import Figure

        from ..plot_controls import add_graph_controls
        from ..plotting import ScrollableFigureCanvas

        graph_layout = QVBoxLayout(graph)
        figure = Figure(layout="constrained")
        canvas = ScrollableFigureCanvas(figure)
        canvas.defer_when_hidden = True
        # Use the available height instead of imposing the canvas's preferred
        # 480-pixel height on the enclosing page or clipping its time axis.
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        toolbar = add_graph_controls(graph_layout, canvas, self.parent)
        graph_layout.addWidget(canvas, 1)
        if prefix == "sensor":
            toolbar.home_callback = self.callbacks.reset_sensor_context
        setattr(self, f"{prefix}_figure", figure)
        setattr(self, f"{prefix}_canvas", canvas)
        setattr(self, f"{prefix}_toolbar", toolbar)

    def _build_analyze(self):
        self._analysis_page = AnalysisPage(
            self.page(),
            AnalysisFooterView(self.status_row, self.status_layout, self.continue_button),
            self.modules,
            self.callbacks,
        )

    def _build_results(self):
        layout = self.page()
        self.result_tabs = QTabWidget()
        self.result_tabs.tabBar().setExpanding(False)
        self.result_tabs.setMinimumHeight(200)
        layout.addWidget(self.result_tabs, 1)
        self._result_view_layouts, self._result_view_scrolls = [], []

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
        self.graph_scroll.verticalScrollBar().valueChanged.connect(
            lambda: self.canvas.draw_idle() if self.canvas.panning else None
        )
        self._result_view_scrolls[1].verticalScrollBar().valueChanged.connect(
            self.time_axis.synchronize
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
        sensor_graph.layout().setContentsMargins(6, 6, 6, 6)
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

    def _build_runs(self):
        layout = self.page()
        split = QSplitter(Qt.Orientation.Vertical)
        panel, content = card()
        self.run_table = table()
        self.run_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.run_table.setAccessibleName("Runs; use Ctrl or Shift to select multiple runs")
        content.addWidget(self.run_table, 1)
        actions = QHBoxLayout()
        self.open_run_button = button("Open results", self.callbacks.open_run)
        self.use_parameters_button = button(
            "Use these parameters", self.callbacks.use_run_parameters
        )
        actions.addWidget(self.open_run_button)
        actions.addWidget(self.use_parameters_button)
        self.delete_run_button = button("Delete Run…", self.callbacks.delete_run)
        actions.addWidget(self.delete_run_button)
        self.clear_runs_button = button("Clear all…", self.callbacks.clear_runs)
        actions.addWidget(self.clear_runs_button)
        actions.addStretch()
        self.delete_run_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.run_table)
        self.delete_run_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.delete_run_shortcut.activated.connect(self.callbacks.delete_run)
        content.addLayout(actions)
        split.addWidget(panel)
        panel, content = card()
        self.run_heading = label("Select a run", "sectionTitle")
        content.addWidget(self.run_heading)
        self.run_summary = label("", "muted")
        self.run_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.addWidget(self.run_summary)
        self.run_detail_tabs = QTabWidget()
        self.run_recordings = readout()
        self.run_details, self.run_warnings, self.run_errors, self.run_saved, self.run_outputs = (
            readout(),
            readout(),
            readout(),
            readout(),
            readout(),
        )
        self.log = readout()
        for widget, title in (
            (self.run_recordings, "Recordings"),
            (self.run_details, "Parameters"),
            (self.run_warnings, "Warnings"),
            (self.run_errors, "Errors"),
            (self.log, "Processing log"),
            (self.run_saved, "Saved run"),
            (self.run_outputs, "Exports"),
        ):
            self.run_detail_tabs.addTab(widget, title)
        content.addWidget(self.run_detail_tabs, 1)
        split.addWidget(panel)
        split.setSizes([300, 360])
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.history_location = label(str(self.history_directory), "muted")
        self.history_location.setToolTip("Local run history")
        self.history_location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.history_location)

    def toggle_sidebar(self):
        self.sidebar.setExpanded(self.shell.sidebar_collapsed, animated=False)

    def sidebar_expanded(self, expanded):
        self.shell.sidebar_collapsed = not expanded
        self.brand.setVisible(expanded)
        for i, item in enumerate(self.nav_buttons):
            item.setText(f"{i + 1}    {self.sections[i]}" if expanded else str(i + 1))
            item.setToolTip("" if expanded else self.sections[i])

    def resize_data(self, width: int) -> None:
        self._data_page.resize_data(width)

    def data_graphics(self) -> ChannelCanvasView:
        self._data_graph.initialize()
        if self._data_canvas_view is None:
            self._data_canvas_view = ChannelCanvasView(
                self.data_figure, self.data_canvas, self.data_toolbar
            )
        return self._data_canvas_view

    def sensor_graphics(self) -> ChannelCanvasView:
        self._sensor_graph.initialize()
        if self._sensor_canvas_view is None:
            self._sensor_canvas_view = ChannelCanvasView(
                self.sensor_figure, self.sensor_canvas, self.sensor_toolbar
            )
        return self._sensor_canvas_view

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

    def data_view(self) -> DataView:
        return DataView(
            parent=self.parent,
            analysis_input=self.analysis_input,
            analysis_input_detail=self.analysis_input_detail,
            channel_table=self.channel_table,
            continue_button=self.continue_button,
            data_channels=self.data_channels,
            data_tabs=self.data_tabs,
            data_time_channel=self.data_time_channel,
            data_time_unit=self.data_time_unit,
            data_values=self.data_values,
            file_label=self.file_label,
            input_recording=self.input_recording,
            input_table=self.input_table,
            mapping=self.mapping,
            pages=self.pages,
            status=self.status,
            time=self.time,
            time_table=self.time_table,
            data_graphics=self.data_graphics,
        )

    def analysis_view(self) -> AnalysisView:
        return self._analysis_page.view(self.parent, self.status, self.log)

    def job_view(self) -> JobView:
        return JobView(
            parent=self.parent,
            analysis_controls=self.analysis_controls,
            clear_runs_button=self.clear_runs_button,
            data_time_channel=self.data_time_channel,
            data_time_unit=self.data_time_unit,
            delete_run_button=self.delete_run_button,
            export_button=self.export_button,
            input_recording=self.input_recording,
            open_button=self.open_button,
            open_run_button=self.open_run_button,
            progress=self.progress,
            run_button=self.run_button,
            save_results_button=self.save_results_button,
            settings_panel=self.settings_panel,
            status=self.status,
            stop_button=self.stop_button,
            use_parameters_button=self.use_parameters_button,
        )

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

    def export_view(self) -> ExportView:
        return ExportView(
            parent=self.parent,
            status=self.status,
        )

    def shell_view(self) -> ShellView:
        return ShellView(
            parent=self.parent,
            continue_button=self.continue_button,
            data_tabs=self.data_tabs,
            nav_buttons=self.nav_buttons,
            notice=self.notice,
            page_title=self.page_title,
            pages=self.pages,
            run_button=self.run_button,
            stop_button=self.stop_button,
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
