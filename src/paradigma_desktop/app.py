"""Native Qt application. File loading and analysis never block the UI thread."""
import json
import logging
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSplitter, QTableView, QTabWidget, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from .core import (
    analyze, export_results, export_table_csv, load_sensor_file, result_tables,
    validate_column_mapping, validate_orientation,
)


class FrameModel(QAbstractTableModel):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role == Qt.DisplayRole:
            return str(self.frame.iat[index.row(), index.column()])

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return str(self.frame.columns[section]) if orientation == Qt.Horizontal else str(section + 1)


class SignalHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        self.signal.emit(self.format(record))


class Worker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    message = Signal(str)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        logger = logging.Logger("paradigma-desktop", logging.INFO)
        handler = SignalHandler(self.message)
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ParaDigMa • Sensor analysis")
        self.resize(1250, 850)
        self.frame = self.results = self.worker = None
        self.source = ""
        self.tables = {}
        self.provenance = {}
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel("ParaDigMa sensor analysis")
        title.setStyleSheet("font-size: 24px; font-weight: 600; padding: 8px")
        layout.addWidget(title)
        toolbar = QHBoxLayout()
        self.open_button = QPushButton("Open sensor file…")
        self.open_button.clicked.connect(self.open_file)
        toolbar.addWidget(self.open_button)
        self.file_label = QLabel("No recording loaded")
        self.file_label.setTextFormat(Qt.PlainText)
        toolbar.addWidget(self.file_label, 1)
        self.run_button = QPushButton("Run ParaDigMa")
        self.run_button.clicked.connect(self.run_analysis)
        self.run_button.setEnabled(False)
        toolbar.addWidget(self.run_button)
        self.export_button = QPushButton("Export results…")
        self.export_button.clicked.connect(self.export)
        self.export_button.setEnabled(False)
        toolbar.addWidget(self.export_button)
        layout.addLayout(toolbar)
        split = QSplitter()
        layout.addWidget(split, 1)
        self.settings_panel = QWidget()
        settings = QFormLayout(self.settings_panel)
        self.pipeline = self.combo(["Gait", "Tremor", "Gait + tremor", "Pulse rate"])
        self.side = self.combo(["left", "right"])
        self.acc = self.combo(["g", "m/s^2"])
        self.gyro = self.combo(["deg/s", "rad/s"])
        self.time = self.combo(["relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"])
        self.orientation = QLineEdit("x,y,z")
        self.mapping = QPlainTextEdit("{}")
        self.mapping.setPlaceholderText('{"timestamp": "time", "ppg": "green"}')
        self.mapping.setMaximumHeight(120)
        self.prepared = QCheckBox("Already prepared (skip conversion)")
        self.gaps = QCheckBox("Split recordings at time gaps")
        self.gaps.setChecked(True)
        self.drop_missing = QCheckBox("Exclude missing sensor samples")
        self.drop_missing.setChecked(True)
        self.drop_missing.setToolTip("Exclude rows with missing/non-finite required samples, report the count, and process valid sections separately.")
        self.prepared.toggled.connect(self.preparation_changed)
        for name, widget in [("Pipeline", self.pipeline), ("Watch side", self.side),
                             ("Acceleration units", self.acc), ("Gyroscope units", self.gyro),
                             ("Time units", self.time), ("Device axes", self.orientation),
                             ("Column mapping (JSON)", self.mapping), ("", self.prepared), ("", self.gaps), ("", self.drop_missing)]:
            settings.addRow(name, widget)
        help_text = QLabel("Device axes: three signed axes, e.g. x,y,z or -y,x,z.\n\n"
                           "Gait: accelerometer + gyroscope.\nTremor: gyroscope.\n"
                           "Pulse rate: green PPG (accelerometer optional).\nAll require a numeric time column.\n\n"
                           "Choose units and orientation for your device before running.")
        help_text.setWordWrap(True)
        settings.addRow(help_text)
        split.addWidget(self.settings_panel)
        tabs = QTabWidget()
        split.addWidget(tabs)
        split.setStretchFactor(1, 1)
        self.input_table = QTableView()
        tabs.addTab(self.input_table, "Sensor samples")
        result_panel = QWidget()
        result_layout = QVBoxLayout(result_panel)
        controls = QHBoxLayout()
        self.dataset = QComboBox()
        self.dataset.currentTextChanged.connect(self.select_dataset)
        controls.addWidget(self.dataset, 1)
        self.csv_button = QPushButton("Export table CSV…")
        self.csv_button.clicked.connect(self.export_csv)
        self.csv_button.setEnabled(False)
        controls.addWidget(self.csv_button)
        result_layout.addLayout(controls)
        self.result_table = QTableView()
        result_layout.addWidget(self.result_table)
        plot_controls = QHBoxLayout()
        self.x_column = QComboBox()
        self.y_column = QComboBox()
        for label, widget in [("X", self.x_column), ("Y", self.y_column)]:
            plot_controls.addWidget(QLabel(label))
            plot_controls.addWidget(widget, 1)
            widget.currentIndexChanged.connect(self.plot)
        result_layout.addLayout(plot_controls)
        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        result_layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        result_layout.addWidget(self.canvas, 1)
        tabs.addTab(result_panel, "Results & plots")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        tabs.addTab(self.log, "Processing log")
        self.status = QLabel("Open a recording to begin. Analysis runs locally.")
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

    @staticmethod
    def combo(items):
        combo = QComboBox()
        combo.addItems(items)
        return combo

    def start_job(self, operation, completed):
        if self.worker is not None:
            return
        self.open_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.settings_panel.setEnabled(False)
        self.export_button.setEnabled(False)
        self.csv_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.worker = Worker(operation)
        self.worker.completed.connect(completed)
        self.worker.failed.connect(self.failure)
        self.worker.message.connect(self.log.appendPlainText)
        self.worker.finished.connect(self.job_finished)
        self.worker.start()

    def job_finished(self):
        self.open_button.setEnabled(True)
        self.run_button.setEnabled(self.frame is not None)
        self.settings_panel.setEnabled(True)
        self.preparation_changed()
        self.export_button.setEnabled(self.results is not None)
        self.csv_button.setEnabled(self.dataset.currentText() in self.tables)
        self.progress.hide()
        self.worker.deleteLater()
        self.worker = None

    def preparation_changed(self, *_):
        for widget in (self.acc, self.gyro, self.time, self.orientation, self.gaps):
            widget.setEnabled(not self.prepared.isChecked())

    def failure(self, message):
        self.status.setText("Operation failed. See the processing log.")
        self.log.appendPlainText(message)
        QMessageBox.critical(self, "Processing failed", message)

    def clear_results(self):
        self.results = None
        self.tables = {}
        self.dataset.clear()
        self.result_table.setModel(None)
        self.export_button.setEnabled(False)
        self.csv_button.setEnabled(False)
        self.figure.clear()
        self.canvas.draw_idle()

    def open_file(self):
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
        self.status.setText("Loading recording…")
        self.start_job(lambda logger: (path, load_sensor_file(path, allow_pickle=allow_pickle)), self.loaded)

    def loaded(self, payload):
        self.source, self.frame = payload
        self.clear_results()
        self.input_table.setModel(FrameModel(self.frame))
        self.file_label.setText(f"{Path(self.source).name} • {len(self.frame):,} samples")
        self.file_label.setToolTip(self.source)
        if self.frame.attrs.get("source_format") == "empatica" and not any(
            f"gyroscope_{axis}" in self.frame for axis in "xyz"
        ):
            message = ("Empatica accelerometer samples loaded. Gait and tremor require gyroscope data; "
                       "pulse rate requires raw green PPG. This import contains neither.")
            self.status.setText(message)
            self.log.appendPlainText(message)
        else:
            self.status.setText("Recording loaded. Review settings, then run analysis.")

    def run_analysis(self):
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
                            split_by_gaps=self.gaps.isChecked(), drop_missing_samples=self.drop_missing.isChecked())
            if self.prepared.isChecked():
                settings.update(accelerometer_units="g", gyroscope_units="deg/s",
                                time_input_unit="relative_s", split_by_gaps=False)
        except (ValueError, KeyError) as exc:
            self.failure(str(exc))
            return
        self.clear_results()
        self.provenance = {"source": self.source, "paradigma_version": version("paradigma"), "settings": settings}
        self.log.clear()
        self.status.setText("Running ParaDigMa…")
        self.start_job(lambda logger: analyze(self.frame, logger=logger, **settings), self.analyzed)

    def analyzed(self, results):
        self.results = results
        self.tables = result_tables(results)
        self.dataset.addItems(self.tables)
        self.export_button.setEnabled(True)
        errors = results.get("errors", [])
        if errors:
            self.log.appendPlainText(json.dumps(errors, indent=2, default=str))
            self.status.setText(f"Analysis returned {len(errors)} processing error(s); inspect the log and partial results.")
            QMessageBox.warning(self, "Incomplete analysis", self.status.text())
        else:
            has_rows = any(len(v) for k, v in self.tables.items() if k.startswith("quantifications/"))
            self.status.setText("Analysis completed. Select an output and numeric columns to plot." if has_rows
                                else "Analysis returned no quantified windows. Inspect the log and recording requirements.")

    def select_dataset(self, name):
        frame = self.tables.get(name)
        self.x_column.blockSignals(True)
        self.y_column.blockSignals(True)
        self.x_column.clear()
        self.y_column.clear()
        self.csv_button.setEnabled(frame is not None)
        self.result_table.setModel(None)
        if frame is not None:
            self.result_table.setModel(FrameModel(frame))
            numeric = list(frame.select_dtypes(include="number").columns)
            self.x_column.addItem("Row number", userData=None)
            for column in numeric:
                label = "Row number (column)" if column == "Row number" else str(column)
                self.x_column.addItem(label, userData=column)
                self.y_column.addItem(str(column), userData=column)
            if "time" in numeric:
                self.x_column.setCurrentText("time")
            self.y_column.setCurrentIndex(1 if numeric and numeric[0] == "time" and len(numeric) > 1 else 0)
        self.x_column.blockSignals(False)
        self.y_column.blockSignals(False)
        self.plot()

    def plot(self, *_):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        frame = self.tables.get(self.dataset.currentText())
        y = self.y_column.currentData()
        x = self.x_column.currentData()
        row_number = self.x_column.currentIndex() == 0
        if frame is not None and y in frame and (row_number or x in frame) and len(frame):
            # Bound rendering cost; the table and exports retain every row.
            step = max(1, int(np.ceil(len(frame) / 20000)))
            sample = frame.iloc[::step]
            xv = np.arange(len(frame))[::step] if row_number else sample[x]
            ax.plot(xv, sample[y], linewidth=1)
            ax.set_xlabel(self.x_column.currentText())
            ax.set_ylabel(self.y_column.currentText())
            ax.set_title(self.dataset.currentText())
            ax.grid(alpha=0.2)
        else:
            ax.text(0.5, 0.5, "Select a non-empty numeric output to visualize", ha="center", transform=ax.transAxes)
        self.canvas.draw_idle()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export complete results", "paradigma-results.json", "JSON (*.json)")
        if path:
            try:
                export_results(path, self.results, self.provenance)
                self.status.setText(f"Results exported to {path}")
            except Exception as exc:
                self.failure(str(exc))

    def export_csv(self):
        frame = self.tables.get(self.dataset.currentText())
        if frame is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export selected table", "output.csv", "CSV (*.csv)")
        if path:
            try:
                export_table_csv(path, frame, source=self.source)
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
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
