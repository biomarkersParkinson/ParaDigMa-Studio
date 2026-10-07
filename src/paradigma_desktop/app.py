"""Native scientific workspace with separate configuration and exploration."""
import json
from html import escape
import logging
import sys
from importlib.metadata import version
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QThread, Signal, QStandardPaths
from PySide6.QtGui import QAction, QIcon, QColor
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QScrollArea, QSplitter, QStackedWidget, QListView,
    QTabBar, QTabWidget, QVBoxLayout, QWidget, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QGridLayout, QLayout, QSizePolicy,
)
from .plot_cache import configure_plot_cache

PLOT_CACHE_DIRECTORY = configure_plot_cache(QStandardPaths.writableLocation(QStandardPaths.GenericCacheLocation))

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib import colormaps, dates

from .core import (
    analyze, export_results, export_table_csv, load_sensor_file, result_tables,
    validate_column_mapping, validate_orientation,
)
from .exploration import PARTICIPANT_COLUMNS, gait_context, measurement_columns, source_timeline
from .recordings import load_recordings, align_recordings, source_key, timeline_offsets
from .history import RunHistory, failure_log, error_summary, merge_errors, run_status, load_result_export, new_run, now
from .inspection import TIME_NAMES, inspect_recording, sensor_descriptives, time_descriptives
from .plot_controls import GraphToolbar, add_graph_controls
from .plotting import GRAPH_COLORS, ScrollableFigureCanvas, binary_indicator, plot_signal, plot_states
from .results_view import (
    MODULE_NAMES, clock_times, clock_origin, aggregation_tables, binary_interval_ends, detail_tables, detail_timing, flat_values, analysis_alignment,
    output_label, plot_metrics, plot_tables, preferred_metric, recording_clock, segment_summary, time_bound, normalise_clock, readable_key, tremor_window_counts,
)
from .theme import STYLESHEET, light_palette, style_axes, module_color
from .analysis_help import FIELD_HELP, SOURCE, DEFAULT_MAX_GAP_SECONDS, DEFAULT_MIN_SECTION_SECONDS
from .time_controls import TimeField
from .time_axis import PinnedTimeAxis
from .widgets import HoverSidebar, FrameModel, ReadableComboBox, ReadableTable, label, button, card, table, readout, field


class SignalHandler(logging.Handler):
    def __init__(self, signal, warning=None, error=None):
        super().__init__()
        self.signal = signal
        self.warning = warning
        self.error = error

    def emit(self, record):
        self.signal.emit(self.format(record))
        if error_summary(record.getMessage()):
            return  # Keep the log; count the individual pipeline failures.
        if record.levelno >= logging.ERROR or failure_log(record.getMessage()):
            if self.error is not None:
                self.error.emit(record.getMessage())
        elif self.warning is not None and record.levelno >= logging.WARNING:
            self.warning.emit(record.getMessage())


class Worker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    message = Signal(str)
    warning = Signal(str)
    error = Signal(str)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        logger = logging.Logger("paradigma-desktop", logging.INFO)
        handler = SignalHandler(self.message, self.warning, self.error)
        logger.addHandler(handler)
        package_logger = logging.getLogger("paradigma")
        previous_level = package_logger.level
        package_logger.setLevel(logging.INFO)
        package_logger.addHandler(handler)
        try:
            self.completed.emit(self.operation(logger))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            package_logger.removeHandler(handler)
            package_logger.setLevel(previous_level)
            handler.close()


