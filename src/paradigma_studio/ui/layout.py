"""Page construction and shared layout helpers for the existing main-window controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QProgressBar,
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
from ..result_workspace_controller import ResultWorkspaceView
from ..shell_controller import ShellView
from ..theme import light_palette
from ..widgets import (
    CheckLabelDelegate,
    HoverSidebar,
    button,
    card,
    combo,
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
from .results_page import ResultsPage, ResultsPageHost
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

    _result_view_layouts = component_attribute("_results_page")
    _result_view_scrolls = component_attribute("_results_page")
    _sensor_graph = component_attribute("_results_page")
    aggregation_table = component_attribute("_results_page")
    canvas = component_attribute("_results_page")
    context_button = component_attribute("_results_page")
    context_controls = component_attribute("_results_page")
    dataset = component_attribute("_results_page")
    dataset_field = component_attribute("_results_page")
    detail_controls = component_attribute("_results_page")
    export_button = component_attribute("_results_page")
    figure = component_attribute("_results_page")
    figure_actions = component_attribute("_results_page")
    figure_actions_layout = component_attribute("_results_page")
    graph_footer = component_attribute("_results_page")
    graph_footer_layout = component_attribute("_results_page")
    graph_scroll = component_attribute("_results_page")
    graph_view = component_attribute("_results_page")
    graph_view_controls = component_attribute("_results_page")
    graph_view_layout = component_attribute("_results_page")
    graphs_workspace = component_attribute("_results_page")
    overview_content = component_attribute("_results_page")
    overview_layout = component_attribute("_results_page")
    overview_scroll = component_attribute("_results_page")
    plot_toolbar = component_attribute("_results_page")
    recording_time_label = component_attribute("_results_page")
    result_graph_view = component_attribute("_results_page")
    result_overlay = component_attribute("_results_page")
    result_series = component_attribute("_results_page")
    result_table = component_attribute("_results_page")
    result_tabs = component_attribute("_results_page")
    result_time_scroll = component_attribute("_results_page")
    results_header = component_attribute("_results_page")
    results_source = component_attribute("_results_page")
    save_results_button = component_attribute("_results_page")
    selection_note = component_attribute("_results_page")
    sensor_channels = component_attribute("_results_page")
    sensor_close = component_attribute("_results_page")
    sensor_tab_index = component_attribute("_results_page")
    sensor_table = component_attribute("_results_page")
    sensor_tabs = component_attribute("_results_page")
    table_actions_layout = component_attribute("_results_page")
    table_dataset = component_attribute("_results_page")
    table_module_tabs = component_attribute("_results_page")
    table_stack = component_attribute("_results_page")
    time_axis = component_attribute("_results_page")
    timing_toggle = component_attribute("_results_page")
    y_column = component_attribute("_results_page")

    data_figure = deferred_attribute("_data_graph")
    data_canvas = deferred_attribute("_data_graph")
    data_toolbar = deferred_attribute("_data_graph")
    sensor_figure = deferred_attribute("_sensor_graph")
    sensor_canvas = deferred_attribute("_sensor_graph")
    sensor_toolbar = deferred_attribute("_sensor_graph")

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

    def _build_results(self) -> None:
        self._results_page = ResultsPage(
            ResultsPageHost(self.parent, self.page(), self.channel_graph, self.sensor_graphics),
            self.callbacks,
            self.graphs,
            self.results,
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
        return self._results_page.result_graphics()

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
            data_time_channel_badge=self._data_page.data_time_channel_badge,
            data_time_unit=self.data_time_unit,
            data_time_unit_badge=self._data_page.data_time_unit_badge,
            data_time_unit_field=self._data_page.data_time_unit_field,
            data_values=self.data_values,
            file_label=self.file_label,
            input_recording=self.input_recording,
            input_table=self.input_table,
            mapping=self.mapping,
            pages=self.pages,
            status=self.status,
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
        return self._results_page.workspace_view()

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
        return self._results_page.graph_view_model()
