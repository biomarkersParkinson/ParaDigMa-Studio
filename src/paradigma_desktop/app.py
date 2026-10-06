"""Native scientific workspace with separate configuration and exploration."""
import json
import logging
import sys
from importlib.metadata import version
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThread, Signal, QStandardPaths
from PySide6.QtGui import QAction, QIcon, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableView, QListView,
    QTabWidget, QVBoxLayout, QWidget, QListWidget, QListWidgetItem,
)
from .plot_cache import configure_plot_cache

PLOT_CACHE_DIRECTORY = configure_plot_cache(QStandardPaths.writableLocation(QStandardPaths.GenericCacheLocation))

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib import colormaps

from .core import (
    analyze, export_results, export_table_csv, load_sensor_file, result_tables,
    validate_column_mapping, validate_orientation,
)
from .exploration import PARTICIPANT_COLUMNS, gait_context, measurement_columns, select_rows, source_timeline
from .history import RunHistory, load_result_export, new_run, now
from .inspection import TIME_NAMES, inspect_recording, sensor_descriptives, time_descriptives
from .plot_controls import add_graph_controls
from .theme import STYLESHEET, light_palette, style_axes


class FrameModel(QAbstractTableModel):
    def __init__(self, frame, compact=False):
        super().__init__()
        self.frame = frame
        self.compact = compact

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role in (Qt.DisplayRole, Qt.ToolTipRole):
            value = self.frame.iat[index.row(), index.column()]
            if self.compact and role == Qt.DisplayRole and (value is pd.NA or value is None
                    or isinstance(value, (float, np.floating)) and np.isnan(value)):
                return "—"
            if self.compact and role == Qt.DisplayRole and isinstance(value, (float, np.floating)):
                return f"{value:.5g}"
            return str(value)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return str(self.frame.columns[section]) if orientation == Qt.Horizontal else str(section + 1)


class ReadableComboBox(QComboBox):
    def showPopup(self):
        # The outer popup owns the margins above/below the list. It does not
        # reliably inherit the list palette on Windows with a dark system theme.
        popup = self.view().window()
        palette = light_palette()
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            palette.setColor(group, QPalette.Window, palette.color(group, QPalette.Base))
        popup.setPalette(palette)
        popup.setAutoFillBackground(True)
        super().showPopup()


class ReadableTable(QTableView):
    def __init__(self):
        super().__init__()
        self._heading_widths = []
        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setTextElideMode(Qt.ElideNone)
        font = header.font()
        font.setWeight(QFont.DemiBold)
        header.setFont(font)
        # Size data columns from a small sample, never the entire sensor file.
        header.setResizeContentsPrecision(25)
        header.sectionResized.connect(self.keep_heading_readable)

    def setModel(self, model):
        self._heading_widths = []
        super().setModel(model)
        if model is not None:
            self.ensurePolished()
            self.horizontalHeader().ensurePolished()
            metrics = self.horizontalHeader().fontMetrics()
            self._heading_widths = [metrics.horizontalAdvance(str(model.headerData(i, Qt.Horizontal))) + 28
                                    for i in range(model.columnCount())]
            self.resizeColumnsToContents()

    def resizeColumnsToContents(self):
        super().resizeColumnsToContents()
        for i, width in enumerate(self._heading_widths):
            if self.columnWidth(i) < width:
                self.setColumnWidth(i, width)

    def setColumnWidth(self, column, width):
        if column < len(self._heading_widths):
            width = max(width, self._heading_widths[column])
        super().setColumnWidth(column, width)

    def keep_heading_readable(self, column, old_width, width):
        if column < len(self._heading_widths) and width < self._heading_widths[column]:
            header = self.horizontalHeader()
            previous = header.blockSignals(True)
            header.resizeSection(column, self._heading_widths[column])
            header.blockSignals(previous)


class SignalHandler(logging.Handler):
    def __init__(self, signal, warning=None):
        super().__init__()
        self.signal = signal
        self.warning = warning

    def emit(self, record):
        self.signal.emit(self.format(record))
        if self.warning is not None and record.levelno >= logging.WARNING:
            self.warning.emit(record.getMessage())


class Worker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    message = Signal(str)
    warning = Signal(str)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        logger = logging.Logger("paradigma-desktop", logging.INFO)
        handler = SignalHandler(self.message, self.warning)
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