class MainWindow(QMainWindow):
    SECTIONS = ("Data", "Analyze", "Results", "Runs")
    MODULES = {"Gait": "gait", "Tremor": "tremor", "Pulse rate": "pulse_rate"}

    def __init__(self, history_dir=None):
        super().__init__()
        self.setWindowTitle("ParaDigMa • Sensor analysis")
        self.setWindowIcon(QIcon(str(Path(__file__).with_name("data") / "app-icon.png")))
        self.resize(1450, 920)
        self.setMinimumSize(960, 650)
        self.setPalette(light_palette())
        self.setStyleSheet(STYLESHEET)
        self.frame = self.results = self.worker = None
        self.source = ""
        self.sources, self.recordings = {}, {}
        self._input_descriptions = {}
        self._recording_bases = {}
        self.tables, self.provenance = {}, {}
        self.aggregation_tables, self._table_choices = {}, {}
        self._timings, self._detail_selections, self._series_items = {}, {}, {}
        self._interval_ends = {}
        self._plot_tables, self._plot_labels = {}, {}
        self._result_selection_artists = []
        self.display_clock = None
        self._source_timelines, self._display_offsets = {}, {}
        self.active_frame = None
        self.active_positions = np.array([], dtype=int)
        self.active_selection = {}
        self.result_source_frame = None
        self.result_timeline = None
        self.sensor_frame = None
        self.active_run = self.current_run = self.selected_run = None
        self.sidebar_collapsed = True
        directory = history_dir or Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / "ParaDigMaDesktop" / "runs"
        self.history = RunHistory(directory)
        self.runs, history_issues = self.history.load()
        self._build_shell()
        self._build_data()
        self._build_analyze()
        self._build_results()
        self._build_runs()
        self._connect()
        self.refresh_runs()
        self.navigate(0)
        self.build_result_overview()
        self.sync_table_outputs()
        self.plot()
        if history_issues:
            self.show_notice("\n".join(history_issues))

    @staticmethod
    def combo(items=()):
        combo = ReadableComboBox()
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
        self.setCentralWidget(root)
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
        self.brand_icon.setPixmap(self.windowIcon().pixmap(28, 28))
        self.brand_icon.setFixedSize(28, 28)
        self.brand_icon.setToolTip("ParaDigMa")
        brand_row.addWidget(self.brand_icon)
        self.brand = label("ParaDigMa", "brand")
        self.brand.setWordWrap(False)
        brand_row.addWidget(self.brand, 1)
        navigation.addLayout(brand_row)
        self.brand_caption = label("SENSOR ANALYSIS", "muted")
        self.brand_caption.setWordWrap(False)
        for widget in (self.brand, self.brand_caption):
            policy = widget.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            widget.setSizePolicy(policy)
        navigation.addWidget(self.brand_caption)
        navigation.addSpacing(24)
        self.nav_buttons = []
        for index, section in enumerate(self.SECTIONS):
            item = button(f"{index + 1}    {section}", lambda checked=False, i=index: self.navigate(i))
            item.setCheckable(True)
            item.setToolTip(section)
            item.setAccessibleName(section)
            item.setShortcut(f"Alt+{index + 1}")
            navigation.addWidget(item)
            self.nav_buttons.append(item)
        navigation.addStretch()
        self.about_button = button("About", self.show_acknowledgements)
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
        center_layout.addWidget(self.status)
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
        self.input_recording.currentIndexChanged.connect(self.inspect_input_recording)
        row.addWidget(self.input_recording, 1)
        self.open_button = button("Open sensor files…", self.open_file, primary=True)
        self.open_button.setToolTip("Ctrl+O · CSV, Parquet, CWA, Avro, TSDF or trusted pickle")
        self.open_action = QAction("Open recording", self)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.open_file)
        self.addAction(self.open_action)
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
        self.data_time_channel.setToolTip("Time column inspected here. Analysis uses its column mapping.")
        time_controls.addWidget(self.data_time_channel, 1)
        self.data_time_unit = self.combo(["relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"])
        self.data_time_unit.setToolTip("Units for inspecting the raw time column. Analysis parameters are set on Analyze.")
        time_controls.addWidget(self.data_time_unit)
        content.addLayout(time_controls)
        self.time_table = table()
        content.addWidget(self.time_table, 1)
        details.addWidget(panel)
        details.setSizes([660, 400])
        overview_layout.addWidget(details, 1)
        self.data_tabs.addTab(overview, "Overview")
        preview = QWidget()
        preview_layout = QHBoxLayout(preview)
        channels = QWidget()
        channels.setMinimumWidth(190)
        channels.setMaximumWidth(260)
        channel_layout = QVBoxLayout(channels)
        channel_layout.addWidget(label("Channels", "sectionTitle"))
        selection = QHBoxLayout()
        selection.addWidget(button("Select all", lambda: self.set_input_channels(self._channel_colors)))
        selection.addWidget(button("Clear", lambda: self.set_input_channels([])))
        channel_layout.addLayout(selection)
        self.data_channels = QListWidget()
        self._channel_colors = {}
        self.data_channels.setPalette(light_palette())
        self.data_channels.setSelectionMode(QAbstractItemView.NoSelection)
        self.data_channels.setTextElideMode(Qt.ElideNone)
        self.data_channels.setAccessibleName("Sensor channels to plot")
        channel_layout.addWidget(self.data_channels, 1)
        preview_layout.addWidget(channels)
        graph = QWidget()
        graph_layout = QVBoxLayout(graph)
        self.data_figure = Figure(layout="constrained")
        self.data_canvas = FigureCanvasQTAgg(self.data_figure)
        self.data_toolbar = add_graph_controls(graph_layout, self.data_canvas, self)
        graph_layout.addWidget(self.data_canvas, 1)
        preview_layout.addWidget(graph, 1)
        self.data_tabs.addTab(preview, "Graphs")
        self.input_table = table()
        self.data_tabs.addTab(self.input_table, "Tables")
        layout.addWidget(self.data_tabs, 1)
        self.continue_button = button("Configure analysis  →", lambda: self.navigate(1))
        self.continue_button.setEnabled(False)
        layout.addWidget(self.continue_button, alignment=Qt.AlignRight)

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
        panel, input_layout = card()
        input_layout.setContentsMargins(18, 14, 18, 14)
        input_row = QHBoxLayout()
        input_row.addWidget(label("Selected input", "muted"))
        self.analysis_input = label("No recording loaded", "sectionTitle")
        input_row.addWidget(self.analysis_input, 1)
        self.analysis_input_detail = label("", "muted")
        input_row.addWidget(self.analysis_input_detail)
        input_row.addWidget(button("Inspect input", lambda: self.navigate(0)))
        input_layout.addLayout(input_row)
        content.addWidget(panel)
        self.analysis_controls = QWidget()
        controls = QVBoxLayout(self.analysis_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(16)
        self.analysis_help = {}
        modules = QHBoxLayout()
        modules.addWidget(self.analysis_field("Analysis modules", label("Analysis modules", "sectionTitle"), inline=True))
        self.module_requirements = label("", "muted")
        self.module_requirements.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.module_buttons = {}
        for name in ("Gait", "Tremor", "Pulse rate"):
            item = button(name)
            item.setObjectName("module")
            item.setProperty("analysisModule", self.MODULES[name])
            item.setCheckable(True)
            self.module_buttons[name] = item
            modules.addWidget(item, 1)
        self.module_buttons["Gait"].setChecked(True)
        controls.addLayout(modules)
        self.settings_panel, parameters = card()
        parameters.setContentsMargins(18, 16, 18, 16)
        parameters.setSpacing(14)
        parameter_header = QHBoxLayout()
        parameter_header.addWidget(label("Analysis parameters", "sectionTitle"))
        parameter_header.addWidget(self.module_requirements, 1)
        parameters.addLayout(parameter_header)
        columns = QHBoxLayout()
        columns.setSpacing(20)
        left = QFormLayout()
        right = QFormLayout()
        for form in (left, right):
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(12)
        self.side = self.combo(["left", "right"])
        self.acc = self.combo(["g", "m/s^2"])
        self.gyro = self.combo(["deg/s", "rad/s"])
        self.time = self.combo(["relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"])
        for widget in (self.side, self.acc, self.gyro, self.time):
            widget.setMinimumWidth(160)
        self.orientation = QLineEdit("x,y,z")
        for title, widget in (("Watch side", self.side), ("Acceleration units", self.acc),
                              ("Gyroscope units", self.gyro), ("Time units", self.time)):
            self.analysis_field(title, widget, form=left)
        self.prepared = QCheckBox("Already prepared (skip conversion)")
        self.gaps = QCheckBox("Split recordings at time gaps")
        self.drop_missing = QCheckBox("Exclude missing sensor samples")
        self.drop_missing.setChecked(True)
        for widget in (self.prepared, self.gaps, self.drop_missing):
            widget.setPalette(light_palette())
        right.addRow(self.analysis_field("Exclude missing sensor samples", self.drop_missing, inline=True))
        self.segmentation_controls = QWidget()
        sections = QFormLayout(self.segmentation_controls)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setRowWrapPolicy(QFormLayout.WrapLongRows)
        sections.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        sections.setHorizontalSpacing(10)
        sections.setVerticalSpacing(12)
        sections.addRow(self.analysis_field("Split recordings at time gaps", self.gaps, inline=True))
        self.max_gap, self.min_segment = QDoubleSpinBox(), QDoubleSpinBox()
        self.section_reset_buttons = {}
        for title, widget, default in (("Maximum gap", self.max_gap, DEFAULT_MAX_GAP_SECONDS),
                                        ("Minimum section duration", self.min_segment, DEFAULT_MIN_SECTION_SECONDS)):
            widget.setRange(0.01, 86400)
            widget.setValue(default)
            widget.setSuffix(" s")
            widget.setDecimals(2)
            widget.setAccessibleName(title)
            reset = button("Default", lambda checked=False, spin=widget, value=default: spin.setValue(value))
            reset.setAccessibleName(f"Reset {title.lower()} to the official default")
            self.section_reset_buttons[title] = reset
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(widget, 1)
            row_layout.addWidget(reset)
            self.analysis_field(title, row, form=sections)
        right.addRow(self.segmentation_controls)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        parameters.addLayout(columns)
        self.mapping = QPlainTextEdit("{}")
        self.mapping.setPlaceholderText('{"timestamp": "time", "ppg": "green"}')
        self.mapping.setFixedHeight(60)
        # Keep channel configuration together, with room to read mappings.
        input_fields = QHBoxLayout()
        input_fields.setSpacing(20)
        axes_form, mapping_form = QFormLayout(), QFormLayout()
        for form in (axes_form, mapping_form):
            form.setRowWrapPolicy(QFormLayout.DontWrapRows)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(12)
        self.analysis_field("Device axes", self.orientation, form=axes_form)
        self.analysis_field("Column mapping (JSON)", self.mapping, form=mapping_form)
        input_fields.addLayout(axes_form, 1)
        input_fields.addLayout(mapping_form, 1)
        parameters.addLayout(input_fields)
        parameters.addWidget(self.analysis_field("Already prepared", self.prepared, inline=True))
        controls.addWidget(self.settings_panel)
        content.addWidget(self.analysis_controls)
        content.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        self.run_button = button("Run Analysis", self.run_analysis, primary=True)
        self.run_button.setShortcut("Ctrl+Return")
        self.run_button.setEnabled(False)
        self.run_button.setMinimumWidth(170)
        row.addWidget(self.run_button)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        layout.addLayout(row)

    def analysis_field(self, title, control, *, form=None, inline=False):
        """Accessible, keyboard-operable help expanded beside its own field."""
        text, reference = FIELD_HELP[title]
        info = button("i")
        info.setObjectName("helpInfo")
        info.setFixedSize(22, 22)
        info.setCheckable(True)
        info.setAccessibleName(f"Information: {title}")
        description = QLabel(f'{escape(text)}<br><a href="{SOURCE}{reference}">ParaDigMa documentation</a>')
        description.setWordWrap(True)
        description.setTextFormat(Qt.RichText)
        description.setOpenExternalLinks(True)
        description.setTextInteractionFlags(Qt.TextBrowserInteraction)
        description.setAccessibleName(f"Help: {title}")
        description.setObjectName("fieldHelp")
        description.hide()
        info.toggled.connect(description.setVisible)
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
        if form is not None:
            content.addWidget(control)
            content.addWidget(description)
            form.addRow(heading, body)
        else:
            content.addWidget(heading)
            if not inline:
                content.addWidget(control)
            content.addWidget(description)
        return body

    def _build_results(self):
        layout = self.page()
        self.result_tabs = QTabWidget()
        self.result_tabs.tabBar().setExpanding(False)
        self.result_tabs.setMinimumHeight(200)
        layout.addWidget(self.result_tabs, 1)
        self._result_view_layouts, self._result_view_scrolls = [], []

        def view(title, pinned=False):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            body = QWidget()
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(12, 12, 12, 12)
            body_layout.setSpacing(12)
            body_layout.setSizeConstraint(QLayout.SetMinimumSize)
            scroll.setWidget(body)
            if pinned:
                self.graph_view = QWidget()
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

        self.results_header = QWidget()
        header = QHBoxLayout(self.results_header)
        header.setContentsMargins(0, 0, 0, 0)
        self.results_source = label("No analysis results", "muted")
        header.addWidget(self.results_source, 1)
        actions = QWidget()
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(12, 0, 0, 0)
        self.filters_toggle = button("Filters")
        self.filters_toggle.setCheckable(True)
        self.csv_button = button("Export CSV…", self.export_csv)
        self.csv_button.setAccessibleName("Export selection CSV")
        self.export_button = button("Export JSON…", self.export)
        self.export_button.setAccessibleName("Export all results JSON")
        self.csv_button.setEnabled(False)
        self.export_button.setEnabled(False)
        for item in (self.filters_toggle, self.csv_button, self.export_button):
            action_layout.addWidget(item)
        self.result_tabs.setCornerWidget(actions, Qt.TopRightCorner)
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
        self.timing_toggle.setToolTip("Add display-only dates and gait timing estimates; original output columns stay unchanged.")
        settings.addWidget(self.timing_toggle)
        self.y_column = self.combo()
        # Kept as internal metric state for linked table/graph inspection.
        # Plot series is the user-facing metric selector.
        self.y_column.setParent(self.detail_controls)
        self.y_column.hide()
        settings.addStretch()
        controls_layout.addLayout(settings)
        self.filters_panel, filters = card()
        filters.setSizeConstraint(QLayout.SetMinimumSize)
        self.time_grid = QGridLayout()
        self.clock_input = TimeField("Time origin", origin=True)
        self.time_from, self.time_to = TimeField("From"), TimeField("Until")
        self.time_fields = [field(title, control) for title, control in
                            (("Time origin", self.clock_input), ("From", self.time_from), ("Until", self.time_to))]
        for widget in self.time_fields:
            widget.setMinimumHeight(64)
        self._time_field_columns = None
        self.arrange_time_fields()
        filters.addLayout(self.time_grid)
        self.time_zone = label("", "muted")
        filters.addWidget(self.time_zone)
        row = QHBoxLayout()
        row.addStretch()
        self.filter_apply = button("Apply", self.apply_filters, primary=True)
        self.filter_reset = button("Reset", self.reset_filters)
        row.addWidget(self.filter_apply, alignment=Qt.AlignBottom)
        row.addWidget(self.filter_reset, alignment=Qt.AlignBottom)
        filters.addLayout(row)
        self.filter_status = label("", "muted")
        self.filter_status.hide()
        filters.addWidget(self.filter_status)
        controls_layout.addWidget(self.filters_panel)
        self.filters_panel.hide()
        self.selection_note = label("No detailed output", "muted")
        controls_layout.addWidget(self.selection_note)
        self.table_module_tabs = QTabBar()
        self.table_module_tabs.setExpanding(False)
        for title in MODULE_NAMES.values():
            self.table_module_tabs.addTab(title)
        self.table_module_tabs.setCurrentIndex(0)
        controls_layout.insertWidget(0, self.table_module_tabs)
        self.overview_scroll, overview_body = view("Overview")
        self.overview_content = QWidget()
        self.overview_layout = QVBoxLayout(self.overview_content)
        self.overview_layout.setContentsMargins(0, 0, 0, 0)
        self.overview_layout.setSpacing(16)
        overview_body.addWidget(self.overview_content, 1)
        _, graph_body = view("Graphs", pinned=True)
        graphs = QWidget()
        graph_layout = QHBoxLayout(graphs)
        self.result_series = QTreeWidget()
        self.result_series.setHeaderLabel("Plot series")
        self.result_series.setPalette(light_palette())
        self.result_series.setMinimumWidth(190)
        self.result_series.setMaximumWidth(285)
        self.result_series.setWordWrap(True)
        self.result_series.setTextElideMode(Qt.ElideNone)
        self.result_series.setAccessibleName("Results to plot simultaneously")
        graph_layout.addWidget(self.result_series)
        graph = QWidget()
        plots = QVBoxLayout(graph)
        plots.setContentsMargins(0, 0, 0, 0)
        self.figure = Figure(layout="constrained")
        self.canvas = ScrollableFigureCanvas(self.figure)
        self.canvas.pinned_time_axis = True
        self.figure_actions = QWidget()
        self.figure_actions_layout = QHBoxLayout(self.figure_actions)
        self.figure_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_toolbar = GraphToolbar(self.canvas, self)
        self.figure_actions_layout.addWidget(self.plot_toolbar)
        self.figure_actions_layout.addStretch()
        graph_body.addWidget(self.figure_actions)
        graph_body.addWidget(self.plot_toolbar.settings)
        graph_scroll = QScrollArea()
        graph_scroll.setWidgetResizable(True)
        graph_scroll.setWidget(self.canvas)
        self.graph_scroll = graph_scroll
        self.canvas.scroll_area = graph_scroll
        self.canvas.outer_scroll_area = self._result_view_scrolls[1]
        plots.addWidget(graph_scroll, 1)
        graph_layout.addWidget(graph, 1)
        self.canvas.setToolTip("Click a point to select its detailed output row.")
        graphs.setMinimumHeight(310)
        self.graphs_workspace = graphs
        graph_body.addWidget(graphs, 1)
        self.time_axis = PinnedTimeAxis(self.canvas, lambda: self.plot_toolbar.settings.axes())
        self.graph_view_layout.addWidget(self.time_axis)
        self.graph_scroll.verticalScrollBar().valueChanged.connect(self.time_axis.synchronize)
        self._result_view_scrolls[1].verticalScrollBar().valueChanged.connect(self.time_axis.synchronize)
        _, table_body = view("Tables")
        self.result_table = table()
        self.result_table.setMinimumHeight(200)
        self.aggregation_table = table()
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.result_table)
        self.table_stack.addWidget(self.aggregation_table)
        table_body.addWidget(self.table_stack, 1)
        self.sensor_panel, sensor_layout = card()
        self.sensor_note = label("", "muted")
        sensor_header = QHBoxLayout()
        sensor_header.addWidget(label("Underlying sensor context", "sectionTitle"), 1)
        sensor_header.addWidget(button("Close", self.hide_sensor_context))
        sensor_layout.addLayout(sensor_header)
        sensor_layout.addWidget(self.sensor_note)
        self.sensor_channel = self.combo()
        sensor_layout.addWidget(self.sensor_channel)
        sensor_tabs = QTabWidget()
        sensor_graph = QWidget()
        graph_layout = QVBoxLayout(sensor_graph)
        self.sensor_figure = Figure(layout="constrained")
        self.sensor_canvas = FigureCanvasQTAgg(self.sensor_figure)
        self.sensor_toolbar = add_graph_controls(graph_layout, self.sensor_canvas, self)
        graph_layout.addWidget(self.sensor_canvas, 1)
        sensor_tabs.addTab(sensor_graph, "Signal")
        self.sensor_table = table()
        sensor_tabs.addTab(self.sensor_table, "Samples")
        sensor_layout.addWidget(sensor_tabs, 1)
        _, sensor_body = view("Sensor context")
        sensor_body.addWidget(self.sensor_panel, 1)
        self.sensor_tab_index = 3
        self.result_tabs.setTabVisible(self.sensor_tab_index, False)
        context = QHBoxLayout()
        context.setContentsMargins(0, 0, 0, 0)
        self.context_button = button("Inspect sensor context", self.inspect_sensor_context)
        self.context_button.setEnabled(False)
        self.context_button.setToolTip("Select a result row or click a graph point")
        context.addWidget(self.context_button)
        self.context_radius = QDoubleSpinBox()
        self.context_radius.setRange(0.1, 120)
        self.context_radius.setValue(2)
        self.context_radius.setSuffix(" s")
        self.context_radius.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.context_radius.setAccessibleName("Sensor context radius")
        self.context_radius.setToolTip("Original samples within this radius of the selected time; not an analysis window.")
        context.addWidget(label("±", "muted"))
        context.addWidget(self.context_radius)
        self.context_controls = QWidget()
        self.context_controls.setLayout(context)
        self.result_tabs.currentChanged.connect(self.results_tab_changed)
        self.results_tab_changed(0)

    def _build_runs(self):
        layout = self.page()
        split = QSplitter(Qt.Vertical)
        panel, content = card()
        self.run_table = table()
        content.addWidget(self.run_table, 1)
        actions = QHBoxLayout()
        self.open_run_button = button("Open results", self.open_run)
        self.use_parameters_button = button("Use these parameters", self.use_run_parameters)
        actions.addWidget(self.open_run_button)
        actions.addWidget(self.use_parameters_button)
        actions.addStretch()
        content.addLayout(actions)
        split.addWidget(panel)
        panel, content = card()
        self.run_heading = label("Select a run", "sectionTitle")
        content.addWidget(self.run_heading)
        self.run_summary = label("", "muted")
        self.run_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.addWidget(self.run_summary)
        self.run_detail_tabs = QTabWidget()
        self.run_details, self.run_warnings, self.run_errors, self.run_outputs = readout(), readout(), readout(), readout()
        self.log = readout()
        for widget, title in ((self.run_details, "Parameters"), (self.run_warnings, "Warnings"),
                              (self.run_errors, "Errors"), (self.run_outputs, "Outputs"), (self.log, "Processing log")):
            self.run_detail_tabs.addTab(widget, title)
        content.addWidget(self.run_detail_tabs, 1)
        split.addWidget(panel)
        split.setSizes([300, 360])
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.history_location = label(str(self.history.directory), "muted")
        self.history_location.setToolTip("Local run history")
        self.history_location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.history_location)

    def _connect(self):
        self.filters_toggle.toggled.connect(self.filters_panel.setVisible)
        self.filters_toggle.toggled.connect(lambda _checked: self.arrange_time_fields())
        self.filters_toggle.toggled.connect(lambda _checked: self.results_tab_changed(self.result_tabs.currentIndex()))
        self.prepared.toggled.connect(self.preparation_changed)
        self.gaps.toggled.connect(self.preparation_changed)
        self.drop_missing.toggled.connect(self.preparation_changed)
        for name, item in self.module_buttons.items():
            item.toggled.connect(lambda checked, n=name: self.modules_changed(n, checked))
        for combo in (self.acc, self.gyro, self.time):
            combo.currentTextChanged.connect(self.preparation_changed)
        self.data_channels.itemChanged.connect(self.plot_input)
        self.data_time_channel.currentIndexChanged.connect(self.refresh_data_descriptives)
        self.time.currentTextChanged.connect(self.data_time_unit.setCurrentText)
        self.data_time_unit.currentTextChanged.connect(self.update_time_statistics)
        self.dataset.currentTextChanged.connect(self.select_dataset)
        self.table_dataset.currentIndexChanged.connect(self.select_output_table)
        self.table_module_tabs.currentChanged.connect(self.table_module_changed)
        self.timing_toggle.toggled.connect(self.table_timing_changed)
        self.y_column.currentIndexChanged.connect(self.update_metric)
        self.result_series.itemChanged.connect(self.plot)
        self.result_series.currentItemChanged.connect(self.select_plot_series)
        for edit in (self.time_from, self.time_to, self.clock_input):
            edit.returnPressed.connect(self.apply_filters)
        self.sensor_channel.currentIndexChanged.connect(self.plot_sensor)
        self.canvas.mpl_connect("button_press_event", self.graph_clicked)
        self.modules_changed()
        self.preparation_changed()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.page_title.setText(self.SECTIONS[index])
        for i, item in enumerate(self.nav_buttons):
            item.setChecked(i == index)

    def show_acknowledgements(self):
        if getattr(self, "_acknowledgements_dialog", None) is None:
            from .acknowledgements import AcknowledgementsDialog
            self._acknowledgements_dialog = AcknowledgementsDialog(self)
        self._acknowledgements_dialog.show()
        self._acknowledgements_dialog.raise_()
        self._acknowledgements_dialog.activateWindow()

    def toggle_sidebar(self):
        self.sidebar.setExpanded(self.sidebar_collapsed, animated=False)

    def sidebar_expanded(self, expanded):
        self.sidebar_collapsed = not expanded
        self.brand.setVisible(expanded)
        self.brand_caption.setVisible(expanded)
        for i, item in enumerate(self.nav_buttons):
            item.setText(f"{i + 1}    {self.SECTIONS[i]}" if expanded else str(i + 1))

    def show_notice(self, message, severity="warning"):
        self.notice.setProperty("severity", severity)
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self.notice.setText(message)
        self.notice.setVisible(bool(message))

    def selected_modules(self):
        return [self.MODULES[name] for name, item in self.module_buttons.items() if item.isChecked()]

    def set_modules(self, pipelines):
        selected = set(pipelines)
        for name, item in self.module_buttons.items():
            blocked = item.blockSignals(True)
            item.setChecked(self.MODULES[name] in selected)
            item.blockSignals(blocked)
        self.modules_changed()

    def modules_changed(self, changed=None, checked=False):
        selected = self.selected_modules()
        self.side.setEnabled("gait" in selected)
        requirements = []
        if "gait" in selected or ("pulse_rate" in selected and not self.prepared.isChecked()):
            requirements.append("Accelerometer")
        if "gait" in selected or "tremor" in selected:
            requirements.append("gyroscope")
        if "pulse_rate" in selected:
            requirements.append("raw green PPG")
        text = ", ".join(requirements)
        self.module_requirements.setText(text[0].upper() + text[1:] + " required." if text else "Select an analysis module.")
        self.run_button.setEnabled(self.frame is not None and bool(selected) and self.worker is None)

    def preparation_changed(self, *_):
        prepared = self.prepared.isChecked()
        for widget in (self.acc, self.gyro, self.time, self.orientation, self.gaps):
            widget.setEnabled(not prepared)
        for widget in (self.max_gap, self.min_segment):
            widget.setEnabled(not prepared and self.gaps.isChecked())
        self.modules_changed()

    def start_job(self, operation, completed):
        if self.worker is not None:
            return
        for widget in (self.open_button, self.run_button, self.settings_panel, self.analysis_controls,
                       self.export_button, self.csv_button, self.open_run_button, self.use_parameters_button,
                       self.data_time_channel, self.data_time_unit, self.input_recording):
            widget.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.worker = Worker(operation)
        self.worker.completed.connect(completed)
        self.worker.failed.connect(self.failure)
        self.worker.message.connect(self.append_log)
        self.worker.warning.connect(self.capture_warning)
        self.worker.error.connect(self.capture_error)
        self.worker.finished.connect(self.job_finished)
        self.worker.start()

    def job_finished(self):
        worker = self.worker
        self.worker = None
        self.open_button.setEnabled(True)
        self.settings_panel.setEnabled(True)
        self.analysis_controls.setEnabled(True)
        self.data_time_channel.setEnabled(True)
        self.data_time_unit.setEnabled(True)
        self.input_recording.setEnabled(True)
        self.modules_changed()
        self.preparation_changed()
        self.export_button.setEnabled(self.results is not None)
        self.csv_button.setEnabled(self.selected_export_table()[1] is not None)
        self.progress.hide()
        if worker is not None:
            worker.deleteLater()
        self.update_run_actions()

    def append_log(self, message):
        if self.active_run is not None:
            self.active_run["log"] += message + "\n"
            if self.selected_run is self.active_run:
                self.log.appendPlainText(message)
        elif self.selected_run is None:
            self.log.appendPlainText(message)

    def capture_warning(self, message):
        if self.active_run is not None and message not in self.active_run["warnings"]:
            self.active_run["warnings"].append(message)
            self.update_run_problems()

    def capture_error(self, message):
        if self.active_run is not None and message not in self.active_run["errors"]:
            self.active_run["errors"].append(message)
            self.update_run_problems()

    def update_run_problems(self):
        record = self.active_run
        if self.selected_run is record:
            self.run_warnings.setPlainText("\n\n".join(record["warnings"]) or "No recorded warnings.")
            self.run_errors.setPlainText("\n\n".join(record["errors"]) or "No recorded errors.")
            self.run_summary.setText(self.run_summary_text(record))
        model = self.run_table.model()
        row = next((i for i, run in enumerate(self.runs) if run is record), None)
        if model is not None and row is not None:
            for name in ("Warnings", "Errors"):
                column = model.frame.columns.get_loc(name)
                model.frame.iat[row, column] = len(record[name.lower()])
                index = model.index(row, column)
                model.dataChanged.emit(index, index, [Qt.DisplayRole])

    def persist_run(self, record):
        try:
            self.history.save(record)
        except (OSError, ValueError, TypeError) as exc:
            self.show_notice(f"Analysis remains available, but run history could not be saved: {exc}")

    def finish_run(self, status, errors=()):
        if self.active_run is None:
            return
        record = self.active_run
        record["status"], record["finished"] = status, now()
        record["errors"] = merge_errors(record["errors"], errors)
        if record["errors"] and status == "Completed":
            record["status"] = "Partial"
        self.persist_run(record)
        self.active_run = None
        self.refresh_runs()

    def failure(self, message):
        self.status.setText("Operation failed. See the processing log.")
        self.append_log(message)
        self.show_notice(message, "error")
        self.finish_run("Failed", [message])

    def clear_results(self):
        self.results, self.active_frame = None, None
        self.display_clock = None
        self._source_timelines, self._display_offsets = {}, {}
        self.clock_input.clear()
        self.tables = {}
        self.aggregation_tables, self._table_choices = {}, {}
        self._timings, self._detail_selections, self._series_items = {}, {}, {}
        self._interval_ends = {}
        self._plot_tables, self._plot_labels = {}, {}
        self.result_series.blockSignals(True)
        self.result_series.clear()
        self.result_series.blockSignals(False)
        self.dataset.clear()
        self.result_table.setModel(None)
        self.aggregation_table.setModel(None)
        self.sync_table_outputs()
        self.build_result_overview()
        self.export_button.setEnabled(False)
        self.csv_button.setEnabled(False)
        self.hide_sensor_context()
        self.context_button.setEnabled(False)
        self.figure.clear()
        self.time_axis.bind(None)
        self.canvas.draw_idle()

    def open_file(self):
        if self.worker is not None:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Open recordings for the same subject", "",
            "Sensor files (*.csv *.parquet *.pkl *.pickle *.json *.avro *.cwa *.CWA);;All files (*)")
        if not paths:
            return
        allow_pickle = False
        if any(Path(path).suffix.lower() in (".pkl", ".pickle") for path in paths):
            reply = QMessageBox.warning(self, "Trusted pickle files only",
                "Pickle files can execute code when opened. Only continue if you trust every selected pickle file's source.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            allow_pickle = True
        self.show_notice("")
        self.status.setText("Loading recordings…")
        unit = self.time.currentText()
        def load(logger):
            sources, frames = load_recordings(paths, allow_pickle=allow_pickle, logger=logger)
            descriptions = {key: inspect_recording(frame, unit) for key, frame in frames.items()}
            return sources, frames, descriptions
        self.start_job(load, self.loaded_recordings)

    def loaded_recordings(self, payload):
        sources, recordings, descriptions = payload
        if len(recordings) == 1:
            key = next(iter(recordings))
            self.loaded((sources[key], recordings[key], descriptions[key]))
            return
        self.input_recording.blockSignals(True)
        self.input_recording.clear()
        for key, path in sources.items():
            self.input_recording.addItem(f"{key} · {Path(path).name}", key)
            self.input_recording.setItemData(self.input_recording.count() - 1, path, Qt.ToolTipRole)
        self.input_recording.blockSignals(False)
        self.sources, self.recordings = sources, recordings
        self._input_descriptions = descriptions
        self.inspect_input_recording()
        self.status.setText(f"{len(recordings)} recordings loaded for one subject.")

    def inspect_input_recording(self, *_):
        key = self.input_recording.currentData()
        if key not in self.recordings:
            return
        sources, recordings, descriptions = self.sources, self.recordings, self._input_descriptions
        self.loaded((sources[key], recordings[key], descriptions[key]))
        self.sources, self.recordings = sources, recordings
        self._input_descriptions = descriptions
        self.input_recording.show()
        self.file_label.setText(f"{len(recordings)} recordings")
        self.file_label.setToolTip("\n".join(sources.values()))
        self.analysis_input.setText(f"{len(recordings)} recordings · One subject")
        self.analysis_input_detail.setText(f"{sum(len(frame) for frame in recordings.values()):,} samples")

    def loaded(self, payload):
        self.source, self.frame = payload[:2]
        self.sources, self.recordings = {"recording_001": self.source}, {}
        self._input_descriptions = {}
        self.input_recording.hide()
        description = payload[2] if len(payload) > 2 else inspect_recording(self.frame, self.time.currentText())
        self.data_tabs.setCurrentIndex(0)
        self.input_table.setModel(FrameModel(self.frame))
        self.file_label.setText(Path(self.source).name)
        self.file_label.setToolTip(self.source)
        self.analysis_input.setText(Path(self.source).name)
        self.analysis_input_detail.setText(f"{len(self.frame):,} samples · {len(self.frame.columns)} channels")
        self.data_values[0].setText(f"{len(self.frame):,}")
        self.data_values[1].setText(str(len(self.frame.columns)))
        self.data_values[2].setText(f"{description['missing']:,}")
        self.data_time_channel.blockSignals(True)
        self.data_time_channel.clear()
        for column in self.frame:
            self.data_time_channel.addItem(str(column), column)
        self.data_time_channel.setCurrentIndex(self.data_time_channel.findData(description["time_column"]))
        self.data_time_channel.blockSignals(False)
        self.data_time_unit.blockSignals(True)
        self.data_time_unit.setCurrentText(description["time_unit"])
        self.data_time_unit.blockSignals(False)
        self.channel_table.setModel(FrameModel(description["sensors"], compact=True))
        self.time_table.setModel(FrameModel(description["time"], compact=True) if description["time"] is not None else None)
        self.update_time_unit_control()
        self.populate_input_channels()
        self.plot_input()
        self.continue_button.setEnabled(True)
        self.modules_changed()
        self.show_notice("")
        self.navigate(0)
        if self.frame.attrs.get("source_format") == "empatica" and not any(f"gyroscope_{axis}" in self.frame for axis in "xyz"):
            message = ("Empatica accelerometer samples loaded. Gait and tremor require gyroscope data; "
                       "pulse rate requires raw green PPG. This import contains neither.")
            self.status.setText(message)
            self.show_notice(message)
            self.append_log(message)
        else:
            self.status.setText("Recording loaded.")

    def update_time_unit_control(self):
        column = self.data_time_channel.currentData()
        numeric_time = self.frame is not None and column in self.frame and not (
            pd.api.types.is_datetime64_any_dtype(self.frame[column].dtype)
            or pd.api.types.is_timedelta64_dtype(self.frame[column].dtype))
        self.data_time_unit.setVisible(numeric_time)
        self.data_time_unit.setEnabled(self.worker is None)

    def refresh_data_descriptives(self, *_):
        if self.frame is not None:
            column = self.data_time_channel.currentData()
            self.channel_table.setModel(FrameModel(sensor_descriptives(self.frame, column), compact=True))
            self.populate_input_channels(self.selected_input_channels())
            self.update_time_statistics()
            self.plot_input()

    def update_time_statistics(self, *_):
        column = self.data_time_channel.currentData()
        if self.frame is not None and column in self.frame:
            self.time_table.setModel(FrameModel(time_descriptives(self.frame[column], self.data_time_unit.currentText()), compact=True))
        else:
            self.time_table.setModel(None)
        self.update_time_unit_control()

    def selected_input_channels(self):
        return [self.data_channels.item(i).data(Qt.UserRole) for i in range(self.data_channels.count())
                if self.data_channels.item(i).checkState() == Qt.Checked]

    def set_input_channels(self, channels):
        self.data_channels.blockSignals(True)
        for i in range(self.data_channels.count()):
            item = self.data_channels.item(i)
            item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in channels else Qt.Unchecked)
        self.data_channels.blockSignals(False)
        self.plot_input()

    def populate_input_channels(self, selection=None):
        numeric = [column for column in self.frame.select_dtypes(include=["number", "bool"]).columns
                   if str(column).lower() not in TIME_NAMES
                   and not pd.api.types.is_complex_dtype(self.frame[column].dtype)]
        colors = GRAPH_COLORS if len(numeric) <= len(GRAPH_COLORS) else colormaps["tab20"].colors if len(numeric) <= 20 else colormaps["turbo"](np.linspace(.05, .95, len(numeric)))
        self._channel_colors = {column: colors[i] for i, column in enumerate(numeric)}
        self.data_channels.blockSignals(True)
        self.data_channels.clear()
        for column in numeric:
            if column == self.data_time_channel.currentData():
                continue
            item = QListWidgetItem(str(column), self.data_channels)
            item.setData(Qt.UserRole, column)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if selection is not None and column in selection else Qt.Unchecked)
        if selection is None and self.data_channels.count():
            self.data_channels.item(0).setCheckState(Qt.Checked)
        self.data_channels.blockSignals(False)

    def plot_input(self, *_):
        self.data_figure.clear()
        channels = self.selected_input_channels()
        if self.frame is None or not channels:
            ax = style_axes(self.data_figure)
            ax.text(.5, .5, "Select sensor channels" if self.frame is not None else "Open a recording with numeric sensor channels",
                    ha="center", transform=ax.transAxes, color="#60728A")
        else:
            column = self.data_time_channel.currentData()
            times, time_label = None, "Time (file units)"
            if column in self.frame:
                series = self.frame[column]
                if pd.api.types.is_datetime64_any_dtype(series.dtype):
                    times, time_label = series, "Time"
                elif pd.api.types.is_timedelta64_dtype(series.dtype):
                    times, time_label = series.dt.total_seconds(), "Time (s)"
                elif not pd.api.types.is_complex_dtype(series.dtype):
                    times = pd.to_numeric(series, errors="coerce")
            usable = times is not None and times.notna().all()
            xs = times if usable else np.arange(len(self.frame))
            flags = [c for c in channels if binary_indicator(self.frame[c], c)]
            signals = [c for c in channels if c not in flags]
            groups = ([signals] if signals else []) + [[flag] for flag in flags]
            first_axes = None
            grid = self.data_figure.add_gridspec(len(groups), 1, height_ratios=[.55 if group[0] in flags else 1 for group in groups])
            for index, group in enumerate(groups):
                ax = style_axes(self.data_figure, position=(grid[index],), sharex=first_axes)
                if first_axes is None:
                    first_axes = ax
                for channel in group:
                    if channel in flags:
                        plot_states(ax, xs, self.frame[channel].to_numpy(dtype=float, na_value=np.nan), self._channel_colors[channel], label=str(channel))
                        ax.set_title(str(channel), loc="left", fontsize=10, fontweight="semibold", color="#243C57", pad=12)
                    else:
                        step = max(1, int(np.ceil(len(self.frame) / 20000)))
                        plot_signal(ax, xs.iloc[::step] if hasattr(xs, "iloc") else xs[::step],
                                    self.frame[channel].iloc[::step], self._channel_colors[channel], label=str(channel))
                        ax.set_ylabel(str(group[0]) if len(group) == 1 else "Sensor values (file units)")
                if len(group) > 1:
                    ax.legend(loc="upper right", ncols=min(3, len(group)), frameon=True, facecolor="white",
                              edgecolor="#E0E7EF", framealpha=.95, fontsize=9)
                if usable and pd.api.types.is_datetime64_any_dtype(times.dtype):
                    timezone = times.dt.tz
                    locator = dates.AutoDateLocator(tz=timezone)
                    ax.xaxis.set_major_locator(locator)
                    ax.xaxis.set_major_formatter(dates.ConciseDateFormatter(locator, tz=timezone))
                ax.set_xlabel(time_label if usable else "Sample position")
                ax.tick_params(axis="x", labelbottom=index == len(groups) - 1)
                ax.xaxis.label.set_visible(index == len(groups) - 1)
                ax.xaxis.offsetText.set_visible(index == len(groups) - 1)
        self.data_toolbar.refresh()
        self.data_canvas.draw_idle()

    def run_analysis(self):
        if self.worker is not None:
            return
        if self.frame is None:
            self.show_notice("Open a recording in Data before running an analysis.")
            self.navigate(0)
            return
        pipelines = self.selected_modules()
        if not pipelines:
            self.show_notice("Select an analysis module.")
            self.navigate(1)
            return
        try:
            mapping = validate_column_mapping(json.loads(self.mapping.toPlainText()))
            axes = (["x", "y", "z"] if self.prepared.isChecked() else
                    validate_orientation([v.strip() for v in self.orientation.text().split(",")]))
            settings = dict(pipelines=pipelines, watch_side=self.side.currentText(),
                            accelerometer_units=self.acc.currentText(), gyroscope_units=self.gyro.currentText(),
                            time_input_unit=self.time.currentText(), device_orientation=axes,
                            column_mapping=mapping, skip_preparation=self.prepared.isChecked(),
                            split_by_gaps=self.gaps.isChecked(), drop_missing_samples=self.drop_missing.isChecked(),
                            max_gap_seconds=self.max_gap.value(), min_segment_seconds=self.min_segment.value())
            if self.prepared.isChecked():
                settings.update(accelerometer_units="g", gyroscope_units="deg/s", time_input_unit="relative_s", split_by_gaps=False)
        except (ValueError, KeyError) as exc:
            self.failure(str(exc))
            return
        self.show_notice("")
        record = new_run(self.source, settings)
        if self.recordings:
            record["sources"] = dict(self.sources)
        record["paradigma_version"] = version("paradigma")
        frame = self.recordings if self.recordings else self.frame
        record["_frame"] = frame
        self.runs.insert(0, record)
        self.active_run = self.current_run = self.selected_run = record
        self.provenance = {"source": self.source, "paradigma_version": record["paradigma_version"], "settings": settings, "run_id": record["id"]}
        self.result_source_frame = frame
        self.result_timeline = None
        self.clear_results()
        self.log.clear()
        self.persist_run(record)
        self.refresh_runs()
        self.status.setText("Running ParaDigMa… Review progress in Runs.")
        self.navigate(1)
        if self.recordings:
            self.provenance["sources"] = dict(self.sources)
        self.start_job(lambda logger: analyze(frame, logger=logger, **settings), self.analyzed)

    def results_tab_changed(self, index):
        if index < 0:
            return
        body = self._result_view_layouts[index]
        # The tab bar stays outside every view's scrolling content. Shared
        # controls move below it rather than changing the navigation position.
        for widget in (self.results_header, self.detail_controls):
            for previous in self._result_view_layouts:
                previous.removeWidget(widget)
        body.insertWidget(0, self.results_header)
        body.insertWidget(1, self.detail_controls)
        self.figure_actions_layout.removeWidget(self.context_controls)
        self.table_actions_layout.removeWidget(self.context_controls)
        actions = self.figure_actions_layout if index == 1 else self.table_actions_layout
        actions.addWidget(self.context_controls, alignment=Qt.AlignRight)
        self.results_scroll = self._result_view_scrolls[index]
        aggregation = index == 2 and self.table_dataset.currentData() in self.aggregation_tables
        detailed = index in (1, 2) and not aggregation
        self.results_header.show()
        self.detail_controls.setVisible(index == 2 or index == 1 and self.filters_toggle.isChecked())
        self.filters_toggle.setVisible(detailed)
        self.filters_panel.setVisible(detailed and self.filters_toggle.isChecked())
        self.csv_button.setVisible(index in (1, 2))
        self.context_controls.setVisible(detailed)
        self.dataset_field.setVisible(index == 2)
        self.table_module_tabs.setVisible(index == 2)
        self.timing_toggle.setVisible(index == 2 and not aggregation)
        self.selection_note.setVisible(index == 2)
        self.csv_button.setEnabled(self.worker is None and self.selected_export_table()[1] is not None)

    def sync_table_outputs(self, force_detail=False):
        names = [*self.tables, *self.aggregation_tables]
        modules = list(dict.fromkeys([*MODULE_NAMES, *(name.split("/")[1] for name in names)]))
        available = {module: any(name.split("/")[1] == module for name in names) for module in modules}
        current = self.table_module_tabs.tabData(self.table_module_tabs.currentIndex())
        name = self.dataset.currentText()
        if force_detail and name in self.tables:
            current = name.split("/")[1]
            self._table_choices[current] = name
        if not available.get(current):
            current = next((module for module in modules if available[module]), modules[0])
        previous = self.table_module_tabs.blockSignals(True)
        if modules != [self.table_module_tabs.tabData(i) for i in range(self.table_module_tabs.count())]:
            while self.table_module_tabs.count():
                self.table_module_tabs.removeTab(0)
            for module in modules:
                index = self.table_module_tabs.addTab(MODULE_NAMES.get(module, module.replace("_", " ").title()))
                self.table_module_tabs.setTabData(index, module)
        for index, module in enumerate(modules):
            self.table_module_tabs.setTabEnabled(index, available[module])
        index = modules.index(current)
        self.table_module_tabs.setCurrentIndex(index)
        self.table_module_tabs.blockSignals(previous)
        self.table_module_changed(index)

    def table_module_changed(self, index):
        if index < 0:
            return
        module = self.table_module_tabs.tabData(index)
        tables = {**self.tables, **self.aggregation_tables}
        names = [name for name in tables if name.split("/")[1] == module]
        preferred = self._table_choices.get(module)
        if preferred not in names:
            preferred = next((name for name in names if name.startswith("quantifications/") and len(tables[name])),
                             names[0] if names else None)
        previous = self.table_dataset.blockSignals(True)
        self.table_dataset.clear()
        for name in names:
            self.table_dataset.addItem(output_label(name).partition(" · ")[2], name)
        if preferred in names:
            self.table_dataset.setCurrentIndex(self.table_dataset.findData(preferred))
        self.table_dataset.blockSignals(previous)
        self.select_output_table()

    def select_output_table(self, *_):
        name = self.table_dataset.currentData()
        module = self.table_module_tabs.tabData(self.table_module_tabs.currentIndex())
        self._table_choices[module] = name
        if name in self.aggregation_tables:
            self.aggregation_table.setModel(FrameModel(self.aggregation_tables[name]))
            self.table_stack.setCurrentIndex(1)
            self.selection_note.setText("Full-run aggregates")
        else:
            self.table_stack.setCurrentIndex(0)
            if name in self.tables and name != self.dataset.currentText():
                self.dataset.setCurrentText(name)
            elif name not in self.tables or self.active_frame is None:
                self.result_table.setModel(None)
                self.selection_note.setText("No tables available")
            else:
                self.update_detail_note()
        self.results_tab_changed(self.result_tabs.currentIndex())

    def table_timing_changed(self, _checked):
        row = self.result_table.currentIndex().row()
        self.refresh_detail_table()
        if row >= 0 and self.active_frame is not None and row < len(self.active_frame):
            self.result_table.setCurrentIndex(self.result_table.model().index(row, 0))
            self.result_table.selectRow(row)
        self.highlight_result_row()

    def selected_export_table(self):
        if self.result_tabs.currentIndex() == 2:
            name = self.table_dataset.currentData()
            if name in self.aggregation_tables:
                return name, self.aggregation_tables[name]
            if name not in self.tables:
                return name, None
        return self.dataset.currentText(), getattr(self, "display_frame", None)

    def build_result_overview(self):
        while self.overview_layout.count():
            item = self.overview_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.overview_values = {}
        self.overview_module_cards = {}
        results = self.results or {}
        if self.display_clock is not None:
            panel, content = card()
            content.addWidget(label("Recording", "sectionTitle"))
            stamp = clock_origin(self.display_clock)
            timezone = self.display_clock.get("timezone") or "timezone unspecified"
            content.addWidget(label(f"Analysis time zero: {stamp.strftime('%d %b %Y, %H:%M:%S')} ({timezone})", "muted"))
            content.addWidget(label(f"Clock source: {self.display_clock['source']}", "muted"))
            self.overview_layout.addWidget(panel)
        modules = list(dict.fromkeys([*results.get("aggregations", {}), *results.get("metadata", {}),
                                     *results.get("quantifications", {}), *results.get("classifications", {})]))
        modules = [name for name in modules if name != "desktop_preparation"]
        if not modules:
            self.overview_layout.addWidget(label("Run an analysis to see module aggregates.", "muted"))
        for module in modules:
            panel, content = card()
            panel.setProperty("analysisModule", module)
            self.overview_module_cards[module] = panel
            heading = label(MODULE_NAMES.get(module, module.replace("_", " ").title()), "pageTitle")
            heading.setProperty("analysisModule", module)
            content.addWidget(heading)
            for error in results.get("errors", []):
                if isinstance(error, dict) and (error.get("pipeline") == module or module in error.get("pipelines", [])):
                    content.addWidget(label(str(error.get("error", "Processing failed")), "notice"))
            groups = [("Aggregates", list(flat_values(results.get("aggregations", {}).get(module, {}))))]
            metadata = results.get("metadata", {}).get(module, {})
            groups.append(("Metadata", list(flat_values(metadata))))
            if module == "gait":
                for branch, summary in segment_summary(metadata).items():
                    groups.append((f"{branch.title()} gait segments", list(flat_values(summary))))
            for heading, entries in groups:
                if not entries:
                    if heading == "Aggregates":
                        content.addWidget(label("No aggregates returned for this module.", "muted"))
                    continue
                content.addWidget(label(heading, "sectionTitle"))
                grid = QGridLayout()
                grid.setSpacing(10)
                for index, (path, value) in enumerate(entries):
                    box, inside = card()
                    title = " · ".join(readable_key(part) for part in path) or "Value"
                    box.setToolTip(" / ".join(path))
                    if module == "tremor" and path == ("perc_windows_tremor",):
                        box.setToolTip("Checked tremor-positive windows ÷ resting/stable windows × 100. "
                                       "This full-run aggregate is not recalculated by graph/table time filters.")
                    inside.addWidget(label(title, "muted"))
                    if value is None or isinstance(value, (float, np.floating)) and not np.isfinite(value):
                        text = "—"
                    elif isinstance(value, (float, np.floating)):
                        text = f"{value:.5g}"
                    else:
                        text = str(value)
                    display = label(text, "metricValue")
                    display.setToolTip(str(value))
                    inside.addWidget(display)
                    self.overview_values[(module, heading, path)] = display
                    grid.addWidget(box, index // 3, index % 3)
                content.addLayout(grid)
            self.overview_layout.addWidget(panel)
        preparation = results.get("metadata", {}).get("desktop_preparation", {})
        if preparation:
            panel, content = card()
            content.addWidget(label("Input preparation", "sectionTitle"))
            for path, value in flat_values(preparation):
                if "by_recording" in path:
                    continue
                content.addWidget(label(f"{' · '.join(path).replace('_', ' ')}: {value}", "muted"))
            self.overview_layout.addWidget(panel)
        self.overview_layout.addStretch()

    def populate_result_series(self):
        self.result_series.blockSignals(True)
        self.result_series.clear()
        self._series_items = {}
        roots, default_modules = {}, set()
        for name, frame in self._plot_tables.items():
            module = name.split("/")[1]
            if module not in roots:
                root = QTreeWidgetItem(self.result_series, [MODULE_NAMES.get(module, module.title())])
                root.setForeground(0, QColor(module_color(module)))
                root.setExpanded(True)
                roots[module] = root
            stage = QTreeWidgetItem(roots[module], [output_label(name).split(" · ", 1)[-1]])
            stage.setExpanded(name.startswith("quantifications/") and len(frame) > 0)
            metrics = plot_metrics(name, frame)
            default = preferred_metric(name, frame)
            # Favor unfiltered gait and quantified outputs for initial plots.
            choose = (len(frame) > 0 and name.startswith("quantifications/") and module not in default_modules
                      and (not name.endswith("/filtered") or not len(self.tables.get("quantifications/gait/unfiltered", []))))
            for metric in metrics:
                title = self._plot_labels.get((name, metric), str(metric).replace("_", " "))
                item = QTreeWidgetItem(stage, [title])
                item.setData(0, Qt.UserRole, (name, metric))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if choose and metric == default else Qt.Unchecked)
                item.setToolTip(0, f"{name}\n{metric}" if (name, metric) not in self._plot_labels else
                                title + "\nDerived from each window probability using the bundled model threshold; not the final merged sample labels.")
                self._series_items[(name, metric)] = item
            if choose and default is not None:
                default_modules.add(module)
        self.result_series.blockSignals(False)

    def selected_result_series(self):
        return [key for key, item in self._series_items.items() if item.checkState(0) == Qt.Checked]

    def select_plot_series(self, item, previous=None):
        key = item.data(0, Qt.UserRole) if item is not None else None
        if key is None:
            return
        name, metric = key
        self.dataset.setCurrentText(name)
        self.y_column.blockSignals(True)
        self.y_column.setCurrentIndex(self.y_column.findData(metric))
        self.y_column.blockSignals(False)

    def analyzed(self, results):
        self.results = results
        if self.current_run is None:
            self.result_source_frame = self.recordings if self.recordings else self.frame
        settings = self.provenance.get("settings", {})
        batch_clock = None
        self._recording_bases = {}
        if isinstance(self.result_source_frame, dict):
            self.result_timeline, self._source_timelines, self._display_offsets, batch_clock, self._recording_bases = align_recordings(
                self.result_source_frame, settings, results)
        else:
            self.result_timeline, self._source_timelines, self._display_offsets = analysis_alignment(
                self.result_source_frame, settings, results, self.provenance.get("display_offsets"))
        if self._display_offsets:
            self.provenance["display_offsets"] = dict(self._display_offsets)
        self.display_clock = None
        if self.provenance.get("display_clock"):
            try:
                self.display_clock = normalise_clock(self.provenance["display_clock"])
            except (ValueError, TypeError, KeyError, OverflowError):
                self.append_log("Stored recording clock is invalid; using available recording timing.")
                self.provenance.pop("display_clock", None)
        if self.display_clock is None:
            self.display_clock = (batch_clock if isinstance(self.result_source_frame, dict) else
                                  recording_clock(self.result_source_frame, settings, self.result_timeline))
        if self.display_clock is not None:
            self.provenance["display_clock"] = dict(self.display_clock)
        if self.active_run is not None:
            self.active_run["_results"] = results
            self.active_run["_provenance"] = dict(self.provenance)
        self.clock_input.set_clock(self.display_clock)
        self.clock_input.setText(self.display_clock["origin"] if self.display_clock else "")
        self.time_from.set_clock(self.display_clock)
        self.time_to.set_clock(self.display_clock)
        self.time_from.clear()
        self.time_to.clear()
        self._detail_selections = {}
        self.tables = detail_tables(results)
        self._plot_tables, self._plot_labels = plot_tables(self.tables)
        self.aggregation_tables = aggregation_tables(results)
        self._timings = {name: detail_timing(results, name, frame) for name, frame in self.tables.items()}
        for name, timing in self._timings.items():
            timing["Timeline time (s)"] = timing["Analysis time (s)"] + timeline_offsets(name, self.tables[name], self._display_offsets)
        self._interval_ends = {name: binary_interval_ends(name, self.tables[name], timing["Timeline time (s)"])
                               for name, timing in self._timings.items()}
        sources = self.provenance.get("sources", {})
        self.results_source.setText(f"{len(sources)} recordings · One subject" if len(sources) > 1 else
                                    Path(self.provenance.get("source", self.source)).name or "Current analysis")
        self.build_result_overview()
        self.populate_result_series()
        times = np.concatenate([t["Timeline time (s)"].to_numpy() for t in self._timings.values()]) if self._timings else np.array([])
        finite = times[np.isfinite(times)]
        if len(finite):
            self.time_from.set_default(float(finite.min()))
            self.time_to.set_default(float(finite.max()))
        self.dataset.blockSignals(True)
        self.dataset.clear()
        self.dataset.addItems(self.tables)
        preferred = next((name for name, _ in self.selected_result_series() if name.startswith("quantifications/")), None)
        if preferred is None:
            preferred = next((name for name, frame in self.tables.items()
                              if name.startswith("quantifications/") and len(frame)), None)
        if preferred:
            self.dataset.setCurrentText(preferred)
        self.dataset.blockSignals(False)
        self.select_dataset(self.dataset.currentText())
        self.sync_table_outputs()
        self.export_button.setEnabled(self.worker is None)
        errors = results.get("errors", [])
        if errors:
            self.append_log(json.dumps(errors, indent=2, default=str))
            count = len(merge_errors(self.active_run["errors"] if self.active_run else [], errors))
            message = f"Analysis returned {count} processing error(s); inspect Runs and the partial results."
            self.status.setText(message)
            self.show_notice(message, "error")
            self.finish_run("Partial", errors)
        else:
            has_rows = any(len(v) for k, v in self.tables.items() if k.startswith("quantifications/"))
            message = "Analysis completed." if has_rows else "No quantified windows. See Runs for details."
            if not has_rows:
                self.capture_warning(message)
            record = self.active_run or self.current_run
            warnings = len(record["warnings"]) if record else 0
            logged_errors = len(record.get("errors", [])) if record else 0
            if logged_errors:
                message = f"Analysis returned {logged_errors} processing error(s); inspect Runs and the partial results."
                self.show_notice(message, "error")
            elif warnings and has_rows:
                message = f"Analysis completed with {warnings} warning(s). See Runs."
                self.show_notice(message)
            elif not has_rows:
                self.show_notice(message)
            self.status.setText(message)
            self.finish_run("Completed")
        self.result_tabs.setCurrentIndex(0)
        self.navigate(2)

    def select_dataset(self, name):
        frame = self.tables.get(name)
        self.hide_sensor_context()
        self.context_button.setEnabled(False)
        self.context_button.setToolTip("Select a result row or click a graph point" if self.result_source_frame is not None else "Original sensor data unavailable")
        self.y_column.blockSignals(True)
        self.y_column.clear()
        if frame is not None:
            plot_frame = self._plot_tables[name]
            for column in plot_metrics(name, plot_frame):
                self.y_column.addItem(str(column), column)
            preferred = next((metric for dataset, metric in self.selected_result_series() if dataset == name),
                             preferred_metric(name, plot_frame))
            if preferred is not None:
                self.y_column.setCurrentIndex(self.y_column.findData(preferred))
        self.y_column.blockSignals(False)
        self.apply_filters()
        self.sync_table_outputs(force_detail=True)
        if self.result_tabs.currentIndex() != 1 and not any(dataset == name for dataset, metric in self.selected_result_series()):
            item = self._series_items.get((name, self.y_column.currentData()))
            if item is not None:
                item.setCheckState(0, Qt.Checked)

    def apply_filters(self, *_):
        name = self.dataset.currentText()
        try:
            clock = self.display_clock
            entered = self.clock_input.text().strip()
            if entered:
                candidate = normalise_clock({"origin": entered, "source": "User supplied",
                    "timezone": clock.get("timezone") if clock else None})
                if clock is None or pd.Timestamp(clock["origin"]) != pd.Timestamp(candidate["origin"]):
                    clock = candidate
            else:
                clock = None
            # Removing the origin keeps the selected interval in elapsed seconds.
            bound_clock = clock if clock is not None else self.display_clock
            low, high = time_bound(self.time_from.text(), bound_clock), time_bound(self.time_to.text(), bound_clock)
            if low is not None and high is not None and low > high:
                raise ValueError("The time minimum cannot exceed the maximum.")
            selections = {}
            for key, frame in self.tables.items():
                times = self._timings[key]["Timeline time (s)"].to_numpy()
                mask = np.ones(len(frame), dtype=bool)
                if low is not None:
                    mask &= times >= low
                if high is not None:
                    mask &= times <= high
                positions = np.flatnonzero(mask)
                selections[key] = frame.iloc[positions], positions
        except (ValueError, TypeError, OverflowError) as exc:
            self.filter_status.setText(str(exc))
            self.filter_status.show()
            return
        clock_changed = clock != self.display_clock
        self.display_clock = clock
        if clock is not None:
            self.provenance["display_clock"] = dict(clock)
        else:
            self.provenance.pop("display_clock", None)
        if self.current_run is not None:
            self.current_run["_provenance"] = dict(self.provenance)
        if clock_changed:
            self.build_result_overview()
        self.clock_input.set_clock(clock)
        for control in (self.time_from, self.time_to):
            control.set_clock(clock)
        self.time_zone.setText("Calendar times: " + (clock.get("timezone") or "timezone unspecified") if clock
                              else "Elapsed seconds · Set a recording time origin to use calendar dates")
        self._detail_selections = selections
        self.active_frame, self.active_positions = selections.get(name, (None, np.array([], dtype=int)))
        self.active_selection = {"time_from": self.time_from.text(), "time_to": self.time_to.text()}
        self.refresh_detail_table()
        self.filter_status.clear()
        self.filter_status.hide()
        self.plot()

    def refresh_detail_table(self):
        self.context_button.setEnabled(False)
        self.context_button.setToolTip("Select a result row or click a graph point" if self.result_source_frame is not None else "Original sensor data unavailable")
        frame = self.active_frame
        if frame is None:
            self.display_frame = None
            self.result_table.setModel(None)
            self.csv_button.setEnabled(False)
            self.selection_note.setText("No detailed outputs returned.")
            return
        name = self.dataset.currentText()
        view = frame.copy()
        if self.timing_toggle.isChecked():
            timing = self._timings[name].iloc[self.active_positions]
            fields = {"Analysis time (s)": timing["Analysis time (s)"].to_numpy(),
                      "Time basis": timing["Time basis"].to_numpy()}
            if any(offset != 0. for offset in self._display_offsets.values()):
                fields = {"Timeline time (s)": timing["Timeline time (s)"].to_numpy(), **fields}
            if self.display_clock is not None:
                fields = {"Recording date/time": clock_times(timing["Timeline time (s)"].to_numpy(), self.display_clock), **fields}
            if name.startswith("quantifications/gait/"):
                fields.update({"Segment start (s)": timing["Segment start (s)"].to_numpy(),
                               "Segment end (s)": timing["Segment end (s)"].to_numpy()})
            for key, values in reversed(list(fields.items())):
                field_name = key if key not in view else f"Display · {key}"
                view.insert(0, field_name, values)
        self.display_frame = view
        self.result_table.setModel(FrameModel(view))
        self.result_table.selectionModel().currentRowChanged.connect(self.result_row_changed)
        self.csv_button.setEnabled(self.worker is None and self.selected_export_table()[1] is not None)
        self.update_detail_note()

    def update_detail_note(self):
        name, frame = self.dataset.currentText(), self.active_frame
        if frame is None:
            return
        clock_note = (f"Recording time ({self.display_clock.get('timezone') or 'timezone unspecified'})"
                      if self.display_clock else "Elapsed time · Set a time origin in Filters to display dates")
        if self.display_clock is None and len(self.provenance.get("sources", {})) > 1:
            clock_note = "File-order timeline · Recording clocks unavailable"
        estimated = name.startswith("quantifications/gait/") and "time" not in frame
        self.selection_note.setText(f"{len(frame):,} / {len(self.tables[name]):,} rows · {clock_note}"
                                    + (" · Gait positions estimated within segments" if estimated else ""))
        if not self.timing_toggle.isChecked():
            self.selection_note.setText(f"{len(frame):,} / {len(self.tables[name]):,} rows")
        if self.table_dataset.currentData() in self.aggregation_tables:
            self.selection_note.setText("Full-run aggregates")

    def reset_filters(self):
        self.time_from.clear()
        self.time_to.clear()
        self.apply_filters()

    def update_metric(self, *_):
        key = self.dataset.currentText(), self.y_column.currentData()
        item = self._series_items.get(key)
        if item is not None:
            self.result_series.blockSignals(True)
            # Changing the active metric replaces its prior default series.
            for previous, candidate in self._series_items.items():
                if previous[0] == key[0]:
                    candidate.setCheckState(0, Qt.Checked if previous == key else Qt.Unchecked)
            self.result_series.blockSignals(False)
        self.plot()

    def plot(self, *_):
        self.figure.clear()
        self._result_selection_artists = []
        chosen = self.selected_result_series()
        binaries = [binary_indicator(self._plot_tables[name][metric], metric) for name, metric in chosen]
        compact_states = bool(binaries) and all(binaries)
        height = max(140 if compact_states else 220, sum(105 if binary else 190 for binary in binaries))
        self.canvas.setMinimumHeight(height)
        self.canvas.setMaximumHeight(height if compact_states else 16777215)
        self.graphs_workspace.setMinimumHeight(280 if binaries and all(binaries) else 310)
        if not chosen:
            ax = style_axes(self.figure)
            ax.text(.5, .5, "Select detailed metrics to plot", ha="center", transform=ax.transAxes, color="#68778c")
        first_axes = None
        grid = self.figure.add_gridspec(len(chosen), 1, height_ratios=[.55 if binary else 1 for binary in binaries]) if chosen else None
        for index, (name, metric) in enumerate(chosen):
            ax = style_axes(self.figure, position=(grid[index],), sharex=first_axes)
            if first_axes is None:
                first_axes = ax
            ax._paradigma_dataset = name
            ax._paradigma_metric = metric
            selected, positions = self._detail_selections.get(name, (self.tables[name].iloc[:0], np.array([], dtype=int)))
            times = self._timings[name]["Timeline time (s)"].to_numpy()[positions]
            binary = binary_indicator(self._plot_tables[name][metric], metric)
            step = 1 if binary else max(1, int(np.ceil(len(selected) / 20000)))
            sample = selected.iloc[::step]
            xs = clock_times(times[::step], self.display_clock)
            ys = self._plot_tables[name][metric].iloc[positions[::step]].to_numpy(dtype=float, na_value=np.nan)
            estimated = name.startswith("quantifications/gait/") and "time" not in sample
            participant_column = next((c for c in PARTICIPANT_COLUMNS if c in sample), None)
            points_only = estimated or participant_column is not None and sample[participant_column].nunique() > 1
            if self.display_clock is not None:
                xs = np.asarray(dates.date2num(xs.to_pydatetime()), dtype=float)
            else:
                xs = np.asarray(xs, dtype=float)
            if "file_key" in sample and not points_only and not binary:
                boundaries = np.flatnonzero(sample.file_key.ne(sample.file_key.shift()).fillna(True).to_numpy(dtype=bool))[1:]
                xs, ys = np.insert(xs, boundaries, np.nan), np.insert(ys, boundaries, np.nan)
            if len(sample) and np.isfinite(xs).any():
                color = module_color(name.split("/")[1])
                if binary:
                    stops = self._interval_ends[name][positions]
                    until = time_bound(self.active_selection.get("time_to", ""), self.display_clock)
                    if until is not None:
                        stops = np.minimum(stops, until)
                    stops = clock_times(stops, self.display_clock)
                    plot_states(ax, xs, ys, color, ends=stops)
                    counts = tremor_window_counts(selected) if metric == "pred_tremor_checked" else None
                    if counts is not None:
                        numerator, denominator, percentage = counts
                        text = f"{numerator:,} / {denominator:,} resting windows"
                        text += f" · {percentage:.2f}%" if percentage is not None else " · No resting windows"
                        ax.text(.01, .95, text + " · Selection", transform=ax.transAxes, va="top",
                                fontsize=8.5, color="#465B73")
                else:
                    plot_signal(ax, xs, ys, color, points_only=points_only, sparse=len(sample) < 120)
            else:
                ax.text(.5, .5, "No timed rows in the current selection", ha="center", transform=ax.transAxes, color="#68778c")
            if not binary:
                ax.set_ylabel(str(metric).replace("_", " "), fontsize=9)
            metric_title = self._plot_labels.get((name, metric), str(metric).replace("_", " ").capitalize())
            ax.set_title(output_label(name) + "  ·  " + metric_title + (" · Estimated positions" if estimated else ""),
                         fontsize=10, fontweight="semibold", color="#243C57", pad=13, loc="left")
            if self.display_clock is not None:
                timezone = clock_origin(self.display_clock).tz
                locator = dates.AutoDateLocator(tz=timezone)
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(dates.ConciseDateFormatter(locator, tz=timezone))
                ax.set_xlabel(f"Recording date/time ({self.display_clock.get('timezone') or 'timezone unspecified'})")
                ax.format_xdata = lambda value, tz=timezone: dates.num2date(value, tz=tz).strftime("%d %b %Y %H:%M:%S")
            else:
                ax.set_xlabel("File-order timeline (s)" if len(self.provenance.get("sources", {})) > 1 else "Elapsed analysis time (s)")
            ax.tick_params(axis="x", labelbottom=False)
            ax.xaxis.label.set_visible(False)
            ax.xaxis.offsetText.set_visible(False)
        self.time_axis.bind(first_axes)
        self.plot_toolbar.refresh()
        self.highlight_result_row()
        self.canvas.draw_idle()

    def result_row_changed(self, current, previous):
        frame = self.active_frame
        valid_row = current.isValid() and frame is not None
        timestamp = (valid_row and "time" in frame and pd.api.types.is_numeric_dtype(frame["time"].dtype)
                     and pd.notna(frame["time"].iloc[current.row()]) and np.isfinite(frame["time"].iloc[current.row()]))
        segment = gait_context(self.results, self.dataset.currentText(), frame.iloc[current.row()]) if valid_row else None
        usable = self.result_source_frame is not None and (timestamp or segment is not None)
        self.context_button.setEnabled(bool(usable))
        self.context_radius.setEnabled(bool(timestamp))
        self.context_button.setText("Inspect gait segment" if segment is not None and not timestamp else "Inspect sensor context")
        if valid_row:
            self.context_button.setToolTip("Inspect original samples for the selected result row")
        if valid_row and not timestamp and segment is None:
            self.context_button.setToolTip("No sensor timing available")
        if self.result_source_frame is None:
            self.context_button.setToolTip("Original sensor data unavailable")
        self.highlight_result_row()

    def highlight_result_row(self):
        """Link a table row to all plots without changing their data or limits."""
        for artist in self._result_selection_artists:
            artist.remove()
        self._result_selection_artists = []
        self.time_axis.set_selection(None)
        name, frame = self.dataset.currentText(), self.active_frame
        current = self.result_table.currentIndex()
        if frame is None or not current.isValid() or name not in self._timings:
            self.canvas.draw_idle()
            return
        row = current.row()
        position = self.active_positions[row]
        timing = self._timings[name].iloc[position]
        seconds = float(timing["Timeline time (s)"])
        if not np.isfinite(seconds):
            self.canvas.draw_idle()
            return
        if self.display_clock is not None:
            timestamp = clock_times([seconds], self.display_clock)[0]
            x = float(dates.date2num(timestamp.to_pydatetime(warn=False)))
            label = timestamp.strftime("%d %b %Y %H:%M:%S.%f").rstrip("0").rstrip(".")
        else:
            x, label = seconds, f"{seconds:.6g} s"
        estimated = "Estimated" in str(timing["Time basis"])
        label = f"Row {row + 1} · {label}" + (" · Estimated" if estimated else "")
        self.time_axis.set_selection(x, label)
        for ax in self.figure.axes:
            if not hasattr(ax, "_paradigma_dataset"):
                continue
            line = Line2D([x, x], [0, 1], transform=ax.get_xaxis_transform(),
                          color="#465B73", linewidth=1.1, linestyle=(0, (3, 3)), alpha=.75, zorder=7)
            line.set_gid("selected-result-time")
            ax.add_artist(line)
            self._result_selection_artists.append(line)
            if ax._paradigma_dataset != name:
                continue
            value = self._plot_tables[name][ax._paradigma_metric].iloc[self.active_positions[row]]
            if (pd.isna(value) or not np.isfinite(float(value))
                    or getattr(ax, "_paradigma_binary", False) and float(value) != 1.):
                continue
            point = Line2D([x], [float(value)], linestyle="none", marker="o", markersize=9,
                           markerfacecolor="white", markeredgecolor=module_color(name.split("/")[1]),
                           markeredgewidth=2, zorder=8)
            point.set_gid("selected-result-point")
            ax.add_artist(point)
            self._result_selection_artists.append(point)
        self.canvas.draw_idle()

    def graph_clicked(self, event):
        if event.inaxes is None or event.xdata is None or self.plot_toolbar.mode:
            return
        name = getattr(event.inaxes, "_paradigma_dataset", self.dataset.currentText())
        if name not in self.tables:
            return
        anchor = float(event.xdata)
        if self.display_clock is not None:
            anchor = (anchor - dates.date2num(pd.Timestamp(self.display_clock["origin"])))*86400
        self.dataset.setCurrentText(name)
        self.sync_table_outputs(force_detail=True)
        metric = getattr(event.inaxes, "_paradigma_metric", None)
        if metric is not None:
            self.y_column.blockSignals(True)
            self.y_column.setCurrentIndex(self.y_column.findData(metric))
            self.y_column.blockSignals(False)
        frame = self.active_frame
        if frame is None or frame.empty:
            return
        times = self._timings[name]["Timeline time (s)"].to_numpy()[self.active_positions]
        distances = np.abs(times - anchor)
        finite = np.isfinite(distances)
        if not finite.any():
            return
        row = int(np.argmin(np.where(finite, distances, np.inf)))
        if getattr(event.inaxes, "_paradigma_binary", False) and metric in self._plot_tables[name]:
            ends = self._interval_ends[name][self.active_positions]
            present = self._plot_tables[name][metric].iloc[self.active_positions].eq(1).fillna(False).to_numpy(dtype=bool)
            covering = np.flatnonzero(present & (times <= anchor) & (anchor < ends))
            if len(covering):
                row = int(covering[-1])
        self.result_table.setCurrentIndex(self.result_table.model().index(row, 0))
        self.result_table.selectRow(row)
        self.result_table.scrollTo(self.result_table.currentIndex())
        self.plot_toolbar.active_axes = next((ax for ax in self.figure.axes
            if getattr(ax, "_paradigma_dataset", None) == name and getattr(ax, "_paradigma_metric", None) == metric), None)
        if self.plot_toolbar.settings_action.isChecked():
            self.plot_toolbar.settings.read_axes()

    def inspect_sensor_context(self):
        row = self.result_table.currentIndex().row()
        if not self.context_button.isEnabled() or row < 0:
            return
        try:
            selected = self.active_frame.iloc[row]
            parts = self.dataset.currentText().split("/")
            module = parts[1] if len(parts) > 1 else ""
            source_frame = self.result_source_frame
            if isinstance(source_frame, dict):
                key = source_key(selected.get("file_key"), self.results)
                source_frame = source_frame[key]
                common = self.result_timeline[key]
                module_timeline = self._source_timelines.get(module, {}).get(key, common)
                display_timeline = common + self._recording_bases[key]
            else:
                if self.result_timeline is None:
                    self.result_timeline = source_timeline(source_frame, self.provenance.get("settings", {}))
                module_timeline = self._source_timelines.get(module, self.result_timeline)
                display_timeline = self.result_timeline
            segment = gait_context(self.results, self.dataset.currentText(), selected)
            if "time" in selected and pd.notna(selected["time"]):
                anchor = float(selected["time"])
                radius = self.context_radius.value()
                mask = np.isfinite(module_timeline) & (np.abs(module_timeline - anchor) <= radius)
                description = f"near {anchor:.4g} s (±{radius:g} s). This is timestamp context, not the algorithm's exact window."
            elif segment is not None:
                start, end, number = segment
                mask = np.isfinite(module_timeline) & (module_timeline >= start) & (module_timeline < end)
                description = f"from gait segment {number}, {start:.4g}–{end:.4g} s, using toolbox metadata. Individual arm-swing timestamps are not provided."
            else:
                raise ValueError("No explicit sensor time context is available.")
            self.sensor_frame = source_frame.iloc[np.flatnonzero(mask)]
            self.sensor_times = display_timeline[mask]
            self.sensor_table.setModel(FrameModel(self.sensor_frame))
            self.sensor_channel.blockSignals(True)
            self.sensor_channel.clear()
            mapping = self.provenance.get("settings", {}).get("column_mapping", {})
            for column in self.sensor_frame.select_dtypes(include="number").columns:
                if mapping.get(column, column) != "time":
                    self.sensor_channel.addItem(str(column), column)
            self.sensor_channel.blockSignals(False)
            self.sensor_note.setText(f"{len(self.sensor_frame):,} original samples {description} Original units; horizontal axis aligned to analysis time.")
            if isinstance(self.result_source_frame, dict):
                path = self.provenance.get("sources", {}).get(key, key)
                self.sensor_note.setText(f"{Path(path).name} · " + self.sensor_note.text())
            self.plot_sensor()
            self.result_tabs.setTabVisible(self.sensor_tab_index, True)
            self.result_tabs.setCurrentIndex(self.sensor_tab_index)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            message = f"Sensor context unavailable: {exc}"
            self.context_button.setToolTip(message)
            self.status.setText(message)

    def hide_sensor_context(self):
        if self.result_tabs.currentIndex() == self.sensor_tab_index:
            self.result_tabs.setCurrentIndex(1)
        self.result_tabs.setTabVisible(self.sensor_tab_index, False)

    def plot_sensor(self, *_):
        self.sensor_figure.clear()
        ax = style_axes(self.sensor_figure)
        column = self.sensor_channel.currentData()
        if self.sensor_frame is not None and column in self.sensor_frame and len(self.sensor_frame):
            module = self.dataset.currentText().split("/")[1]
            color = module_color(module)
            step = max(1, int(np.ceil(len(self.sensor_frame) / 20000)))
            xs = clock_times(self.sensor_times[::step], self.display_clock)
            if binary_indicator(self.sensor_frame[column], column):
                plot_states(ax, clock_times(self.sensor_times, self.display_clock), self.sensor_frame[column].to_numpy(dtype=float, na_value=np.nan), color)
                ax.set_title(str(column), loc="left", fontsize=10, fontweight="semibold", color="#243C57", pad=12)
            else:
                plot_signal(ax, xs, self.sensor_frame[column].iloc[::step], color)
            if self.display_clock is not None:
                timezone = clock_origin(self.display_clock).tz
                locator = dates.AutoDateLocator(tz=timezone)
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(dates.ConciseDateFormatter(locator, tz=timezone))
                ax.set_xlabel("Recording date/time")
            else:
                ax.set_xlabel("Analysis time (s)")
            if not getattr(ax, "_paradigma_binary", False):
                ax.set_ylabel(str(column))
        else:
            ax.text(.5, .5, "No original samples in this context", ha="center", transform=ax.transAxes)
        self.sensor_toolbar.refresh()
        self.sensor_canvas.draw_idle()

    def refresh_runs(self):
        data = pd.DataFrame([{"Started": datetime.fromisoformat(record["started"]).astimezone().strftime("%d %b %Y · %H:%M"), "Status": run_status(record),
            "Input": (f"{len(record['sources'])} recordings" if len(record.get("sources", {})) > 1 else Path(record["source"]).name), "Modules": ", ".join(record["settings"].get("pipelines", [])),
            "Warnings": len(record["warnings"]), "Errors": len(record.get("errors", [])), "Exports": len(record["outputs"])} for record in self.runs],
            columns=["Started", "Status", "Input", "Modules", "Warnings", "Errors", "Exports"])
        self.run_table.setModel(FrameModel(data))
        self.run_table.setColumnWidth(0, 176)
        self.run_table.setColumnWidth(2, 170)
        self.run_table.selectionModel().currentRowChanged.connect(self.select_run)
        if self.runs:
            index = next((i for i, record in enumerate(self.runs) if record is self.selected_run), 0)
            self.run_table.setCurrentIndex(self.run_table.model().index(index, 0))
            self.run_table.selectRow(index)
        else:
            self.selected_run = None
        self.update_run_actions()

    def select_run(self, current, previous):
        if not current.isValid() or current.row() >= len(self.runs):
            return
        record = self.runs[current.row()]
        self.selected_run = record
        self.run_heading.setText(f"{run_status(record)} · " + (f"{len(record['sources'])} recordings" if len(record.get("sources", {})) > 1 else Path(record["source"]).name))
        self.run_heading.setToolTip(f"Run ID: {record['id']}")
        self.run_summary.setText(self.run_summary_text(record))
        self.run_details.setPlainText("\n".join(f"{key.replace('_', ' ').capitalize()}: {json.dumps(value, ensure_ascii=False)}" for key, value in record["settings"].items()))
        self.run_warnings.setPlainText("\n\n".join(str(value) for value in record["warnings"]) or "No recorded warnings.")
        self.run_errors.setPlainText("\n\n".join(record.get("errors", [])) or "No recorded errors.")
        self.run_outputs.setPlainText("\n\n".join(f"{item.get('kind', 'Export')}: {item.get('path', '')}" for item in record["outputs"]) or "No exports saved.")
        self.log.setPlainText(record.get("log", ""))
        self.update_run_actions()

    @staticmethod
    def run_summary_text(record):
        started = datetime.fromisoformat(record["started"]).astimezone().strftime("%d %b %Y, %H:%M:%S")
        finished = datetime.fromisoformat(record["finished"]).astimezone().strftime("%H:%M:%S") if record.get("finished") else "—"
        return (f"{started} – {finished} · ParaDigMa {record.get('paradigma_version', '—')} · "
                f"{len(record['warnings'])} warning(s), {len(record.get('errors', []))} error(s)\n{chr(10).join(record.get('sources', {}).values()) or record['source']}")

    def update_run_actions(self):
        record = self.selected_run
        available = record is not None and ("_results" in record or any(item.get("kind") == "JSON" for item in record["outputs"]))
        self.open_run_button.setEnabled(bool(available) and self.worker is None)
        self.use_parameters_button.setEnabled(record is not None and self.worker is None)

    def open_run(self):
        record = self.selected_run
        if record is None or self.worker is not None:
            return
        if "_results" in record:
            self.restore_run((record["id"], record.get("_provenance", {}), record["_results"]))
            return
        output = next((item for item in reversed(record["outputs"]) if item.get("kind") == "JSON"), None)
        if output:
            self.status.setText("Opening exported results…")
            self.start_job(lambda logger: (record["id"], *load_result_export(output["path"])), self.restore_run)

    def restore_run(self, payload):
        run_id, provenance, results = payload
        record = next(record for record in self.runs if record["id"] == run_id)
        self.current_run = record
        self.provenance = provenance or {"source": record["source"], "settings": record["settings"], "paradigma_version": record["paradigma_version"], "sources": record.get("sources", {})}
        self.result_source_frame = record.get("_frame")
        self.result_timeline = None
        record["_results"], record["_provenance"] = results, self.provenance
        self.show_notice("")
        self.analyzed(results)
        self.update_run_actions()

    def use_run_parameters(self):
        if self.selected_run is None or self.worker is not None:
            return
        settings = self.selected_run["settings"]
        self.set_modules(settings.get("pipelines", ["gait"]))
        for widget, key in ((self.side, "watch_side"), (self.acc, "accelerometer_units"), (self.gyro, "gyroscope_units"), (self.time, "time_input_unit")):
            if key in settings:
                widget.setCurrentText(str(settings[key]))
        self.orientation.setText(",".join(settings.get("device_orientation") or ["x", "y", "z"]))
        self.mapping.setPlainText(json.dumps(settings.get("column_mapping", {})))
        self.prepared.setChecked(settings.get("skip_preparation", False))
        self.gaps.setChecked(settings.get("split_by_gaps", False))
        self.drop_missing.setChecked(settings.get("drop_missing_samples", False))
        self.max_gap.setValue(settings.get("max_gap_seconds", DEFAULT_MAX_GAP_SECONDS) or DEFAULT_MAX_GAP_SECONDS)
        self.min_segment.setValue(settings.get("min_segment_seconds", DEFAULT_MIN_SECTION_SECONDS) or DEFAULT_MIN_SECTION_SECONDS)
        self.preparation_changed()
        self.navigate(1)
        self.status.setText("Run parameters restored. Check the selected input before running.")

    def record_output(self, path, kind):
        if self.current_run is not None:
            name, frame = self.selected_export_table()
            self.current_run["outputs"].append({"kind": kind, "path": str(Path(path).resolve()), "saved": now(), "dataset": name if kind == "CSV" else "all results"})
            if kind == "CSV":
                aggregation = name.startswith("aggregations/")
                self.current_run["outputs"][-1].update(selected_rows=len(frame),
                    selection={"scope": "Full run"} if aggregation else self.active_selection)
            self.persist_run(self.current_run)
            self.refresh_runs()

    def export(self):
        if self.results is None or self.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export complete results", "paradigma-results.json", "JSON (*.json)")
        if path:
            try:
                export_results(path, self.results, self.provenance, protected_sources=[*self.sources.values(), *self.provenance.get("sources", {}).values()])
                self.record_output(path, "JSON")
                self.status.setText(f"Results exported to {path}")
            except Exception as exc:
                self.failure(str(exc))

    def export_csv(self):
        name, frame = self.selected_export_table()
        if frame is None or self.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export selected rows", "output.csv", "CSV (*.csv)")
        if path:
            try:
                export_table_csv(path, frame, source=self.provenance.get("source", self.source), protected_sources=[*self.sources.values(), *self.provenance.get("sources", {}).values()])
                self.record_output(path, "CSV")
                self.status.setText(f"{len(frame):,} rows from {name} exported to {path}")
            except Exception as exc:
                self.failure(str(exc))

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Processing in progress", "Wait for processing to finish before closing.")
            event.ignore()
        else:
            if getattr(self, "_acknowledgements_dialog", None) is not None:
                self._acknowledgements_dialog.close()
            event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "time_fields"):
            self.arrange_time_fields()
        if hasattr(self, "data_details"):
            orientation = Qt.Horizontal if self.width() >= 1280 else Qt.Vertical
            if self.data_details.orientation() != orientation:
                self.data_details.setOrientation(orientation)
                self.data_details.setSizes([660, 400] if orientation == Qt.Horizontal else [220, 300])

    def arrange_time_fields(self):
        # Use actual control hints, including Windows font metrics and the
        # hidden elapsed-seconds editor, rather than a fixed window breakpoint.
        available = self.width() - self.sidebar.rail_width - 44 - 38 - 24 - 24
        for widget in self.time_fields:
            widget.ensurePolished()
        widths = [widget.minimumSizeHint().width() for widget in self.time_fields]
        spacing = max(12, self.time_grid.horizontalSpacing())
        if sum(widths) + spacing * 2 <= available:
            columns = 3
        elif max(widths[0], widths[1] + widths[2] + spacing) <= available:
            columns = 2
        else:
            columns = 1
        if columns == self._time_field_columns:
            return
        self._time_field_columns = columns
        for widget in self.time_fields:
            self.time_grid.removeWidget(widget)
        if columns == 2:
            self.time_grid.addWidget(self.time_fields[0], 0, 0, 1, 2)
            self.time_grid.addWidget(self.time_fields[1], 1, 0)
            self.time_grid.addWidget(self.time_fields[2], 1, 1)
        elif columns == 3:
            for column, widget in enumerate(self.time_fields):
                self.time_grid.addWidget(widget, 0, column)
        else:
            for row, widget in enumerate(self.time_fields):
                self.time_grid.addWidget(widget, row, 0)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ParaDigMaDesktop")
    app.setOrganizationName("ParaDigMa")
    app.setStyle("Fusion")
    window = MainWindow()
    screen = app.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        window.resize(max(window.minimumWidth(), min(window.width(), available.width() - 48)),
                      max(window.minimumHeight(), min(window.height(), available.height() - 48)))
    app.setWindowIcon(window.windowIcon())
    window.show()
    sys.exit(app.exec())
