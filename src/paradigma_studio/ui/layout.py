"""Page construction and shared layout helpers for the existing main-window controls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListView,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
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
from ..analysis_help import DEFAULT_MAX_GAP_SECONDS, DEFAULT_MIN_SECTION_SECONDS, FIELD_HELP, SOURCE
from ..assets import DATA_DIRECTORY
from ..branding import APP_NAME
from ..data_controller import DataView
from ..export_controller import ExportView
from ..job_controller import JobView
from ..result_workspace_controller import ResultWorkspaceView, set_results_tab
from ..results_view import MODULE_NAMES
from ..shell_controller import ShellView
from ..theme import LINK_COLOR, light_palette, tooltip_text
from ..time_controls import TimeField
from ..widgets import (
    AdaptiveFormColumns,
    CheckLabelDelegate,
    ContextComboBox,
    FigureActionBar,
    HoverSidebar,
    ModuleTabBar,
    ReadableComboBox,
    SeriesTree,
    WrappedForm,
    button,
    card,
    field,
    label,
    readout,
    table,
)
from ..workspace_state import GraphState, ResultState, ShellState
from .deferred import DeferredWidget, deferred_attribute
from .graph_views import ChannelCanvasView, ResultCanvasView
from .result_graphs import ResultGraphView


@dataclass(frozen=True)
class WorkspaceCallbacks:
    update_context_action: Callable[..., Any]
    choose_export: Callable[..., Any]
    clear_runs: Callable[..., Any]
    delete_run: Callable[..., Any]
    graph_clicked: Callable[..., Any]
    hide_sensor_context: Callable[..., Any]
    inspect_input_recording: Callable[..., Any]
    inspect_sensor_context: Callable[..., Any]
    navigate: Callable[..., Any]
    open_file: Callable[..., Any]
    open_run: Callable[..., Any]
    plot: Callable[..., Any]
    reset_origin: Callable[..., Any]
    reset_sensor_context: Callable[..., Any]
    results_tab_changed: Callable[..., Any]
    run_analysis: Callable[..., Any]
    save_results: Callable[..., Any]
    selected_result_series: Callable[..., Any]
    set_input_channels: Callable[..., Any]
    set_sensor_channels: Callable[..., Any]
    show_acknowledgements: Callable[..., Any]
    stop_analysis: Callable[..., Any]
    toggle_analysis_help: Callable[..., Any]
    use_run_parameters: Callable[..., Any]


class WorkspaceLayout:
    """Own widget construction; expose frozen page views and explicit callbacks."""

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
        self._data_canvas_view = self._sensor_canvas_view = self._result_canvas_view = None
        self._build_shell()
        self._build_data()
        self._build_analyze()
        self._build_results()
        self._build_runs()

    @staticmethod
    def combo(items=(), *, combo_type=ReadableComboBox):
        combo = combo_type()
        # A Qt list view and explicit palette avoid native dark-theme popups
        # combining dark selection backgrounds with inherited dark text.
        view = QListView()
        view.setUniformItemSizes(True)
        view.setPalette(light_palette())
        combo.setView(view)
        combo.setPalette(light_palette())
        combo.setMaxVisibleItems(12)
        combo.addItems(items)
        return combo

    def _build_shell(self):
        root = QWidget()
        root.setObjectName("workspace")
        self.parent.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
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

    def page(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.pages.addWidget(widget)
        return layout

    def _build_data(self):
        layout = self.page()
        panel, content = card()
        row = QHBoxLayout()
        self.file_label = label("No recording loaded", "sectionTitle")
        row.addWidget(self.file_label, 1)
        self.input_recording = self.combo()
        self.input_recording.setAccessibleName("Recording to inspect")
        self.input_recording.hide()
        self.input_recording.currentIndexChanged.connect(self.callbacks.inspect_input_recording)
        row.addWidget(self.input_recording, 1)
        self.open_button = button("Open sensor files…", self.callbacks.open_file, primary=True)
        self.open_button.setToolTip("Ctrl+O · CSV, Parquet, CWA, Avro, TSDF or trusted pickle")
        self.open_action = QAction("Open recording", self.parent)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.callbacks.open_file)
        self.parent.addAction(self.open_action)
        row.addWidget(self.open_button)
        content.addLayout(row)
        layout.addWidget(panel)
        self.data_tabs = QTabWidget()
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(18, 18, 18, 18)
        overview_layout.setSpacing(16)
        metrics = QHBoxLayout()
        self.data_values = []
        for title in ("Sensor samples", "Channels", "Missing values"):
            panel, content = card()
            content.addWidget(label(title, "muted"))
            value = label("—", "metricValue")
            content.addWidget(value)
            self.data_values.append(value)
            metrics.addWidget(panel, 1)
        overview_layout.addLayout(metrics)
        details = self.data_details = QSplitter(Qt.Horizontal)
        details.setHandleWidth(12)
        panel, content = card()
        content.addWidget(label("Sensor channels", "sectionTitle"))
        self.channel_table = table()
        content.addWidget(self.channel_table, 1)
        details.addWidget(panel)
        panel, content = card()
        time_controls = QHBoxLayout()
        content.addWidget(label("Time channel", "sectionTitle"))
        self.data_time_channel = self.combo()
        self.data_time_channel.setPlaceholderText("Select time column")
        self.data_time_channel.setToolTip(
            tooltip_text("Time column inspected here. Analysis uses its column mapping.")
        )
        time_controls.addWidget(self.data_time_channel, 1)
        self.data_time_unit = self.combo(
            [
                "relative_s",
                "relative_ms",
                "absolute_s",
                "absolute_ms",
                "difference_s",
                "difference_ms",
            ]
        )
        self.data_time_unit.setToolTip(
            tooltip_text(
                "Units for inspecting the raw time column. Analysis parameters are set on Analyze."
            )
        )
        time_controls.addWidget(self.data_time_unit)
        content.addLayout(time_controls)
        self.time_table = table()
        content.addWidget(self.time_table, 1)
        details.addWidget(panel)
        details.setSizes([660, 400])
        overview_layout.addWidget(details, 1)
        self.data_tabs.addTab(overview, "Overview")
        preview, self.data_channels, self._data_graph = self.channel_graph(
            self.callbacks.set_input_channels, "Sensor channels to plot", "data"
        )
        self.data_tabs.addTab(preview, "Graphs")
        self.input_table = table()
        self.data_tabs.addTab(self.input_table, "Tables")
        layout.addWidget(self.data_tabs, 1)
        self.continue_button = button("Configure analysis  →", lambda: self.callbacks.navigate(1))
        self.continue_button.setEnabled(False)
        self.status_layout.addWidget(self.continue_button)

    def channel_graph(self, select_channels, accessible_name, prefix):
        """Shared raw-sensor workspace: a channel list beside a fitted graph."""
        preview = QWidget()
        preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
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
                    [channel_list.item(i).data(Qt.UserRole) for i in range(channel_list.count())]
                ),
            )
        )
        selection.addWidget(button("Clear", lambda: select_channels([])))
        channel_layout.addLayout(selection)
        channel_list.setPalette(light_palette())
        channel_list.setSelectionMode(QAbstractItemView.NoSelection)
        channel_list.setTextElideMode(Qt.ElideNone)
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
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        toolbar = add_graph_controls(graph_layout, canvas, self.parent)
        graph_layout.addWidget(canvas, 1)
        if prefix == "sensor":
            toolbar.home_callback = self.callbacks.reset_sensor_context
        setattr(self, f"{prefix}_figure", figure)
        setattr(self, f"{prefix}_canvas", canvas)
        setattr(self, f"{prefix}_toolbar", toolbar)

    def _build_analyze(self):
        layout = self.page()
        layout.setSpacing(12)
        scroll = self.analysis_scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("analysisBody")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 4, 0)
        content.setSpacing(16)
        content.setSizeConstraint(QLayout.SetMinimumSize)
        self._build_analysis_input(content)
        # The full stack, including wrapped help, must reserve its real height.
        # Otherwise native controls can grow while the parent still allocates
        # a smaller preferred height, consuming the gap below the parameters.
        self.analysis_controls = WrappedForm()
        controls = QVBoxLayout(self.analysis_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(16)
        # WrappedForm already reserves exactly the stack's required height.
        # AlignTop would cap the layout rectangle at its preferred size hint,
        # compressing spacing when help is taller at the current width.
        self.analysis_help = {}
        self.analysis_help_sections = {}
        self._build_analysis_modules(controls)
        self._build_analysis_parameters()
        self._build_analysis_help()
        controls.addWidget(self.settings_panel)
        controls.addWidget(self.analysis_help_panel)
        content.addWidget(self.analysis_controls)
        content.addStretch()
        self._build_analysis_actions()
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        bar = scroll.verticalScrollBar()
        bar.rangeChanged.connect(
            lambda low, high: bar.setStyleSheet(
                "QScrollBar::handle:vertical { background: transparent; }" if high == low else ""
            )
        )
        bar.setStyleSheet("QScrollBar::handle:vertical { background: transparent; }")
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

    def _build_analysis_input(self, content):
        panel, input_layout = card()
        input_layout.setContentsMargins(18, 14, 18, 14)
        input_row = QHBoxLayout()
        input_row.addWidget(label("Selected input", "muted"))
        self.analysis_input = label("No recording loaded", "sectionTitle")
        input_row.addWidget(self.analysis_input, 1)
        self.analysis_input_detail = label("", "muted")
        input_row.addWidget(self.analysis_input_detail)
        input_row.addWidget(button("Inspect input", lambda: self.callbacks.navigate(0)))
        input_layout.addLayout(input_row)
        content.addWidget(panel)

    def _build_analysis_modules(self, controls):
        modules = QHBoxLayout()
        module_heading = self.analysis_field(
            "Analysis modules", label("Analysis modules", "sectionTitle"), inline=True
        )
        modules.addWidget(module_heading)
        self.module_requirements = label("", "muted")
        self.module_requirements.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.module_buttons = {}
        for name in ("Gait", "Tremor", "Pulse rate"):
            item = button(name)
            item.setObjectName("module")
            item.setProperty("analysisModule", self.modules[name])
            item.setCheckable(True)
            self.module_buttons[name] = item
            modules.addWidget(item, 1)
        self.module_buttons["Gait"].setChecked(True)
        controls.addLayout(modules)

    def _build_analysis_parameters(self):
        self.settings_panel, parameter_card = card()
        parameter_card.setContentsMargins(18, 16, 18, 16)
        parameter_card.setSpacing(14)
        parameter_card.setAlignment(Qt.AlignTop)
        # Reserve the form's actual minimum before help changes the outer
        # layout. Otherwise Qt briefly clips the bottom rows while settling.
        parameter_card.setSizeConstraint(QLayout.SetMinimumSize)
        self.analysis_parameter_fields = WrappedForm()
        self.analysis_parameter_fields.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        parameters = QVBoxLayout(self.analysis_parameter_fields)
        parameters.setContentsMargins(0, 0, 0, 0)
        parameters.setSpacing(14)
        parameters.setAlignment(Qt.AlignTop)
        parameter_card.addWidget(self.analysis_parameter_fields, alignment=Qt.AlignTop)
        parameter_header = QHBoxLayout()
        parameter_header.addWidget(label("Analysis parameters", "sectionTitle"))
        parameter_header.addWidget(self.module_requirements, 1)
        parameters.addLayout(parameter_header)
        left = QFormLayout()
        right = QFormLayout()
        columns = AdaptiveFormColumns(left, right)
        for form in (left, right):
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(12)
        self.side = self.combo(["left", "right"], combo_type=ContextComboBox)
        self.acc = self.combo(["g", "m/s^2"])
        self.gyro = self.combo(["deg/s", "rad/s"])
        self.time = self.combo(
            [
                "relative_s",
                "relative_ms",
                "absolute_s",
                "absolute_ms",
                "difference_s",
                "difference_ms",
            ]
        )
        for widget in (self.side, self.acc, self.gyro, self.time):
            widget.setMinimumWidth(160)
        self.orientation = QLineEdit("x,y,z")
        for title, widget in (
            ("Watch side", self.side),
            ("Acceleration units", self.acc),
            ("Gyroscope units", self.gyro),
            ("Time units", self.time),
        ):
            self.analysis_field(title, widget, form=left)
        sections = self._build_analysis_segmentation(right)
        parameters.addLayout(columns)
        self.mapping = QPlainTextEdit("{}")
        self.mapping.setPlaceholderText('{"timestamp": "time", "ppg": "green"}')
        self.mapping.setFixedHeight(60)
        # Each column flows independently, so short fields use available space.
        self.analysis_field("Device axes", self.orientation, form=left)
        self.analysis_field("Column mapping (JSON)", self.mapping, form=sections)
        left.setFormAlignment(Qt.AlignTop)
        right.setFormAlignment(Qt.AlignTop)
        sections.setAlignment(Qt.AlignTop)
        self._build_analysis_origin(parameters)

    def _build_analysis_segmentation(self, right):
        self.prepared = QCheckBox("Already prepared (skip conversion)")
        self.gaps = QCheckBox("Split recordings at time gaps")
        self.drop_missing = QCheckBox("Exclude missing sensor samples")
        self.drop_missing.setChecked(True)
        for widget in (self.prepared, self.gaps, self.drop_missing):
            widget.setPalette(light_palette())
        right.addRow(
            self.analysis_field("Exclude missing sensor samples", self.drop_missing, inline=True)
        )
        self.segmentation_controls = WrappedForm()
        sections = QGridLayout(self.segmentation_controls)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setColumnStretch(1, 1)
        sections.setHorizontalSpacing(10)
        sections.setVerticalSpacing(12)
        sections.addWidget(
            self.analysis_field("Split recordings at time gaps", self.gaps, inline=True), 0, 0, 1, 2
        )
        self.max_gap, self.min_segment = QDoubleSpinBox(), QDoubleSpinBox()
        self.section_reset_buttons = {}
        for title, widget, default in (
            ("Maximum gap", self.max_gap, DEFAULT_MAX_GAP_SECONDS),
            ("Minimum section duration", self.min_segment, DEFAULT_MIN_SECTION_SECONDS),
        ):
            widget.setRange(0.01, 86400)
            widget.setValue(default)
            widget.setSuffix(" s")
            widget.setDecimals(2)
            widget.setAccessibleName(title)
            reset = button(
                "Default", lambda checked=False, spin=widget, value=default: spin.setValue(value)
            )
            reset.setAccessibleName(f"Reset {title.lower()} to the official default")
            self.section_reset_buttons[title] = reset
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(widget, 1)
            row_layout.addWidget(reset)
            self.analysis_field(title, row, form=sections)
        right.addRow(self.segmentation_controls)
        return sections

    def _build_analysis_origin(self, parameters):
        self.clock_input = TimeField("Time origin", origin=True)
        self.clock_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.origin_reset = button("Default", self.callbacks.reset_origin)
        origin_row = WrappedForm()
        clock_group, reset_group = QHBoxLayout(), QHBoxLayout()
        clock_group.addWidget(self.clock_input)
        reset_group.addWidget(self.origin_reset, alignment=Qt.AlignRight)
        origin_layout = AdaptiveFormColumns(clock_group, reset_group, right_stretch=0)
        origin_layout.setSpacing(12)
        origin_row.setLayout(origin_layout)
        origin_form = QFormLayout()
        origin_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        origin_form.setHorizontalSpacing(10)
        origin_form.setVerticalSpacing(12)
        origin_form.setFormAlignment(Qt.AlignTop)
        self.analysis_field("Time origin", origin_row, form=origin_form)
        parameters.addLayout(origin_form)
        parameters.addWidget(self.analysis_field("Already prepared", self.prepared, inline=True))

    def _build_analysis_help(self):
        # Help belongs below the complete parameter card. Expanding a field's row changes
        # QFormLayout alignment and column widths, shifting unrelated labels.
        self.analysis_help_panel, help_layout = card()
        help_layout.setSpacing(12)
        for title, (info, description) in self.analysis_help.items():
            section = QWidget()
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(4)
            section_layout.addWidget(label(title, "sectionTitle"))
            section_layout.addWidget(description)
            section.hide()
            self.analysis_help_sections[title] = section
            info.toggled.connect(
                lambda checked, title=title: self.callbacks.toggle_analysis_help(title, checked)
            )
            help_layout.addWidget(section)
        self.analysis_help_panel.hide()

    def _build_analysis_actions(self):
        self.run_button = button("Run Analysis", self.callbacks.run_analysis, primary=True)
        self.run_button.setShortcut("Ctrl+Return")
        self.run_button.setEnabled(False)
        self.run_button.setMinimumWidth(170)
        self.stop_button = button("Stop Analysis", self.callbacks.stop_analysis)
        self.stop_button.setEnabled(False)
        self.status_layout.addWidget(self.stop_button)
        self.status_layout.addWidget(self.run_button)
        # Keep the footer height stable when navigation hides its actions.
        # Otherwise Results can resize/repaint after its first row selection.
        self.status_row.setMinimumHeight(
            max(
                control.sizeHint().height()
                for control in (self.continue_button, self.stop_button, self.run_button)
            )
        )

    def analysis_field(self, title, control, *, form=None, inline=False):
        """Accessible help toggles; explanations are kept outside the form rows."""
        text, reference = FIELD_HELP[title]
        info = button("i")
        info.setObjectName("helpInfo")
        info.setFixedSize(22, 22)
        info.setCheckable(True)
        info.setAccessibleName(f"Information: {title}")
        url = reference if reference.startswith("https://") else SOURCE + reference
        visual = ""
        link_title = "ParaDigMa documentation"
        if title == "Device axes":
            image = QUrl.fromLocalFile(str(DATA_DIRECTORY / "directions_axes.png")).toString()
            visual = (
                f'<p><img src="{image}" width="260" height="247"></p>'
                "<p>Reference figure: ParaDigMa Coordinate System guide.</p>"
            )
            link_title = "ParaDigMa documentation · Coordinate System guide"
        description = QLabel(
            f'{escape(text)}{visual}<br><a style="color: {LINK_COLOR}; text-decoration: underline;" '
            f'href="{url}">{link_title}</a>'
        )
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        description.setTextFormat(Qt.RichText)
        description.setOpenExternalLinks(True)
        description.setTextInteractionFlags(Qt.TextBrowserInteraction)
        description.setAccessibleName(f"Help: {title}")
        description.setObjectName("fieldHelp")
        description.hide()
        self.analysis_help[title] = (info, description)
        control.setAccessibleName(title)
        heading = QWidget()
        row = QHBoxLayout(heading)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        title_label = control if inline else label(title, "muted")
        if not inline:
            title_label.setBuddy(control)
        row.addWidget(title_label)
        row.addWidget(info, alignment=Qt.AlignVCenter)
        row.addStretch()
        body = QWidget()
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)
        content.setSizeConstraint(QLayout.SetMinimumSize)
        if form is not None:
            content.setAlignment(Qt.AlignTop)
            content.addWidget(control, alignment=Qt.AlignTop)
            if isinstance(form, QGridLayout):
                index = form.rowCount()
                form.addWidget(heading, index, 0, Qt.AlignTop)
                form.addWidget(body, index, 1, Qt.AlignTop)
            else:
                form.addRow(heading, body)
        else:
            content.addWidget(heading)
            if not inline:
                content.addWidget(control)
        return body

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
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(12)
        body_layout.setSizeConstraint(QLayout.SetMinimumSize)
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
        self.result_tabs.setCornerWidget(actions, Qt.TopRightCorner)

    def _build_result_table_controls(self):
        self.detail_controls = QWidget()
        controls_layout = QVBoxLayout(self.detail_controls)
        controls_layout.setSizeConstraint(QLayout.SetMinimumSize)
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
        self.result_series.setTextElideMode(Qt.ElideNone)
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
        graphs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
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
        graph_scroll.setFrameShape(QFrame.NoFrame)
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
        self.recording_time_label.setAlignment(Qt.AlignCenter)
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
        self.sensor_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
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
        split = QSplitter(Qt.Vertical)
        panel, content = card()
        self.run_table = table()
        self.run_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
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
        self.delete_run_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self.run_table)
        self.delete_run_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.delete_run_shortcut.activated.connect(self.callbacks.delete_run)
        content.addLayout(actions)
        split.addWidget(panel)
        panel, content = card()
        self.run_heading = label("Select a run", "sectionTitle")
        content.addWidget(self.run_heading)
        self.run_summary = label("", "muted")
        self.run_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
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
        self.history_location.setTextInteractionFlags(Qt.TextSelectableByMouse)
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
        orientation = Qt.Horizontal if width >= 1280 else Qt.Vertical
        if self.data_details.orientation() != orientation:
            self.data_details.setOrientation(orientation)
            self.data_details.setSizes([660, 400] if orientation == Qt.Horizontal else [220, 300])

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
        return AnalysisView(
            parent=self.parent,
            acc=self.acc,
            analysis_controls=self.analysis_controls,
            analysis_help=self.analysis_help,
            analysis_help_panel=self.analysis_help_panel,
            analysis_help_sections=self.analysis_help_sections,
            analysis_scroll=self.analysis_scroll,
            clock_input=self.clock_input,
            drop_missing=self.drop_missing,
            gaps=self.gaps,
            gyro=self.gyro,
            log=self.log,
            mapping=self.mapping,
            max_gap=self.max_gap,
            min_segment=self.min_segment,
            module_buttons=self.module_buttons,
            module_requirements=self.module_requirements,
            orientation=self.orientation,
            prepared=self.prepared,
            run_button=self.run_button,
            side=self.side,
            status=self.status,
            stop_button=self.stop_button,
            time=self.time,
        )

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
