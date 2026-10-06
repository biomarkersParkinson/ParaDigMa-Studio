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
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableView,
    QTabWidget, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from .core import (
    analyze, export_results, export_table_csv, load_sensor_file, result_tables,
    validate_column_mapping, validate_orientation,
)
from .exploration import PARTICIPANT_COLUMNS, gait_context, measurement_columns, select_rows, source_timeline
from .history import RunHistory, load_result_export, new_run, now
from .theme import STYLESHEET, style_axes


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
            if self.compact and role == Qt.DisplayRole and isinstance(value, (float, np.floating)):
                return f"{value:.5g}"
            return str(value)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return str(self.frame.columns[section]) if orientation == Qt.Horizontal else str(section + 1)


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
    widget = QTableView()
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
    return widget


def readout():
    widget = QPlainTextEdit()
    widget.setReadOnly(True)
    return widget


class MainWindow(QMainWindow):
    SECTIONS = ("Data", "Analyze", "Results", "Runs")
    SUBTITLES = (
        "Open a recording and inspect its sensor channels.",
        "Choose an analysis plan and review preparation settings.",
        "Explore metrics, compare selections and inspect sensor context.",
        "Review analysis status, parameters, warnings and saved outputs.",
    )

    def __init__(self, history_dir=None):
        super().__init__()
        self.setWindowTitle("ParaDigMa • Sensor analysis")
        self.setWindowIcon(QIcon(str(Path(__file__).with_name("data") / "app-icon.png")))
        self.resize(1450, 920)
        self.setMinimumSize(960, 650)
        self.setStyleSheet(STYLESHEET)
        self.frame = self.results = self.worker = None
        self.source = ""
        self.tables, self.provenance = {}, {}
        self.active_frame = None
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
        self._build_inspectors()
        self._connect()
        self.refresh_runs()
        self.navigate(0)
        self.plot()
        if history_issues:
            self.show_notice("\n".join(history_issues))

    @staticmethod
    def combo(items):
        combo = QComboBox()
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
        self.local_label = label("Local processing\nYour data stays on this device.")
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
        titles = QVBoxLayout()
        self.page_title = label("", "pageTitle")
        self.page_subtitle = label("", "muted")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        heading.addLayout(titles, 1)
        self.inspector_toggle = button("Inspector")
        self.inspector_toggle.setCheckable(True)
        self.inspector_toggle.setChecked(True)
        self.inspector_toggle.setToolTip("Show or hide contextual settings and metadata")
        heading.addWidget(self.inspector_toggle)
        center_layout.addLayout(heading)
        self.notice = label("", "notice")
        self.notice.hide()
        center_layout.addWidget(self.notice)
        self.workspace_split = QSplitter()
        self.pages = QStackedWidget()
        self.workspace_split.addWidget(self.pages)
        self.inspector = QFrame()
        self.inspector.setObjectName("inspector")
        self.inspector.setMinimumWidth(258)
        self.inspector.setMaximumWidth(390)
        inspector_layout = QVBoxLayout(self.inspector)
        inspector_layout.setContentsMargins(16, 16, 12, 12)
        self.inspector_title = label("", "sectionTitle")
        inspector_layout.addWidget(self.inspector_title)
        self.inspector_pages = QStackedWidget()
        inspector_layout.addWidget(self.inspector_pages, 1)
        self.workspace_split.addWidget(self.inspector)
        self.workspace_split.setStretchFactor(0, 1)
        self.workspace_split.setStretchFactor(1, 0)
        self.workspace_split.setSizes([900, 310])
        center_layout.addWidget(self.workspace_split, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        center_layout.addWidget(self.progress)
        self.status = label("Open a recording to begin. Analysis runs locally.", "muted")
        center_layout.addWidget(self.status)
        shell.addWidget(center, 1)

    def page(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(16)
        self.pages.addWidget(widget)
        return layout

    def inspector_page(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 2, 4, 8)
        layout.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.inspector_pages.addWidget(scroll)
        return content, layout

    def _build_data(self):
        layout = self.page()
        panel, content = card()
        row = QHBoxLayout()
        self.file_label = label("No recording loaded", "sectionTitle")
        row.addWidget(self.file_label, 1)
        self.open_button = button("Open sensor file…", self.open_file, primary=True)
        self.open_button.setToolTip("Open a sensor recording (Ctrl+O)")
        self.open_action = QAction("Open recording", self)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.open_file)
        self.addAction(self.open_action)
        row.addWidget(self.open_button)
        content.addLayout(row)
        content.addWidget(label("CSV, Parquet, Axivity CWA, Empatica Avro, TSDF or trusted pickle.", "muted"))
        layout.addWidget(panel)
        metrics = QHBoxLayout()
        self.data_values = []
        for title in ("Sensor samples", "Channels", "Missing values"):
            panel, content = card()
            content.addWidget(label(title, "muted"))
            value = label("—", "metricValue")
            content.addWidget(value)
            self.data_values.append(value)
            metrics.addWidget(panel, 1)
        layout.addLayout(metrics)
        self.data_tabs = QTabWidget()
        self.input_table = table()
        self.data_tabs.addTab(self.input_table, "Samples")
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        self.data_figure = Figure(layout="constrained")
        self.data_canvas = FigureCanvasQTAgg(self.data_figure)
        preview_layout.addWidget(NavigationToolbar2QT(self.data_canvas, self))
        preview_layout.addWidget(self.data_canvas, 1)
        self.data_tabs.addTab(preview, "Signal preview")
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
        self.analysis_input = label("Open a sensor recording in Data to begin.", "sectionTitle")
        input_layout.addWidget(self.analysis_input)
        self.analysis_input_detail = label("", "muted")
        input_layout.addWidget(self.analysis_input_detail)
        input_layout.addWidget(button("Inspect input", lambda: self.navigate(0)), alignment=Qt.AlignLeft)
        content.addWidget(panel)
        self.analysis_controls = QWidget()
        controls = QVBoxLayout(self.analysis_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(16)
        controls.addWidget(label("Analysis modules", "sectionTitle"))
        modules = QHBoxLayout()
        self.module_buttons = {}
        for name, description in (("Gait", "Detection and\narm-swing metrics"),
                                  ("Tremor", "Detection and\ntremor measurements"),
                                  ("Pulse rate", "Raw green PPG\nanalysis")):
            item = button(f"{name}\n{description}", lambda checked=False, n=name: self.pipeline.setCurrentText(n))
            item.setObjectName("module")
            item.setCheckable(True)
            item.setToolTip(description)
            self.module_buttons[name] = item
            modules.addWidget(item, 1)
        controls.addLayout(modules)
        panel, common = card()
        form = QFormLayout()
        form.setSpacing(14)
        self.pipeline = self.combo(["Gait", "Tremor", "Gait + tremor", "Pulse rate"])
        self.side = self.combo(["left", "right"])
        form.addRow("Analysis plan", self.pipeline)
        form.addRow("Watch side", self.side)
        common.addLayout(form)
        self.module_requirements = label("", "muted")
        common.addWidget(self.module_requirements)
        controls.addWidget(panel)
        panel, prep_layout = card()
        prep_layout.addWidget(label("Preprocessing", "sectionTitle"))
        prep_layout.addWidget(label("The toolbox prepares the required signals before extracting metrics. Review input units, missing samples and gaps in the inspector.", "muted"))
        self.preparation_summary = label("", "muted")
        prep_layout.addWidget(self.preparation_summary)
        controls.addWidget(panel)
        content.addWidget(self.analysis_controls)
        content.addStretch()
        row = QHBoxLayout()
        row.addWidget(label("Runs locally · results open in the Results workspace", "muted"), 1)
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
        self.dataset = QComboBox()
        self.dataset.setMinimumWidth(160)
        self.dataset.setAccessibleName("Result dataset")
        controls.addWidget(self.dataset, 1)
        self.csv_button = button("Export selection CSV…", self.export_csv)
        self.export_button = button("Export all JSON…", self.export)
        self.csv_button.setEnabled(False)
        self.export_button.setEnabled(False)
        controls.addWidget(self.csv_button)
        controls.addWidget(self.export_button)
        layout.addLayout(controls)
        self.selection_note = label("Run an analysis to explore its outputs.", "muted")
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
        self.overview_text = label("Choose an output dataset and metric in the inspector.", "muted")
        overview_layout.addWidget(self.overview_text)
        overview_layout.addWidget(label("Descriptive statistics of the selection", "sectionTitle"))
        self.summary_table = table()
        overview_layout.addWidget(self.summary_table, 1)
        overview_layout.addWidget(label("These summaries describe selected rows. Toolbox aggregations remain available as separate datasets.", "muted"))
        self.result_tabs.addTab(overview, "Overview")
        graphs = QWidget()
        graph_layout = QVBoxLayout(graphs)
        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.plot_toolbar = NavigationToolbar2QT(self.canvas, self)
        graph_layout.addWidget(self.plot_toolbar)
        graph_layout.addWidget(self.canvas, 1)
        graph_layout.addWidget(label("Pan, zoom or save the figure. Click a time-based point to select its row for sensor inspection.", "muted"))
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
        self.sensor_channel = QComboBox()
        sensor_layout.addWidget(self.sensor_channel)
        sensor_tabs = QTabWidget()
        sensor_graph = QWidget()
        graph_layout = QVBoxLayout(sensor_graph)
        self.sensor_figure = Figure(layout="constrained")
        self.sensor_canvas = FigureCanvasQTAgg(self.sensor_figure)
        graph_layout.addWidget(NavigationToolbar2QT(self.sensor_canvas, self))
        graph_layout.addWidget(self.sensor_canvas, 1)
        sensor_tabs.addTab(sensor_graph, "Signal")
        self.sensor_table = table()
        sensor_tabs.addTab(self.sensor_table, "Samples")
        sensor_layout.addWidget(sensor_tabs, 1)
        self.sensor_tab_index = self.result_tabs.addTab(self.sensor_panel, "Sensor context")
        self.result_tabs.setTabVisible(self.sensor_tab_index, False)
        layout.addWidget(self.result_tabs, 1)

    def _build_runs(self):
        layout = self.page()
        panel, content = card()
        content.addWidget(label("Analysis history", "sectionTitle"))
        content.addWidget(label("Run metadata is saved locally. Results stay in this session until you export them; exported JSON can be reopened here.", "muted"))
        self.run_table = table()
        content.addWidget(self.run_table, 1)
        actions = QHBoxLayout()
        self.open_run_button = button("Open results", self.open_run)
        self.use_parameters_button = button("Use these parameters", self.use_run_parameters)
        actions.addWidget(self.open_run_button)
        actions.addWidget(self.use_parameters_button)
        actions.addStretch()
        content.addLayout(actions)
        layout.addWidget(panel, 1)
        panel, content = card()
        content.addWidget(label("Processing log", "sectionTitle"))
        self.log = readout()
        content.addWidget(self.log, 1)
        layout.addWidget(panel, 1)

    def _build_inspectors(self):
        _, layout = self.inspector_page()
        layout.addWidget(label("Recording metadata", "sectionTitle"))
        self.data_metadata = readout()
        self.data_metadata.setPlaceholderText("Open a recording to inspect its path, channels and metadata.")
        self.data_metadata.setMinimumHeight(210)
        layout.addWidget(self.data_metadata)
        layout.addWidget(label("Preview channel", "sectionTitle"))
        self.data_channel = QComboBox()
        layout.addWidget(self.data_channel)
        layout.addWidget(label("The preview displays original sensor values. Its horizontal axis uses the file's numeric time values, or sample positions if numeric time is unavailable.", "muted"))
        layout.addStretch()
        self.settings_panel, layout = self.inspector_page()
        layout.addWidget(label("Preparation", "sectionTitle"))
        self.prepared = QCheckBox("Already prepared (skip conversion)")
        self.gaps = QCheckBox("Split recordings at time gaps")
        self.gaps.setChecked(True)
        self.drop_missing = QCheckBox("Exclude missing sensor samples")
        self.drop_missing.setChecked(True)
        self.drop_missing.setToolTip("Exclude invalid required samples, record the count, and analyze valid sections separately.")
        for widget in (self.prepared, self.gaps, self.drop_missing):
            layout.addWidget(widget)
        layout.addWidget(label("Confirm units and orientation for your device before running. Defaults may differ from the recording.", "muted"))
        self.advanced_toggle = button("Advanced parameters  ›")
        self.advanced_toggle.setCheckable(True)
        layout.addWidget(self.advanced_toggle)
        self.advanced_settings = QWidget()
        advanced = QFormLayout(self.advanced_settings)
        advanced.setContentsMargins(0, 4, 0, 4)
        advanced.setRowWrapPolicy(QFormLayout.WrapAllRows)
        advanced.setSpacing(12)
        self.acc = self.combo(["g", "m/s^2"])
        self.gyro = self.combo(["deg/s", "rad/s"])
        self.time = self.combo(["relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"])
        self.orientation = QLineEdit("x,y,z")
        self.mapping = QPlainTextEdit("{}")
        self.mapping.setPlaceholderText('{"timestamp": "time", "ppg": "green"}')
        self.mapping.setFixedHeight(100)
        self.max_gap = QDoubleSpinBox()
        self.min_segment = QDoubleSpinBox()
        for widget in (self.max_gap, self.min_segment):
            widget.setRange(0.01, 86400)
            widget.setValue(1.5)
            widget.setSuffix(" s")
            widget.setDecimals(2)
        for name, widget in (("Acceleration units", self.acc), ("Gyroscope units", self.gyro),
                             ("Time units", self.time), ("Device axes", self.orientation),
                             ("Column mapping (JSON)", self.mapping), ("Maximum gap", self.max_gap),
                             ("Minimum section duration", self.min_segment)):
            advanced.addRow(name, widget)
        advanced.addRow(label("Axes: three signed axes, for example x,y,z or -y,x,z.", "muted"))
        layout.addWidget(self.advanced_settings)
        self.advanced_settings.hide()
        layout.addStretch()
        _, layout = self.inspector_page()
        layout.addWidget(label("Metric & axes", "sectionTitle"))
        self.x_column, self.y_column = QComboBox(), QComboBox()
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.addRow("Horizontal axis", self.x_column)
        form.addRow("Metric", self.y_column)
        layout.addLayout(form)
        layout.addWidget(label("Shared selection", "sectionTitle"))
        self.participant = QComboBox()
        self.segment = QComboBox()
        self.filter_column = QComboBox()
        self.filter_value = QLineEdit()
        self.filter_value.setPlaceholderText("Contains text (optional)")
        self.filter_min, self.filter_max = QLineEdit(), QLineEdit()
        self.filter_min.setPlaceholderText("Minimum")
        self.filter_max.setPlaceholderText("Maximum")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.addRow("Participant", self.participant)
        form.addRow("Recording section", self.segment)
        form.addRow("Filter column", self.filter_column)
        form.addRow("Text", self.filter_value)
        bounds = QHBoxLayout()
        bounds.addWidget(self.filter_min)
        bounds.addWidget(self.filter_max)
        form.addRow("Numeric bounds", bounds)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(button("Apply filters", self.apply_filters, primary=True))
        row.addWidget(button("Reset", self.reset_filters))
        layout.addLayout(row)
        self.filter_status = label("", "muted")
        layout.addWidget(self.filter_status)
        self.context_button = button("Inspect sensor context", self.inspect_sensor_context)
        self.context_button.setEnabled(False)
        layout.addWidget(self.context_button)
        self.context_radius = QDoubleSpinBox()
        self.context_radius.setRange(0.1, 120)
        self.context_radius.setValue(2)
        self.context_radius.setSuffix(" s on each side")
        layout.addWidget(self.context_radius)
        self.context_hint = label("Select a row or click a time-based graph point. Context shows original values near the timestamp, not a reconstructed analysis window.", "muted")
        layout.addWidget(self.context_hint)
        self.result_metadata = readout()
        self.result_metadata.setPlaceholderText("Choose an output to inspect its metadata.")
        self.result_metadata.setMinimumHeight(130)
        layout.addWidget(label("Result metadata", "sectionTitle"))
        layout.addWidget(self.result_metadata)
        layout.addStretch()
        _, layout = self.inspector_page()
        self.run_heading = label("Select an analysis run.", "sectionTitle")
        layout.addWidget(self.run_heading)
        self.run_summary = label("", "muted")
        self.run_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.run_summary)
        layout.addWidget(label("Parameters", "sectionTitle"))
        self.run_details = readout()
        self.run_details.setMinimumHeight(180)
        layout.addWidget(self.run_details)
        layout.addWidget(label("Warnings & errors", "sectionTitle"))
        self.run_warnings = readout()
        self.run_warnings.setMinimumHeight(120)
        layout.addWidget(self.run_warnings)
        layout.addWidget(label("Output locations", "sectionTitle"))
        self.run_outputs = readout()
        self.run_outputs.setMinimumHeight(100)
        layout.addWidget(self.run_outputs)
        location = label(f"Local history: {self.history.directory}", "muted")
        location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(location)
        layout.addStretch()

    def _connect(self):
        self.inspector_toggle.toggled.connect(self.inspector.setVisible)
        self.advanced_toggle.toggled.connect(self.toggle_advanced)
        self.prepared.toggled.connect(self.preparation_changed)
        self.gaps.toggled.connect(self.preparation_changed)
        self.drop_missing.toggled.connect(self.preparation_changed)
        self.pipeline.currentTextChanged.connect(self.plan_changed)
        for combo in (self.acc, self.gyro, self.time):
            combo.currentTextChanged.connect(self.preparation_changed)
        self.data_channel.currentIndexChanged.connect(self.plot_input)
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
        self.plan_changed()
        self.preparation_changed()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.inspector_pages.setCurrentIndex(index)
        self.page_title.setText(self.SECTIONS[index])
        self.page_subtitle.setText(self.SUBTITLES[index])
        self.inspector_title.setText(("Data inspector", "Analysis settings", "Explore & filter", "Run details")[index])
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

    def toggle_advanced(self, checked):
        self.advanced_settings.setVisible(checked)
        self.advanced_toggle.setText("Advanced parameters  ⌄" if checked else "Advanced parameters  ›")

    def show_notice(self, message):
        self.notice.setText(message)
        self.notice.setVisible(bool(message))

    def plan_changed(self, *_):
        plan = self.pipeline.currentText()
        for name, item in self.module_buttons.items():
            item.setChecked(name == plan or (plan == "Gait + tremor" and name in ("Gait", "Tremor")))
        self.module_requirements.setText({
            "Gait": "Requires numeric time, accelerometer and gyroscope channels.",
            "Tremor": "Requires numeric time and gyroscope channels.",
            "Gait + tremor": "Runs gait and tremor together. Requires accelerometer and gyroscope channels.",
            "Pulse rate": "Runs separately. Requires raw green PPG and accelerometer channels for raw-data preparation.",
        }[plan])

    def preparation_changed(self, *_):
        prepared = self.prepared.isChecked()
        for widget in (self.acc, self.gyro, self.time, self.orientation, self.gaps):
            widget.setEnabled(not prepared)
        for widget in (self.max_gap, self.min_segment):
            widget.setEnabled(not prepared and self.gaps.isChecked())
        if prepared:
            text = "Already prepared · relative seconds, g and deg/s expected"
        else:
            text = f"{self.acc.currentText()} · {self.gyro.currentText()} · {self.time.currentText()}"
        text += " · missing samples excluded" if self.drop_missing.isChecked() else " · strict sample validation"
        if self.gaps.isChecked() and not prepared:
            text += " · split at time gaps"
        self.preparation_summary.setText(text)

    def start_job(self, operation, completed):
        if self.worker is not None:
            return
        for widget in (self.open_button, self.run_button, self.settings_panel, self.analysis_controls,
                       self.export_button, self.csv_button, self.open_run_button, self.use_parameters_button):
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
        self.run_button.setEnabled(self.frame is not None)
        self.settings_panel.setEnabled(True)
        self.analysis_controls.setEnabled(True)
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
        self.start_job(lambda logger: (path, load_sensor_file(path, allow_pickle=allow_pickle)), self.loaded)

    def loaded(self, payload):
        self.source, self.frame = payload
        self.input_table.setModel(FrameModel(self.frame))
        self.file_label.setText(Path(self.source).name)
        self.file_label.setToolTip(self.source)
        self.analysis_input.setText(Path(self.source).name)
        self.analysis_input_detail.setText(f"{len(self.frame):,} samples · {len(self.frame.columns)} channels")
        self.data_values[0].setText(f"{len(self.frame):,}")
        self.data_values[1].setText(str(len(self.frame.columns)))
        self.data_values[2].setText(f"{int(self.frame.isna().sum().sum()):,}")
        metadata = {"source": self.source, "samples": len(self.frame),
                    "columns": {str(c): str(t) for c, t in self.frame.dtypes.items()}, "metadata": self.frame.attrs}
        self.data_metadata.setPlainText(json.dumps(metadata, indent=2, default=str))
        self.data_channel.blockSignals(True)
        self.data_channel.clear()
        for column in self.frame.select_dtypes(include="number").columns:
            if column != "time":
                self.data_channel.addItem(str(column), column)
        self.data_channel.blockSignals(False)
        self.plot_input()
        self.continue_button.setEnabled(True)
        self.run_button.setEnabled(self.worker is None)
        self.show_notice("")
        self.navigate(0)
        if self.frame.attrs.get("source_format") == "empatica" and not any(f"gyroscope_{axis}" in self.frame for axis in "xyz"):
            message = ("Empatica accelerometer samples loaded. Gait and tremor require gyroscope data; "
                       "pulse rate requires raw green PPG. This import contains neither.")
            self.status.setText(message)
            self.show_notice(message)
            self.append_log(message)
        else:
            self.status.setText("Recording loaded. Open Analyze to configure a run.")

    def plot_input(self, *_):
        self.data_figure.clear()
        ax = style_axes(self.data_figure)
        channel = self.data_channel.currentData()
        if self.frame is not None and channel in self.frame:
            step = max(1, int(np.ceil(len(self.frame) / 20000)))
            sample = self.frame.iloc[::step]
            times = pd.to_numeric(sample["time"], errors="coerce") if "time" in sample else None
            numeric_time = times is not None and times.notna().all()
            ax.plot(times if numeric_time else np.arange(len(self.frame))[::step], sample[channel], color="#2563a5", linewidth=1)
            ax.set_xlabel("Time (file units)" if numeric_time else "Sample position")
            ax.set_ylabel(str(channel))
        else:
            ax.text(.5, .5, "Open a recording with numeric sensor channels", ha="center", transform=ax.transAxes)
        self.data_canvas.draw_idle()

    def run_analysis(self):
        if self.worker is not None:
            return
        if self.frame is None:
            self.show_notice("Open a recording in Data before running an analysis.")
            self.navigate(0)
            return
        try:
            mapping = validate_column_mapping(json.loads(self.mapping.toPlainText()))
            axes = (["x", "y", "z"] if self.prepared.isChecked() else
                    validate_orientation([v.strip() for v in self.orientation.text().split(",")]))
            pipelines = {"Gait": ["gait"], "Tremor": ["tremor"],
                         "Gait + tremor": ["gait", "tremor"], "Pulse rate": ["pulse_rate"]}[self.pipeline.currentText()]
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
            message = "Analysis completed. Explore outputs in Overview, Graphs or Tables." if has_rows else "Analysis returned no quantified windows. Inspect Runs and recording requirements."
            self.status.setText(message)
            self.finish_run("Completed", [] if has_rows else [message])
        self.navigate(2)

    def select_dataset(self, name):
        frame = self.tables.get(name)
        self.hide_sensor_context()
        self.context_button.setEnabled(False)
        self.context_hint.setText("Select a row or click a time-based graph point. Context shows original samples near the timestamp." if self.result_source_frame is not None else
                                  "Sensor context requires the original recording from this session. Reopened JSON contains derived results only.")
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
            self.selection_note.setText("Run an analysis to explore its outputs.")
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
        self.selection_note.setText(f"{Path(source).name or 'Current analysis'} · {len(selected):,} of {len(frame):,} rows selected · graphs, tables and summaries share this selection")
        self.filter_status.setText(f"{len(selected):,} selected rows" + (" · no participant field" if self.participant_column is None else ""))
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
        self.summary_table.setModel(None)
        if frame is not None:
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
            self.overview_text.setText(f"Metric: {metric if metric is not None else 'choose a numeric column'} · {len(frame):,} selected rows")
        else:
            self.overview_text.setText("Run an analysis to explore its outputs.")
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
            self.context_hint.setText("This output has no explicit timestamp or gait-segment time metadata. No sensor timing will be inferred.")
        if self.result_source_frame is None:
            self.context_hint.setText("Sensor context requires the original recording from this session. Reopened JSON contains derived results only.")

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
        self.run_summary.setText(f"Started: {started}\nFinished: {finished}\nToolbox: {record.get('paradigma_version', '—')}\n\nSource: {record['source']}")
        self.run_details.setPlainText("\n".join(f"{key.replace('_', ' ').capitalize()}: {json.dumps(value, ensure_ascii=False)}" for key, value in record["settings"].items()))
        self.run_warnings.setPlainText("\n\n".join(str(value) for value in record["warnings"]) or "No recorded warnings.")
        self.run_outputs.setPlainText("\n\n".join(f"{item.get('kind', 'Export')}: {item.get('path', '')}" for item in record["outputs"]) or "No exports saved. Open results and export to choose an output location.")
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
        self.pipeline.setCurrentText({("gait",): "Gait", ("tremor",): "Tremor", ("gait", "tremor"): "Gait + tremor", ("pulse_rate",): "Pulse rate"}.get(tuple(settings.get("pipelines", [])), "Gait"))
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