def label(text="", role=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(True)
    if role:
        widget.setObjectName(role)
    return widget


def button(text, callback=None, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    if callback:
        widget.clicked.connect(callback)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName("card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    return widget, layout


def table():
    widget = ReadableTable()
    widget.setPalette(light_palette())
    widget.horizontalHeader().setPalette(light_palette())
    widget.verticalHeader().setPalette(light_palette())
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.verticalHeader().hide()
    widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
    return widget


def readout():
    widget = QPlainTextEdit()
    widget.setReadOnly(True)
    return widget


def field(title, control):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    heading = label(title, "muted")
    heading.setBuddy(control)
    layout.addWidget(heading)
    layout.addWidget(control)
    control.setAccessibleName(title)
    return widget


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
        self.tables, self.provenance = {}, {}
        self.active_frame = None
        self._summary_frame = None
        self.active_positions = np.array([], dtype=int)
        self.active_selection = {}
        self.result_source_frame = None
        self.result_timeline = None
        self.sensor_frame = None
        self.active_run = self.current_run = self.selected_run = None
        self.sidebar_collapsed = False
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
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(194)
        navigation = QVBoxLayout(self.sidebar)
        navigation.setContentsMargins(12, 20, 12, 18)
        navigation.setSpacing(8)
        brand_row = QHBoxLayout()
        self.brand_icon = label()
        self.brand_icon.setPixmap(self.windowIcon().pixmap(28, 28))
        self.brand_icon.setToolTip("ParaDigMa")
        brand_row.addWidget(self.brand_icon)
        self.brand = label("ParaDigMa", "brand")
        brand_row.addWidget(self.brand, 1)
        navigation.addLayout(brand_row)
        self.brand_caption = label("SENSOR ANALYSIS", "muted")
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
        self.local_label = label("Local processing")
        navigation.addWidget(self.local_label)
        self.collapse_button = button("‹  Collapse", self.toggle_sidebar)
        self.collapse_button.setObjectName("collapse")
        self.collapse_button.setAccessibleName("Collapse navigation")
        navigation.addWidget(self.collapse_button)
        shell.addWidget(self.sidebar)
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
        self.open_button = button("Open sensor file…", self.open_file, primary=True)
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 4, 0)
        content.setSpacing(18)
        panel, input_layout = card()
        input_layout.addWidget(label("Selected input", "muted"))
        input_row = QHBoxLayout()
        self.analysis_input = label("No recording loaded", "sectionTitle")
        input_row.addWidget(self.analysis_input, 1)
        input_row.addWidget(button("Inspect input", lambda: self.navigate(0)))
        input_layout.addLayout(input_row)
        self.analysis_input_detail = label("", "muted")
        input_layout.addWidget(self.analysis_input_detail)
        content.addWidget(panel)
        self.analysis_controls = QWidget()
        controls = QVBoxLayout(self.analysis_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(16)
        controls.addWidget(label("Analysis modules", "sectionTitle"))
        modules = QHBoxLayout()
        self.module_buttons = {}
        for name, description in (("Gait", "Requires accelerometer and gyroscope channels."),
                                  ("Tremor", "Requires gyroscope channels. Can run together with gait."),
                                  ("Pulse rate", "Requires raw green PPG. Runs separately from gait and tremor.")):
            item = button(name)
            item.setObjectName("module")
            item.setCheckable(True)
            item.setToolTip(description)
            self.module_buttons[name] = item
            modules.addWidget(item, 1)
        self.module_buttons["Gait"].setChecked(True)
        controls.addLayout(modules)
        self.module_requirements = label("", "muted")
        controls.addWidget(self.module_requirements)
        self.settings_panel, parameters = card()
        parameters.addWidget(label("Analysis parameters", "sectionTitle"))
        columns = QHBoxLayout()
        columns.setSpacing(28)
        left = QFormLayout()
        right = QFormLayout()
        for form in (left, right):
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setSpacing(14)
        self.side = self.combo(["left", "right"])
        self.acc = self.combo(["g", "m/s^2"])
        self.gyro = self.combo(["deg/s", "rad/s"])
        self.time = self.combo(["relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"])
        for widget in (self.side, self.acc, self.gyro, self.time):
            widget.setMinimumWidth(160)
        self.orientation = QLineEdit("x,y,z")
        self.orientation.setToolTip("Three signed axes, for example x,y,z or -y,x,z")
        for title, widget in (("Watch side", self.side), ("Acceleration units", self.acc),
                              ("Gyroscope units", self.gyro), ("Time units", self.time),
                              ("Device axes", self.orientation)):
            left.addRow(title, widget)
        self.prepared = QCheckBox("Already prepared (skip conversion)")
        self.prepared.setToolTip("Prepared data must already use relative seconds, g and deg/s.")
        self.gaps = QCheckBox("Split recordings at time gaps")
        self.gaps.setChecked(True)
        self.drop_missing = QCheckBox("Exclude missing sensor samples")
        self.drop_missing.setChecked(True)
        self.drop_missing.setToolTip("Exclude invalid required samples and analyze valid sections separately.")
        for widget in (self.prepared, self.gaps, self.drop_missing):
            widget.setPalette(light_palette())
            right.addRow(widget)
        self.max_gap, self.min_segment = QDoubleSpinBox(), QDoubleSpinBox()
        for widget in (self.max_gap, self.min_segment):
            widget.setRange(0.01, 86400)
            widget.setValue(1.5)
            widget.setSuffix(" s")
            widget.setDecimals(2)
        right.addRow("Maximum gap", self.max_gap)
        right.addRow("Minimum section duration", self.min_segment)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        parameters.addLayout(columns)
        self.mapping = QPlainTextEdit("{}")
        self.mapping.setPlaceholderText('{"timestamp": "time", "ppg": "green"}')
        self.mapping.setFixedHeight(70)
        parameters.addWidget(field("Column mapping (JSON)", self.mapping))
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

    def _build_results(self):
        layout = self.page()
        controls = QHBoxLayout()
        self.dataset = self.combo()
        self.dataset.setMinimumWidth(160)
        self.dataset.setAccessibleName("Result dataset")
        self.dataset.setToolTip("Output dataset")
        controls.addWidget(self.dataset, 1)
        self.filters_toggle = button("Filters")
        self.filters_toggle.setCheckable(True)
        controls.addWidget(self.filters_toggle)
        self.csv_button = button("Export selection CSV…", self.export_csv)
        self.export_button = button("Export all JSON…", self.export)
        self.csv_button.setEnabled(False)
        self.export_button.setEnabled(False)
        controls.addWidget(self.csv_button)
        controls.addWidget(self.export_button)
        layout.addLayout(controls)
        settings = QHBoxLayout()
        self.x_column, self.y_column = self.combo(), self.combo()
        settings.addWidget(field("Metric", self.y_column), 1)
        settings.addWidget(field("Horizontal axis", self.x_column), 1)
        self.participant, self.segment = self.combo(), self.combo()
        self.participant_field = field("Participant", self.participant)
        self.segment_field = field("Recording section", self.segment)
        settings.addWidget(self.participant_field, 1)
        settings.addWidget(self.segment_field, 1)
        self.participant_field.hide()
        self.segment_field.hide()
        layout.addLayout(settings)
        self.filters_panel, filters = card()
        row = QHBoxLayout()
        self.filter_column = self.combo()
        self.filter_value = QLineEdit()
        self.filter_value.setPlaceholderText("Contains text")
        self.filter_min, self.filter_max = QLineEdit(), QLineEdit()
        self.filter_min.setPlaceholderText("Minimum")
        self.filter_max.setPlaceholderText("Maximum")
        row.addWidget(field("Column", self.filter_column), 2)
        row.addWidget(field("Text", self.filter_value), 2)
        row.addWidget(field("Minimum", self.filter_min), 1)
        row.addWidget(field("Maximum", self.filter_max), 1)
        actions = QVBoxLayout()
        actions.addStretch()
        actions.addWidget(button("Apply", self.apply_filters, primary=True))
        row.addLayout(actions)
        actions = QVBoxLayout()
        actions.addStretch()
        actions.addWidget(button("Reset", self.reset_filters))
        row.addLayout(actions)
        filters.addLayout(row)
        self.filter_status = label("", "muted")
        filters.addWidget(self.filter_status)
        layout.addWidget(self.filters_panel)
        self.filters_panel.hide()
        self.selection_note = label("No results", "muted")
        layout.addWidget(self.selection_note)
        self.result_tabs = QTabWidget()
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(18, 18, 18, 18)
        metrics = QHBoxLayout()
        self.result_values = []
        for title in ("Selected rows", "Metric median", "Metric range"):
            panel, content = card()
            content.addWidget(label(title, "muted"))
            value = label("—", "metricValue")
            content.addWidget(value)
            self.result_values.append(value)
            metrics.addWidget(panel, 1)
        overview_layout.addLayout(metrics)
        overview_layout.addWidget(label("Descriptive statistics of the selection", "sectionTitle"))
        self.summary_table = table()
        overview_layout.addWidget(self.summary_table, 1)
        self.summary_table.setToolTip("Statistics of selected rows. Official aggregations are separate output datasets.")
        self.metadata_toggle = button("Metadata")
        self.metadata_toggle.setCheckable(True)
        overview_layout.addWidget(self.metadata_toggle, alignment=Qt.AlignLeft)
        self.result_metadata = readout()
        self.result_metadata.setMaximumHeight(130)
        overview_layout.addWidget(self.result_metadata)
        self.result_metadata.hide()
        self.metadata_toggle.toggled.connect(self.result_metadata.setVisible)
        self.result_tabs.addTab(overview, "Overview")
        graphs = QWidget()
        graph_layout = QVBoxLayout(graphs)
        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.plot_toolbar = add_graph_controls(graph_layout, self.canvas, self)
        graph_layout.addWidget(self.canvas, 1)
        self.canvas.setToolTip("Click a time-based point to select its result row.")
        self.result_tabs.addTab(graphs, "Graphs")
        self.result_table = table()
        self.result_tabs.addTab(self.result_table, "Tables")
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
        self.sensor_tab_index = self.result_tabs.addTab(self.sensor_panel, "Sensor context")
        self.result_tabs.setTabVisible(self.sensor_tab_index, False)
        layout.addWidget(self.result_tabs, 1)
        context = QHBoxLayout()
        self.context_button = button("Inspect sensor context", self.inspect_sensor_context)
        self.context_button.setEnabled(False)
        context.addWidget(self.context_button)
        self.context_radius = QDoubleSpinBox()
        self.context_radius.setRange(0.1, 120)
        self.context_radius.setValue(2)
        self.context_radius.setSuffix(" s")
        self.context_radius.setMaximumWidth(100)
        self.context_radius.setToolTip("Original samples within this radius of the selected time; not an analysis window.")
        context.addWidget(label("±", "muted"))
        context.addWidget(self.context_radius)
        self.context_hint = label("Select a result row", "muted")
        context.addWidget(self.context_hint, 1)
        layout.addLayout(context)

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
        self.run_details, self.run_warnings, self.run_outputs = readout(), readout(), readout()
        self.log = readout()
        for widget, title in ((self.run_details, "Parameters"), (self.run_warnings, "Warnings"),
                              (self.run_outputs, "Outputs"), (self.log, "Processing log")):
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
        self.x_column.currentIndexChanged.connect(self.plot)
        self.y_column.currentIndexChanged.connect(self.update_metric)
        self.participant.currentIndexChanged.connect(self.apply_filters)
        self.segment.currentIndexChanged.connect(self.apply_filters)
        self.filter_value.returnPressed.connect(self.apply_filters)
        self.filter_min.returnPressed.connect(self.apply_filters)
        self.filter_max.returnPressed.connect(self.apply_filters)
        self.sensor_channel.currentIndexChanged.connect(self.plot_sensor)
        self.canvas.mpl_connect("button_press_event", self.graph_clicked)
        self.modules_changed()
        self.preparation_changed()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.page_title.setText(self.SECTIONS[index])
        for i, item in enumerate(self.nav_buttons):
            item.setChecked(i == index)

    def toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        compact = self.sidebar_collapsed
        self.sidebar.setFixedWidth(68 if compact else 194)
        self.brand.setText("P" if compact else "ParaDigMa")
        self.brand.setVisible(not compact)
        self.brand_caption.setVisible(not compact)
        self.local_label.setVisible(not compact)
        for i, item in enumerate(self.nav_buttons):
            item.setText(str(i + 1) if compact else f"{i + 1}    {self.SECTIONS[i]}")
        self.collapse_button.setText("›" if compact else "‹  Collapse")
        self.collapse_button.setAccessibleName("Expand navigation" if compact else "Collapse navigation")

    def show_notice(self, message):
        self.notice.setText(message)
        self.notice.setVisible(bool(message))

    def selected_modules(self):
        return [self.MODULES[name] for name, item in self.module_buttons.items() if item.isChecked()]

    def set_modules(self, pipelines):
        selected = set(pipelines)
        if "pulse_rate" in selected:
            selected = {"pulse_rate"}
        for name, item in self.module_buttons.items():
            blocked = item.blockSignals(True)
            item.setChecked(self.MODULES[name] in selected)
            item.blockSignals(blocked)
        self.modules_changed()

    def modules_changed(self, changed=None, checked=False):
        # Gait and tremor are independently selectable; the official API
        # requires pulse rate to run on its own.
        if checked:
            incompatible = ("Gait", "Tremor") if changed == "Pulse rate" else ("Pulse rate",)
            for name in incompatible:
                item = self.module_buttons[name]
                blocked = item.blockSignals(True)
                item.setChecked(False)
                item.blockSignals(blocked)
        selected = self.selected_modules()
        self.side.setEnabled("gait" in selected)
        self.module_requirements.setText(
            "Requires accelerometer and gyroscope channels." if "gait" in selected else
            "Requires gyroscope channels." if "tremor" in selected else
            "Raw green PPG required; raw preparation also needs accelerometer channels." if "pulse_rate" in selected else
            "Select an analysis module.")
        self.run_button.setEnabled(self.frame is not None and bool(selected) and self.worker is None)

    def preparation_changed(self, *_):
        prepared = self.prepared.isChecked()
        for widget in (self.acc, self.gyro, self.time, self.orientation, self.gaps):
            widget.setEnabled(not prepared)
        for widget in (self.max_gap, self.min_segment):
            widget.setEnabled(not prepared and self.gaps.isChecked())

    def start_job(self, operation, completed):
        if self.worker is not None:
            return
        for widget in (self.open_button, self.run_button, self.settings_panel, self.analysis_controls,
                       self.export_button, self.csv_button, self.open_run_button, self.use_parameters_button,
                       self.data_time_channel, self.data_time_unit):
            widget.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.worker = Worker(operation)
        self.worker.completed.connect(completed)
        self.worker.failed.connect(self.failure)
        self.worker.message.connect(self.append_log)
        self.worker.warning.connect(self.capture_warning)
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
        self.modules_changed()
        self.preparation_changed()
        self.export_button.setEnabled(self.results is not None)
        self.csv_button.setEnabled(self.active_frame is not None)
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
            if self.selected_run is self.active_run:
                self.run_warnings.setPlainText("\n\n".join(self.active_run["warnings"]))

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
        for error in errors:
            message = error if isinstance(error, str) else json.dumps(error, default=str)
            if message not in record["warnings"]:
                record["warnings"].append(message)
        self.persist_run(record)
        self.active_run = None
        self.refresh_runs()

    def failure(self, message):
        self.status.setText("Operation failed. See the processing log.")
        self.append_log(message)
        self.show_notice(message)
        self.finish_run("Failed", [message])

    def clear_results(self):
        self.results, self.active_frame = None, None
        self._summary_frame = None
        self.tables = {}
        self.dataset.clear()
        self.result_table.setModel(None)
        self.summary_table.setModel(None)
        self.export_button.setEnabled(False)
        self.csv_button.setEnabled(False)
        self.hide_sensor_context()
        self.context_button.setEnabled(False)
        self.figure.clear()
        self.canvas.draw_idle()

    def open_file(self):
        if self.worker is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open sensor recording", "",
            "Sensor files (*.csv *.parquet *.pkl *.pickle *.json *.avro *.cwa *.CWA);;All files (*)")
        if not path:
            return
        allow_pickle = False
        if Path(path).suffix.lower() in (".pkl", ".pickle"):
            reply = QMessageBox.warning(self, "Trusted pickle files only",
                "Pickle files can execute code when opened. Only continue if you trust this file's source.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            allow_pickle = True
        self.show_notice("")
        self.status.setText("Loading recording…")
        unit = self.time.currentText()
        def load(logger):
            frame = load_sensor_file(path, allow_pickle=allow_pickle)
            return path, frame, inspect_recording(frame, unit)
        self.start_job(load, self.loaded)

    def loaded(self, payload):
        self.source, self.frame = payload[:2]
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
        numeric = [column for column in self.frame.select_dtypes(include="number").columns
                   if str(column).lower() not in TIME_NAMES
                   and not pd.api.types.is_complex_dtype(self.frame[column].dtype)]
        palette = colormaps["tab10"] if len(numeric) <= 10 else colormaps["tab20"] if len(numeric) <= 20 else None
        colors = palette.colors if palette is not None else colormaps["turbo"](np.linspace(.05, .95, len(numeric)))
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
        ax = style_axes(self.data_figure)
        channels = self.selected_input_channels()
        if self.frame is not None and channels:
            step = max(1, int(np.ceil(len(self.frame) / 20000)))
            sample = self.frame.iloc[::step]
            column = self.data_time_channel.currentData()
            times, time_label = None, "Time (file units)"
            if column in sample:
                series = sample[column]
                if pd.api.types.is_datetime64_any_dtype(series.dtype):
                    times, time_label = series, "Time"
                elif pd.api.types.is_timedelta64_dtype(series.dtype):
                    times, time_label = series.dt.total_seconds(), "Time (s)"
                elif not pd.api.types.is_complex_dtype(series.dtype):
                    times = pd.to_numeric(series, errors="coerce")
            numeric_time = times is not None and times.notna().all()
            for channel in channels:
                ax.plot(times if numeric_time else np.arange(len(self.frame))[::step], sample[channel],
                        color=self._channel_colors[channel], linewidth=1, label=str(channel))
            ax.set_xlabel(time_label if numeric_time else "Sample position")
            ax.set_ylabel(str(channels[0]) if len(channels) == 1 else "Sensor values (file units)")
            if len(channels) > 1:
                ax.legend(loc="upper left", bbox_to_anchor=(0, 1.02), ncols=min(3, len(channels)), frameon=False, fontsize=9)
        else:
            ax.text(.5, .5, "Select sensor channels" if self.frame is not None else "Open a recording with numeric sensor channels",
                    ha="center", transform=ax.transAxes)
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
        record["paradigma_version"] = version("paradigma")
        record["_frame"] = self.frame
        self.runs.insert(0, record)
        self.active_run = self.current_run = self.selected_run = record
        self.provenance = {"source": self.source, "paradigma_version": record["paradigma_version"], "settings": settings, "run_id": record["id"]}
        self.result_source_frame = self.frame
        self.result_timeline = None
        self.clear_results()
        self.log.clear()
        self.persist_run(record)
        self.refresh_runs()
        self.status.setText("Running ParaDigMa… Review progress in Runs.")
        self.navigate(1)
        frame = self.frame
        self.start_job(lambda logger: analyze(frame, logger=logger, **settings), self.analyzed)

    def analyzed(self, results):
        self.results = results
        if self.active_run is not None:
            self.active_run["_results"] = results
            self.active_run["_provenance"] = dict(self.provenance)
        elif self.current_run is None:
            self.result_source_frame = self.frame
        self.tables = result_tables(results)
        self.dataset.blockSignals(True)
        self.dataset.clear()
        self.dataset.addItems(self.tables)
        preferred = next((name for name, frame in self.tables.items() if name.startswith("quantifications/") and len(frame)), None)
        if preferred:
            self.dataset.setCurrentText(preferred)
        self.dataset.blockSignals(False)
        self.select_dataset(self.dataset.currentText())
        self.export_button.setEnabled(self.worker is None)
        errors = results.get("errors", [])
        if errors:
            self.append_log(json.dumps(errors, indent=2, default=str))
            message = f"Analysis returned {len(errors)} processing error(s); inspect Runs and the partial results."
            self.status.setText(message)
            self.show_notice(message)
            self.finish_run("Partial", errors)
        else:
            has_rows = any(len(v) for k, v in self.tables.items() if k.startswith("quantifications/"))
            message = "Analysis completed." if has_rows else "No quantified windows. See Runs for details."
            self.status.setText(message)
            self.finish_run("Completed", [] if has_rows else [message])
        self.navigate(2)

    def select_dataset(self, name):
        frame = self.tables.get(name)
        self.hide_sensor_context()
        self.context_button.setEnabled(False)
        self.context_hint.setText("Select a result row" if self.result_source_frame is not None else "Original sensor data unavailable")
        for widget in (self.x_column, self.y_column, self.participant, self.segment, self.filter_column):
            widget.blockSignals(True)
            widget.clear()
        self.filter_value.clear()
        self.filter_min.clear()
        self.filter_max.clear()
        self.participant_column = None
        self.participant.addItem("All participants", None)
        self.segment.addItem("All sections", None)
        self.filter_column.addItem("Choose a column", None)
        if frame is not None:
            numeric = list(frame.select_dtypes(include="number").columns)
            self.x_column.addItem("Row number", None)
            for column in numeric:
                self.x_column.addItem("Row number (column)" if column == "Row number" else str(column), column)
                self.y_column.addItem(str(column), column)
            if "time" in numeric:
                self.x_column.setCurrentText("time")
            measurements = measurement_columns(frame)
            preferred = next((column for column in ("range_of_motion", "tremor_power", "pulse_rate", "heart_rate") if column in measurements),
                             measurements[0] if measurements else (numeric[0] if numeric else None))
            if preferred is not None:
                self.y_column.setCurrentIndex(numeric.index(preferred))
            for column in frame.columns:
                self.filter_column.addItem(str(column), column)
            self.participant_column = next((c for c in PARTICIPANT_COLUMNS if c in frame), None)
            if self.participant_column:
                for value in frame[self.participant_column].dropna().unique():
                    self.participant.addItem(str(value), value)
            if "file_key" in frame:
                for value in frame["file_key"].dropna().unique():
                    self.segment.addItem(str(value), value)
        self.participant.setEnabled(self.participant_column is not None)
        self.segment.setEnabled(frame is not None and "file_key" in frame)
        self.participant_field.setVisible(self.participant_column is not None)
        self.segment_field.setVisible(frame is not None and "file_key" in frame)
        self.participant.setToolTip("Filters existing participant identifiers; none are inferred." if self.participant_column else "This output contains no participant identifiers.")
        for widget in (self.x_column, self.y_column, self.participant, self.segment, self.filter_column):
            widget.blockSignals(False)
        self.apply_filters()

    def apply_filters(self, *_):
        frame = self.tables.get(self.dataset.currentText())
        if frame is None:
            self.active_frame = None
            self.active_positions = np.array([], dtype=int)
            self.result_table.setModel(None)
            self.csv_button.setEnabled(False)
            self.selection_note.setText("No results")
            self.result_metadata.clear()
            self.filter_status.setText("No output selected.")
            self.update_metric()
            return
        try:
            selected, positions = select_rows(frame, participant_column=self.participant_column,
                participant=self.participant.currentData(), segment=self.segment.currentData(),
                column=self.filter_column.currentData(), text=self.filter_value.text().strip(),
                minimum=self.filter_min.text().strip(), maximum=self.filter_max.text().strip())
        except ValueError as exc:
            self.filter_status.setText(str(exc))
            return
        self.active_frame, self.active_positions = selected, positions
        self.active_selection = {"participant": self.participant.currentData(), "section": self.segment.currentData(),
            "column": self.filter_column.currentData(), "text": self.filter_value.text().strip(),
            "minimum": self.filter_min.text().strip(), "maximum": self.filter_max.text().strip()}
        self.result_table.setModel(FrameModel(selected))
        self.result_table.selectionModel().currentRowChanged.connect(self.result_row_changed)
        self.hide_sensor_context()
        self.context_button.setEnabled(False)
        self.csv_button.setEnabled(self.worker is None)
        source = self.provenance.get("source", self.source)
        self.selection_note.setText(f"{Path(source).name or 'Current analysis'} · {len(selected):,} / {len(frame):,} rows")
        self.filter_status.clear()
        self.update_metric()
        self.result_metadata.setPlainText(json.dumps({"dataset": self.dataset.currentText(), "rows": len(frame),
            "selected_rows": len(selected), "source": source,
            "preparation": self.results.get("metadata", {}).get("desktop_preparation", {}) if self.results else {}}, indent=2, default=str))

    def reset_filters(self):
        for widget in (self.participant, self.segment, self.filter_column):
            widget.blockSignals(True)
            widget.setCurrentIndex(0)
            widget.blockSignals(False)
        self.filter_value.clear()
        self.filter_min.clear()
        self.filter_max.clear()
        self.apply_filters()

    def update_metric(self, *_):
        frame, metric = self.active_frame, self.y_column.currentData()
        self.result_values[0].setText(f"{len(frame):,}" if frame is not None else "—")
        self.result_values[1].setText("—")
        self.result_values[2].setText("—")
        if frame is not self._summary_frame:
            self.summary_table.setModel(None)
        if frame is not None:
            # Changing only the graph metric does not change this selection's
            # overview. Recompute its full statistics when rows/dataset change.
            if frame is not self._summary_frame:
                numeric = frame[measurement_columns(frame)].replace([np.inf, -np.inf], np.nan)
                if len(numeric.columns) and len(numeric):
                    summary = numeric.describe().T.reset_index().rename(columns={"index": "Metric"})
                    summary = summary[["Metric", "count", "mean", "std", "min", "50%", "max"]].rename(
                        columns={"count": "Count", "mean": "Mean", "std": "SD", "min": "Min", "50%": "Median", "max": "Max"})
                    self.summary_table.setModel(FrameModel(summary, compact=True))
                    self.summary_table.resizeColumnsToContents()
            if metric in frame and pd.api.types.is_numeric_dtype(frame[metric].dtype):
                values = frame[metric].replace([np.inf, -np.inf], np.nan).dropna()
                if len(values):
                    self.result_values[1].setText(f"{values.median():.4g}")
                    self.result_values[2].setText(f"{values.min():.4g} – {values.max():.4g}")
        self._summary_frame = frame
        self.plot()

    def plot(self, *_):
        self.figure.clear()
        ax = style_axes(self.figure)
        frame = self.active_frame
        y, x = self.y_column.currentData(), self.x_column.currentData()
        row_number = self.x_column.currentIndex() == 0
        if frame is not None and y in frame and (row_number or x in frame) and len(frame):
            step = max(1, int(np.ceil(len(frame) / 20000)))
            sample = frame.iloc[::step]
            xv = self.active_positions[::step] if row_number else sample[x]
            xs = np.asarray(xv, dtype=float) if row_number else sample[x].to_numpy(dtype=float, na_value=np.nan)
            ys = sample[y].to_numpy(dtype=float, na_value=np.nan)
            multiple_participants = self.participant_column is not None and sample[self.participant_column].nunique() > 1
            if "file_key" in sample and not multiple_participants:
                changes = sample["file_key"].ne(sample["file_key"].shift()).fillna(True).to_numpy(dtype=bool)
                boundaries = np.flatnonzero(changes)[1:]
                xs, ys = np.insert(xs, boundaries, np.nan), np.insert(ys, boundaries, np.nan)
            ax.plot(xs, ys, color="#2563a5", linewidth=0 if multiple_participants else 1.25,
                    marker="o" if multiple_participants or len(sample) < 120 else None, markersize=3)
            ax.set_xlabel(self.x_column.currentText())
            ax.set_ylabel(self.y_column.currentText())
            ax.set_title(self.dataset.currentText(), fontsize=10, loc="left")
        else:
            ax.text(.5, .5, "No rows or numeric metric in the current selection", ha="center", transform=ax.transAxes, color="#68778c")
        self.plot_toolbar.refresh()
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
        if valid_row and not timestamp and segment is None:
            self.context_hint.setText("No sensor timing available")
        if self.result_source_frame is None:
            self.context_hint.setText("Original sensor data unavailable")

    def graph_clicked(self, event):
        frame = self.active_frame
        if (event.inaxes is None or event.xdata is None or self.x_column.currentData() != "time"
                or self.plot_toolbar.mode or frame is None or "time" not in frame or frame.empty):
            return
        distances = np.abs(pd.to_numeric(frame["time"], errors="coerce").to_numpy(dtype=float, na_value=np.nan) - event.xdata)
        finite = np.isfinite(distances)
        if not finite.any():
            return
        row = int(np.argmin(np.where(finite, distances, np.inf)))
        self.result_table.setCurrentIndex(self.result_table.model().index(row, 0))
        self.result_table.selectRow(row)
        self.result_table.scrollTo(self.result_table.currentIndex())
        self.context_hint.setText(f"Selected result at {frame['time'].iloc[row]:.4g} s. Inspect nearby original sensor samples.")

    def inspect_sensor_context(self):
        row = self.result_table.currentIndex().row()
        if not self.context_button.isEnabled() or row < 0:
            return
        try:
            if self.result_timeline is None:
                self.result_timeline = source_timeline(self.result_source_frame, self.provenance.get("settings", {}))
            selected = self.active_frame.iloc[row]
            segment = gait_context(self.results, self.dataset.currentText(), selected)
            if "time" in selected and pd.notna(selected["time"]):
                anchor = float(selected["time"])
                radius = self.context_radius.value()
                mask = np.isfinite(self.result_timeline) & (np.abs(self.result_timeline - anchor) <= radius)
                description = f"near {anchor:.4g} s (±{radius:g} s). This is timestamp context, not the algorithm's exact window."
            elif segment is not None:
                start, end, number = segment
                mask = np.isfinite(self.result_timeline) & (self.result_timeline >= start) & (self.result_timeline < end)
                description = f"from gait segment {number}, {start:.4g}–{end:.4g} s, using toolbox metadata. Individual arm-swing timestamps are not provided."
            else:
                raise ValueError("No explicit sensor time context is available.")
            self.sensor_frame = self.result_source_frame.iloc[np.flatnonzero(mask)]
            self.sensor_times = self.result_timeline[mask]
            self.sensor_table.setModel(FrameModel(self.sensor_frame))
            self.sensor_channel.blockSignals(True)
            self.sensor_channel.clear()
            mapping = self.provenance.get("settings", {}).get("column_mapping", {})
            for column in self.sensor_frame.select_dtypes(include="number").columns:
                if mapping.get(column, column) != "time":
                    self.sensor_channel.addItem(str(column), column)
            self.sensor_channel.blockSignals(False)
            self.sensor_note.setText(f"{len(self.sensor_frame):,} original samples {description} Original units; horizontal axis aligned to analysis time.")
            self.plot_sensor()
            self.result_tabs.setTabVisible(self.sensor_tab_index, True)
            self.result_tabs.setCurrentIndex(self.sensor_tab_index)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self.context_hint.setText(f"Sensor context unavailable: {exc}")

    def hide_sensor_context(self):
        if self.result_tabs.currentIndex() == self.sensor_tab_index:
            self.result_tabs.setCurrentIndex(1)
        self.result_tabs.setTabVisible(self.sensor_tab_index, False)

    def plot_sensor(self, *_):
        self.sensor_figure.clear()
        ax = style_axes(self.sensor_figure)
        column = self.sensor_channel.currentData()
        if self.sensor_frame is not None and column in self.sensor_frame and len(self.sensor_frame):
            step = max(1, int(np.ceil(len(self.sensor_frame) / 20000)))
            ax.plot(self.sensor_times[::step], self.sensor_frame[column].iloc[::step], color="#bc601f", linewidth=1)
            ax.set_xlabel("Analysis time (s)")
            ax.set_ylabel(str(column))
        else:
            ax.text(.5, .5, "No original samples in this context", ha="center", transform=ax.transAxes)
        self.sensor_toolbar.refresh()
        self.sensor_canvas.draw_idle()

    def refresh_runs(self):
        data = pd.DataFrame([{"Started": datetime.fromisoformat(record["started"]).astimezone().strftime("%d %b %Y · %H:%M"), "Status": record["status"],
            "Input": Path(record["source"]).name, "Modules": ", ".join(record["settings"].get("pipelines", [])),
            "Warnings": len(record["warnings"]), "Exports": len(record["outputs"])} for record in self.runs],
            columns=["Started", "Status", "Input", "Modules", "Warnings", "Exports"])
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
        self.run_heading.setText(f"{record['status']} · {Path(record['source']).name}")
        self.run_heading.setToolTip(f"Run ID: {record['id']}")
        started = datetime.fromisoformat(record["started"]).astimezone().strftime("%d %b %Y, %H:%M:%S")
        finished = datetime.fromisoformat(record["finished"]).astimezone().strftime("%H:%M:%S") if record.get("finished") else "—"
        self.run_summary.setText(f"{started} – {finished} · ParaDigMa {record.get('paradigma_version', '—')}\n{record['source']}")
        self.run_details.setPlainText("\n".join(f"{key.replace('_', ' ').capitalize()}: {json.dumps(value, ensure_ascii=False)}" for key, value in record["settings"].items()))
        self.run_warnings.setPlainText("\n\n".join(str(value) for value in record["warnings"]) or "No recorded warnings.")
        self.run_outputs.setPlainText("\n\n".join(f"{item.get('kind', 'Export')}: {item.get('path', '')}" for item in record["outputs"]) or "No exports saved.")
        self.log.setPlainText(record.get("log", ""))
        self.update_run_actions()

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
        self.provenance = provenance or {"source": record["source"], "settings": record["settings"], "paradigma_version": record["paradigma_version"]}
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
        self.max_gap.setValue(settings.get("max_gap_seconds", 1.5) or 1.5)
        self.min_segment.setValue(settings.get("min_segment_seconds", 1.5) or 1.5)
        self.preparation_changed()
        self.navigate(1)
        self.status.setText("Run parameters restored. Check the selected input before running.")

    def record_output(self, path, kind):
        if self.current_run is not None:
            self.current_run["outputs"].append({"kind": kind, "path": str(Path(path).resolve()), "saved": now(), "dataset": self.dataset.currentText() if kind == "CSV" else "all results"})
            if kind == "CSV":
                self.current_run["outputs"][-1].update(selected_rows=len(self.active_frame), selection=self.active_selection)
            self.persist_run(self.current_run)
            self.refresh_runs()

    def export(self):
        if self.results is None or self.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export complete results", "paradigma-results.json", "JSON (*.json)")
        if path:
            try:
                export_results(path, self.results, self.provenance, protected_sources=[self.source])
                self.record_output(path, "JSON")
                self.status.setText(f"Results exported to {path}")
            except Exception as exc:
                self.failure(str(exc))

    def export_csv(self):
        if self.active_frame is None or self.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export selected rows", "output.csv", "CSV (*.csv)")
        if path:
            try:
                export_table_csv(path, self.active_frame, source=self.provenance.get("source", self.source), protected_sources=[self.source])
                self.record_output(path, "CSV")
                self.status.setText(f"{len(self.active_frame):,} selected rows exported to {path}")
            except Exception as exc:
                self.failure(str(exc))

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Processing in progress", "Wait for processing to finish before closing.")
            event.ignore()
        else:
            event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "data_details"):
            orientation = Qt.Horizontal if self.width() >= 1280 else Qt.Vertical
            if self.data_details.orientation() != orientation:
                self.data_details.setOrientation(orientation)
                self.data_details.setSizes([660, 400] if orientation == Qt.Horizontal else [220, 300])


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
