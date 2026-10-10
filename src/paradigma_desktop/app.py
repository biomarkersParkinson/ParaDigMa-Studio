"""Native scientific workspace with separate configuration and exploration."""

import json
from threading import Event
from collections import OrderedDict
import sys
from importlib.metadata import version
from pathlib import Path
from datetime import datetime

import numpy as np
from PySide6.QtCore import Qt, QStandardPaths, QItemSelectionModel
from PySide6.QtGui import QIcon, QColor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QWidget,
    QMessageBox,
    QTreeWidgetItem,
    QGridLayout,
)
from .bootstrap import PLOT_CACHE_DIRECTORY as PLOT_CACHE_DIRECTORY


from .core import (
    analyze as analyze,
    export_results,
    export_table_csv,
    load_sensor_file as load_sensor_file,
    validate_column_mapping,
    validate_orientation,
)
from .exploration import SensorContext, gait_context, source_timeline
from .sensor_navigation import SensorNavigator, SensorTimeIndex
from .recordings import load_recordings, align_recordings, source_key
from .history import RunHistory, merge_errors, run_status, load_result_export, new_run, now
from .inspection import inspect_recording, sensor_descriptives, time_descriptives
from .results_view import (
    MODULE_NAMES,
    clock_times,
    clock_origin,
    flat_values,
    analysis_alignment,
    output_label,
    plot_metrics,
    preferred_metric,
    recording_clock,
    normalise_clock,
    readable_key,
    gait_model_threshold,
    tremor_overview_entries,
)
from .theme import STYLESHEET, light_palette, module_color
from .analysis_help import DEFAULT_MAX_GAP_SECONDS, DEFAULT_MIN_SECTION_SECONDS
from .previews import CachedPreview
from .overview import recording_extent, recording_summary
from .analysis_process import run_isolated_analysis
from .result_data import prepare_result_data, detail_table_view
from .assets import DATA_DIRECTORY
from .branding import APP_NAME, USER_DATA_DIRECTORY
from .ui.layout import WorkspaceLayout
from .ui.result_graphs import ResultGraphs
from .channels import (
    selected_channels,
    check_channels,
    populate_channels,
    plot_channel_signals,
    mark_sensor_time,
)
from .jobs import Worker, SignalHandler as SignalHandler
from .widgets import ReadableTable as ReadableTable

from .widgets import FrameModel, RecordModel, WrappedForm, label, card


class MainWindow(WorkspaceLayout, ResultGraphs, QMainWindow):
    selected_channels = staticmethod(selected_channels)
    check_channels = staticmethod(check_channels)
    populate_channels = staticmethod(populate_channels)
    plot_channel_signals = staticmethod(plot_channel_signals)

    SECTIONS = ("Data", "Analyze", "Results", "Runs")
    MODULES = {"Gait": "gait", "Tremor": "tremor", "Pulse rate": "pulse_rate"}

    def __init__(self, history_dir=None):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} • Sensor analysis")
        self.setWindowIcon(QIcon(str(DATA_DIRECTORY / "app-icon.png")))
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
        self._interval_ends, self._bar_bounds = {}, {}
        self._plot_tables, self._plot_labels = {}, {}
        self._result_selection_artists = []
        self._plot_signature = None
        self._result_shared_axes = None
        self._epoch_views = {}
        self._epoch_presence_views = {}
        self._gait_presence_cache = None
        self._gait_epoch_cache = None
        self._table_views = OrderedDict()
        self._result_layout_index = None
        self.display_clock = None
        self._origin_override = False
        self._origin_preview = CachedPreview(self)
        self._origin_preview.value_ready.connect(self.apply_origin_preview)
        self._origin_preview.failed.connect(self.append_log)
        self._time_preview = CachedPreview(self)
        self._time_preview.value_ready.connect(self.apply_time_preview)
        self._time_preview.failed.connect(self.append_log)
        self._sensor_preview = CachedPreview(self)
        self._sensor_preview.value_ready.connect(self.apply_sensor_preview)
        self._sensor_preview.failed.connect(self.append_log)
        self._data_plot_dirty = False
        self._source_timelines, self._display_offsets = {}, {}
        self.active_frame = None
        self.active_positions = np.array([], dtype=int)
        self.active_selection = {}
        self.result_source_frame = None
        self.result_timeline = None
        self.sensor_frame = None
        self._sensor_context = None
        self._sensor_navigator = None
        self._sensor_time_indices = OrderedDict()
        self._sensor_view_callbacks = {}
        self.active_run = self.current_run = self.selected_run = None
        self.sidebar_collapsed = True
        directory = (
            history_dir
            or Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation))
            / USER_DATA_DIRECTORY
            / "runs"
        )
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

    def toggle_analysis_help(self, title, checked):
        if self._updating_analysis_help:
            return
        self._updating_analysis_help = True
        body = self.analysis_scroll.widget()
        updates = body.updatesEnabled()
        body.setUpdatesEnabled(False)
        try:
            if checked:
                for other_title, (info, _) in self.analysis_help.items():
                    if other_title != title:
                        info.setChecked(False)
            for name, (info, description) in self.analysis_help.items():
                description.setVisible(info.isChecked())
                self.analysis_help_sections[name].setVisible(info.isChecked())
            self.analysis_help_panel.setVisible(
                any(info.isChecked() for info, _ in self.analysis_help.values())
            )
            # Fit the fixed-height wrapper synchronously. Activating its layout
            # alone still uses the old height until a queued LayoutRequest,
            # which can paint the help over the parameter card in the meantime.
            for widget in (self.analysis_help_panel, self.analysis_controls, body):
                if isinstance(widget, WrappedForm):
                    widget._fit_height()
                widget.layout().activate()
        finally:
            body.setUpdatesEnabled(updates)
            self._updating_analysis_help = False

    def _connect(self):
        self.result_graph_view.currentIndexChanged.connect(self.plot)
        self.data_tabs.currentChanged.connect(self.data_tab_changed)
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
        self.clock_input.valueEdited.connect(self.origin_edited)
        self.mapping.textChanged.connect(self.update_origin_default)
        self.mapping.textChanged.connect(self.input_mapping_changed)
        for control in (self.time,):
            control.currentTextChanged.connect(self.update_origin_default)
        for control in (self.prepared, self.drop_missing):
            control.toggled.connect(self.update_origin_default)
        self.sensor_channels.itemChanged.connect(self.plot_sensor)
        self.sensor_toolbar.home_callback = self.reset_sensor_context
        self.canvas.mpl_connect("button_press_event", self.graph_clicked)
        self.modules_changed()
        self.preparation_changed()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.continue_button.setVisible(index == 0)
        self.stop_button.setVisible(index == 1)
        self.run_button.setVisible(index == 1)
        self.page_title.setText(self.SECTIONS[index])
        for i, item in enumerate(self.nav_buttons):
            item.setChecked(i == index)
        if index == 0:
            self.data_tab_changed(self.data_tabs.currentIndex())

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
        return [
            self.MODULES[name] for name, item in self.module_buttons.items() if item.isChecked()
        ]

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
        self.module_requirements.setText(
            text[0].upper() + text[1:] + " required." if text else "Select an analysis module."
        )
        self.run_button.setEnabled(
            self.frame is not None and bool(selected) and self.worker is None
        )
        self.update_origin_default()

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
        for widget in (
            self.open_button,
            self.run_button,
            self.settings_panel,
            self.analysis_controls,
            self.export_button,
            self.open_run_button,
            self.use_parameters_button,
            self.delete_run_button,
            self.clear_runs_button,
            self.data_time_channel,
            self.data_time_unit,
            self.input_recording,
        ):
            widget.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.worker = Worker(operation)
        self.worker.completed.connect(completed)
        self.worker.failed.connect(self.failure)
        self.worker.cancelled.connect(self.analysis_cancelled)
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
        self.stop_button.setEnabled(False)
        self._analysis_stop = None
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
            self.run_warnings.setPlainText(
                "\n\n".join(record["warnings"]) or "No recorded warnings."
            )
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
            self.show_notice(
                f"Analysis remains available, but run history could not be saved: {exc}"
            )

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
        self.disconnect_sensor_view()
        for toolbar in (self.plot_toolbar, self.sensor_toolbar):
            if toolbar._pan_info is not None:
                toolbar.release_pan(None)
        self._plot_signature = None
        self._result_shared_axes = None
        self._result_selection_artists.clear()
        self._epoch_views.clear()
        self._epoch_presence_views.clear()
        self._gait_presence_cache = self._gait_epoch_cache = None
        self._table_views.clear()
        self.result_overlay.invalidate()
        self.results, self.active_frame = None, None
        self.display_clock = None
        self._source_timelines, self._display_offsets = {}, {}
        self.tables = {}
        self.aggregation_tables, self._table_choices = {}, {}
        self._timings, self._detail_selections, self._series_items = {}, {}, {}
        self._interval_ends, self._bar_bounds = {}, {}
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
        self.hide_sensor_context()
        self.display_frame = self.sensor_frame = self.sensor_times = None
        self._sensor_context = None
        self._sensor_navigator = None
        self._sensor_time_indices.clear()
        self.sensor_table.setModel(None)
        self.sensor_figure.clear()
        self.context_button.setEnabled(False)
        self.figure.clear()
        self.time_axis.bind(None)
        self.plot_toolbar.refresh()
        self.sensor_toolbar.refresh()
        self.canvas.draw_idle()

    def open_file(self):
        if self.worker is not None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open recordings for the same subject",
            "",
            "Sensor files (*.csv *.parquet *.pkl *.pickle *.json *.avro *.cwa *.CWA);;All files (*)",
        )
        if not paths:
            return
        allow_pickle = False
        if any(Path(path).suffix.lower() in (".pkl", ".pickle") for path in paths):
            reply = QMessageBox.warning(
                self,
                "Trusted pickle files only",
                "Pickle files can execute code when opened. Only continue if you trust every selected pickle file's source.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
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
        self._origin_preview.clear()
        self._time_preview.clear()
        self._sensor_preview.clear()
        self.input_recording.blockSignals(True)
        self.input_recording.clear()
        for key, path in sources.items():
            self.input_recording.addItem(f"{key} · {Path(path).name}", key)
            self.input_recording.setItemData(self.input_recording.count() - 1, path, Qt.ToolTipRole)
        self.input_recording.blockSignals(False)
        self.sources, self.recordings = sources, recordings
        self._input_descriptions = descriptions
        self._origin_override = False
        self.inspect_input_recording(new_selection=True)
        self.modules_changed()
        self.status.setText(f"{len(recordings)} recordings loaded for one subject.")

    def inspect_input_recording(self, *_, new_selection=False):
        key = self.input_recording.currentData()
        if key not in self.recordings:
            return
        self.source, self.frame = self.sources[key], self.recordings[key]
        self.display_input_recording(self._input_descriptions[key], new_selection=new_selection)
        self.input_recording.show()
        self.file_label.setText(f"{len(self.recordings)} recordings")
        self.file_label.setToolTip("\n".join(self.sources.values()))
        self.analysis_input.setText(f"{len(self.recordings)} recordings · One subject")
        self.analysis_input_detail.setText(
            f"{sum(len(frame) for frame in self.recordings.values()):,} samples"
        )

    def loaded(self, payload):
        self._origin_preview.clear()
        self._time_preview.clear()
        self._sensor_preview.clear()
        self.source, self.frame = payload[:2]
        self._origin_override = False
        self.sources, self.recordings = {"recording_001": self.source}, {}
        self._input_descriptions = {}
        self.input_recording.hide()
        description = (
            payload[2]
            if len(payload) > 2
            else inspect_recording(self.frame, self.time.currentText())
        )
        self.display_input_recording(description, new_selection=True)
        self.modules_changed()
        self.show_notice("")
        self.navigate(0)
        if self.frame.attrs.get("source_format") == "empatica" and not any(
            f"gyroscope_{axis}" in self.frame for axis in "xyz"
        ):
            message = (
                "Empatica accelerometer samples loaded. Gait and tremor require gyroscope data; "
                "pulse rate requires raw green PPG. This import contains neither."
            )
            self.status.setText(message)
            self.show_notice(message)
            self.append_log(message)
        else:
            self.status.setText("Recording loaded.")

    def display_input_recording(self, description, *, new_selection):
        """Refresh inspection only; changing the viewed file never realigns the batch."""
        self._time_preview.cancel_pending()
        self.time_table.setEnabled(True)
        self._sensor_preview.cancel_pending()
        self.channel_table.setEnabled(True)
        channels = None if new_selection else self.selected_input_channels()
        if new_selection:
            self.data_tabs.setCurrentIndex(0)
        self.input_table.setModel(FrameModel(self.frame))
        self.file_label.setText(Path(self.source).name)
        self.file_label.setToolTip(self.source)
        self.analysis_input.setText(Path(self.source).name)
        self.analysis_input_detail.setText(
            f"{len(self.frame):,} samples · {len(self.frame.columns)} channels"
        )
        self.data_values[0].setText(f"{len(self.frame):,}")
        self.data_values[1].setText(str(len(self.frame.columns)))
        self.data_values[2].setText(f"{description['missing']:,}")
        self.data_time_channel.blockSignals(True)
        self.data_time_channel.clear()
        for column in self.frame:
            self.data_time_channel.addItem(str(column), column)
        self.data_time_channel.setCurrentIndex(
            self.data_time_channel.findData(description["time_column"])
        )
        self.data_time_channel.blockSignals(False)
        self.data_time_unit.blockSignals(True)
        self.data_time_unit.setCurrentText(description["time_unit"])
        self.data_time_unit.blockSignals(False)
        self.channel_table.setModel(FrameModel(description["sensors"], compact=True))
        self.time_table.setModel(
            FrameModel(description["time"], compact=True)
            if description["time"] is not None
            else None
        )
        self.update_time_unit_control()
        self.populate_input_channels(channels)
        if new_selection or self.data_tabs.currentIndex() == 1:
            self.plot_input()
        else:
            self._data_plot_dirty = True
        self.continue_button.setEnabled(True)

    def data_tab_changed(self, index):
        if index == 1 and self._data_plot_dirty:
            self.plot_input()

    def update_time_unit_control(self):
        import pandas as pd

        column = self.data_time_channel.currentData()
        numeric_time = (
            self.frame is not None
            and column in self.frame
            and not (
                pd.api.types.is_datetime64_any_dtype(self.frame[column].dtype)
                or pd.api.types.is_timedelta64_dtype(self.frame[column].dtype)
            )
        )
        self.data_time_unit.setVisible(numeric_time)
        self.data_time_unit.setEnabled(self.worker is None)

    def refresh_data_descriptives(self, *_):
        if self.frame is not None:
            frame, column = self.frame, self.data_time_channel.currentData()
            self.channel_table.setEnabled(False)
            self._sensor_preview.request(
                (self.source, column), lambda: sensor_descriptives(frame, column)
            )
            self.populate_input_channels(self.selected_input_channels())
            self.update_time_statistics()
            if self.data_tabs.currentIndex() == 1:
                self.plot_input()
            else:
                self._data_plot_dirty = True

    def apply_sensor_preview(self, description):
        self.channel_table.setModel(
            FrameModel(description, compact=True) if description is not None else None
        )
        self.channel_table.setEnabled(True)

    def update_time_statistics(self, *_):
        column = self.data_time_channel.currentData()
        if self.frame is not None and column in self.frame:
            frame, unit = self.frame, self.data_time_unit.currentText()
            self.time_table.setEnabled(False)
            self._time_preview.request(
                (self.source, column, unit), lambda: time_descriptives(frame[column], unit)
            )
        else:
            self._time_preview.cancel_pending()
            self.time_table.setModel(None)
            self.time_table.setEnabled(True)
        self.update_time_unit_control()

    def apply_time_preview(self, description):
        self.time_table.setModel(
            FrameModel(description, compact=True) if description is not None else None
        )
        self.time_table.setEnabled(True)

    def selected_input_channels(self):
        return self.selected_channels(self.data_channels)

    def set_input_channels(self, channels):
        self.check_channels(self.data_channels, channels)
        self.plot_input()

    def populate_input_channels(self, selection=None):
        self._channel_colors = self.populate_channels(
            self.data_channels,
            self.frame,
            excluded={self.data_time_channel.currentData()},
            selection=selection,
        )

    def input_mapping_changed(self):
        self._data_plot_dirty = True
        if self.pages.currentIndex() == 0:
            self.data_tab_changed(self.data_tabs.currentIndex())

    def plot_input(self, *_):
        import pandas as pd

        self._data_plot_dirty = False
        try:
            mapping = validate_column_mapping(json.loads(self.mapping.toPlainText()))
        except (ValueError, TypeError):
            # An incomplete Analyze mapping must not prevent original-data inspection.
            mapping = {}
        channels = self.selected_input_channels()
        times, time_label, timezone = None, "Time (file units)", None
        if self.frame is not None:
            column = self.data_time_channel.currentData()
            if column in self.frame:
                series = self.frame[column]
                if pd.api.types.is_datetime64_any_dtype(series.dtype):
                    times, time_label, timezone = series, "Time", series.dt.tz
                elif pd.api.types.is_timedelta64_dtype(series.dtype):
                    times, time_label = series.dt.total_seconds(), "Time (s)"
                elif not pd.api.types.is_complex_dtype(series.dtype):
                    times = pd.to_numeric(series, errors="coerce")
        usable = times is not None and times.notna().all()
        xs = times if usable else np.arange(len(self.frame)) if self.frame is not None else []
        self.plot_channel_signals(
            self.data_figure,
            self.frame,
            channels,
            self._channel_colors,
            xs,
            time_label if usable else "Sample position",
            column_mapping=mapping,
            timezone=timezone,
            calendar=usable and pd.api.types.is_datetime64_any_dtype(times.dtype),
            empty_text="Open a recording with numeric sensor channels",
        )
        self.data_toolbar.refresh()
        self.data_canvas.draw_idle()

    def origin_edited(self):
        self._origin_override = True
        self._origin_preview.cancel_pending()
        self.clock_input.setEnabled(True)

    def reset_origin(self):
        self._origin_override = False
        self.update_origin_default()

    def update_origin_default(self, *_):
        if self._origin_override or self.frame is None:
            return
        try:
            settings = {
                "time_input_unit": self.time.currentText(),
                "skip_preparation": self.prepared.isChecked(),
                "column_mapping": validate_column_mapping(json.loads(self.mapping.toPlainText())),
                "pipelines": self.selected_modules(),
                "drop_missing_samples": self.drop_missing.isChecked(),
            }
        except (ValueError, TypeError, KeyError, OverflowError):
            self._origin_preview.cancel_pending()
            self.apply_origin_preview(None)
            return
        frame, recordings = self.frame, self.recordings
        key = json.dumps(settings, sort_keys=True)
        if self._origin_preview.is_requested(key):
            return

        def preview():
            if recordings:
                return align_recordings(recordings, settings, {})[3]
            timeline = analysis_alignment(frame, settings, {})[0]
            return recording_clock(frame, settings, timeline)

        self.clock_input.setEnabled(False)
        self._origin_preview.request(key, preview)

    def apply_origin_preview(self, clock):
        if self._origin_override:
            return
        self.clock_input.set_clock(clock)
        self.clock_input.setText(clock["origin"] if clock else "")
        self.clock_input.setEnabled(True)

    def origin_setting(self):
        if not self._origin_override:
            return {"mode": "automatic"}
        entered = self.clock_input.text().strip()
        if not entered:
            return {"mode": "elapsed"}
        clock = self.clock_input._clock
        return {
            "mode": "custom",
            "clock": normalise_clock(
                {
                    "origin": entered,
                    "source": "User supplied",
                    "timezone": clock.get("timezone") if clock else None,
                }
            ),
        }

    def stop_analysis(self):
        cancel = getattr(self, "_analysis_stop", None)
        if self.worker is not None and cancel is not None:
            cancel.set()
            self.stop_button.setEnabled(False)
            self.status.setText("Stopping analysis…")

    def analysis_cancelled(self):
        self.append_log("Analysis stopped by the user.")
        self.finish_run("Cancelled")
        self.status.setText("Analysis cancelled.")
        self.show_notice("")

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
            axes = (
                ["x", "y", "z"]
                if self.prepared.isChecked()
                else validate_orientation([v.strip() for v in self.orientation.text().split(",")])
            )
            settings = dict(
                pipelines=pipelines,
                watch_side=self.side.currentText(),
                accelerometer_units=self.acc.currentText(),
                gyroscope_units=self.gyro.currentText(),
                time_input_unit=self.time.currentText(),
                device_orientation=axes,
                column_mapping=mapping,
                skip_preparation=self.prepared.isChecked(),
                split_by_gaps=self.gaps.isChecked(),
                drop_missing_samples=self.drop_missing.isChecked(),
                max_gap_seconds=self.max_gap.value(),
                min_segment_seconds=self.min_segment.value(),
            )
            settings["plot_time_origin"] = self.origin_setting()
            if self.prepared.isChecked():
                settings.update(
                    accelerometer_units="g",
                    gyroscope_units="deg/s",
                    time_input_unit="relative_s",
                    split_by_gaps=False,
                )
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
        self.provenance = {
            "source": self.source,
            "paradigma_version": record["paradigma_version"],
            "settings": settings,
            "run_id": record["id"],
        }
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
        core_settings = dict(settings)
        core_settings.pop("plot_time_origin", None)
        self._analysis_stop = Event()
        cancel = self._analysis_stop
        self.start_job(
            lambda logger: run_isolated_analysis(frame, core_settings, logger, cancel),
            self.analyzed,
        )
        self.stop_button.setEnabled(self.worker is not None)

    def results_tab_changed(self, index):
        if index < 0:
            return
        body = self._result_view_layouts[index]
        # The tab bar stays outside every view's scrolling content. Shared
        # controls move below it rather than changing the navigation position.
        if index != self._result_layout_index:
            for widget in (self.results_header, self.detail_controls):
                for previous in self._result_view_layouts:
                    previous.removeWidget(widget)
            body.insertWidget(0, self.results_header)
            body.insertWidget(1, self.detail_controls)
            self.graph_footer_layout.removeWidget(self.context_controls)
            self.table_actions_layout.removeWidget(self.context_controls)
            if index == 1:
                self.graph_footer_layout.addWidget(self.context_controls, alignment=Qt.AlignRight)
            else:
                self.table_actions_layout.addWidget(self.context_controls, alignment=Qt.AlignRight)
            self._result_layout_index = index
        self.results_scroll = self._result_view_scrolls[index]
        aggregation = index == 2 and self.table_dataset.currentData() in self.aggregation_tables
        detailed = index in (1, 2) and not aggregation
        self.results_header.show()
        self.sensor_close.setVisible(index == self.sensor_tab_index)
        self.detail_controls.setVisible(index == 2)
        self.context_controls.setVisible(detailed)
        self.dataset_field.setVisible(index == 2)
        self.table_module_tabs.setVisible(index == 2)
        self.timing_toggle.setVisible(index == 2 and not aggregation)
        self.selection_note.setVisible(index == 2)

    def sync_table_outputs(self, force_detail=False):
        names = [*self.tables, *self.aggregation_tables]
        name = self.dataset.currentText()
        if (
            force_detail
            and name in self.tables
            and name == self.table_dataset.currentData()
            and tuple(names) == getattr(self, "_table_output_names", None)
        ):
            return
        self._table_output_names = tuple(names)
        modules = list(dict.fromkeys([*MODULE_NAMES, *(name.split("/")[1] for name in names)]))
        available = {
            module: any(name.split("/")[1] == module for name in names) for module in modules
        }
        current = self.table_module_tabs.tabData(self.table_module_tabs.currentIndex())
        name = self.dataset.currentText()
        if force_detail and name in self.tables:
            current = name.split("/")[1]
            self._table_choices[current] = name
        if not available.get(current):
            current = next((module for module in modules if available[module]), modules[0])
        previous = self.table_module_tabs.blockSignals(True)
        if modules != [
            self.table_module_tabs.tabData(i) for i in range(self.table_module_tabs.count())
        ]:
            while self.table_module_tabs.count():
                self.table_module_tabs.removeTab(0)
            for module in modules:
                index = self.table_module_tabs.addTab(
                    MODULE_NAMES.get(module, module.replace("_", " ").title())
                )
                self.table_module_tabs.setTabData(index, module)
        for index, module in enumerate(modules):
            self.table_module_tabs.setTabEnabled(index, available[module])
            self.table_module_tabs.setTabTextColor(index, QColor(module_color(module)))
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
            preferred = next(
                (
                    name
                    for name in names
                    if name.startswith("quantifications/") and len(tables[name])
                ),
                names[0] if names else None,
            )
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

    def build_result_overview(self, prepared_views=None):
        while self.overview_layout.count():
            item = self.overview_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.overview_values = {}
        self.overview_module_cards = {}
        self.overview_gait_charts = {}
        results = self.results or {}
        entries = recording_summary(results, self.provenance, self.display_clock, prepared_views)
        if entries:
            panel = QWidget()
            panel.setObjectName("recordingOverviewFields")
            grid = QGridLayout(panel)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(10)
            index = 0
            for title, value in entries:
                box, inside = card()
                inside.setAlignment(Qt.AlignTop)
                heading = label(title, "muted")
                heading.setWordWrap(True)
                inside.addWidget(heading)
                display = label(str(value), "metricValue")
                display.setWordWrap(True)
                inside.addWidget(display)
                if title == "Recording timespan":
                    index = (index + 2) // 3 * 3
                    grid.addWidget(box, index // 3, 0, 1, 3)
                    box.setToolTip("Recording extent includes the final sample interval.")
                    index += 3
                else:
                    grid.addWidget(box, index // 3, index % 3)
                    if title.endswith("Gaps"):
                        box.setToolTip(
                            "Interruptions between prepared-data intervals.\nLeading and trailing exclusions reduce coverage but are not counted as gaps."
                        )
                    index += 1
            self.overview_layout.addWidget(panel)
        modules = list(
            dict.fromkeys(
                [
                    *results.get("aggregations", {}),
                    *results.get("metadata", {}),
                    *results.get("quantifications", {}),
                    *results.get("classifications", {}),
                ]
            )
        )
        modules = [
            name
            for name in modules
            if name in MODULE_NAMES
            or not name.startswith("desktop_")
            and any(
                name in results.get(stage, {})
                for stage in ("classifications", "quantifications", "aggregations")
            )
        ]
        if not modules:
            self.overview_layout.addWidget(
                label("Run an analysis to see module aggregates.", "muted")
            )
        for module in modules:
            panel, content = card()
            panel.setProperty("analysisModule", module)
            self.overview_module_cards[module] = panel
            heading = label(MODULE_NAMES.get(module, module.replace("_", " ").title()), "pageTitle")
            heading.setProperty("analysisModule", module)
            content.addWidget(heading)
            for error in results.get("errors", []):
                if isinstance(error, dict) and (
                    error.get("pipeline") == module or module in error.get("pipelines", [])
                ):
                    content.addWidget(label(str(error.get("error", "Processing failed")), "notice"))
            if module == "tremor":
                grid = QGridLayout()
                grid.setSpacing(10)
                for index, (group, path, title, value, explanation) in enumerate(
                    tremor_overview_entries(results)
                ):
                    box, inside = card()
                    box.setToolTip(explanation)
                    inside.addWidget(label(title, "muted"))
                    try:
                        number = float(value)
                        text = f"{number:.2f}" if np.isfinite(number) else "—"
                    except (TypeError, ValueError, OverflowError):
                        text = "—"
                    display = label(text, "metricValue")
                    display.setToolTip(str(value))
                    inside.addWidget(display)
                    self.overview_values[module, group, path] = display
                    grid.addWidget(box, index // 3, index % 3)
                content.addLayout(grid)
                self.overview_layout.addWidget(panel)
                continue
            aggregate_entries = list(flat_values(results.get("aggregations", {}).get(module, {})))
            if module == "gait":
                from .gait_overview import build_gait_charts

                charts, self.overview_gait_charts, chart_paths = build_gait_charts(
                    results.get("aggregations", {}).get(module, {}),
                    metadata=results.get("metadata", {}).get(module, {}),
                    scroll_area=self._result_view_scrolls[0],
                )
                for chart in charts:
                    content.addWidget(chart)
                aggregate_entries = [
                    (path, value) for path, value in aggregate_entries if path not in chart_paths
                ]
            groups = [("Aggregates", aggregate_entries)]
            metadata = results.get("metadata", {}).get(module, {})
            groups.append(("Metadata", list(flat_values(metadata))))
            for heading, entries in groups:
                if not entries:
                    if heading == "Aggregates" and not (
                        module == "gait" and self.overview_gait_charts
                    ):
                        content.addWidget(label("No aggregates returned for this module.", "muted"))
                    continue
                content.addWidget(label(heading, "sectionTitle"))
                grid = QGridLayout()
                grid.setSpacing(10)
                for index, (path, value) in enumerate(entries):
                    box, inside = card()
                    title = " · ".join(readable_key(part) for part in path) or "Value"
                    box.setToolTip(" / ".join(path))
                    inside.addWidget(label(title, "muted"))
                    if (
                        value is None
                        or isinstance(value, (float, np.floating))
                        and not np.isfinite(value)
                    ):
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
        self.overview_layout.addStretch()

    def populate_result_series(self):
        self.result_series.blockSignals(True)
        self.result_series.clear()
        self._series_items = {}
        roots, default_modules = {}, set()
        title_counts = {}
        module_order = {
            module: index for index, module in enumerate((*MODULE_NAMES, "preparation"))
        }
        names = sorted(
            self._plot_tables,
            key=lambda name: module_order.get(
                "preparation" if name.startswith("preparation/") else name.split("/")[1],
                len(module_order),
            ),
        )
        for name in names:
            frame = self._plot_tables[name]
            module = "preparation" if name.startswith("preparation/") else name.split("/")[1]
            for metric in plot_metrics(name, frame):
                title = self._plot_labels.get((name, metric), str(metric).replace("_", " "))
                title_counts[module, title] = title_counts.get((module, title), 0) + 1
        for name in names:
            frame = self._plot_tables[name]
            module = "preparation" if name.startswith("preparation/") else name.split("/")[1]
            if module not in roots:
                root = QTreeWidgetItem(
                    self.result_series,
                    [
                        MODULE_NAMES.get(
                            module, "Data coverage" if module == "preparation" else module.title()
                        )
                    ],
                )
                root.setForeground(0, QColor(module_color(module)))
                root.setFlags(root.flags() & ~Qt.ItemIsUserCheckable)
                root.setExpanded(True)
                roots[module] = root
            metrics = plot_metrics(name, frame)
            default = preferred_metric(name, frame)
            # Favor unfiltered gait and quantified outputs for initial plots.
            choose = (
                len(frame) > 0
                and name.startswith("quantifications/")
                and module not in default_modules
                and (
                    not name.endswith("/filtered")
                    or not len(self.tables.get("quantifications/gait/unfiltered", []))
                )
            )
            for metric in metrics:
                title = self._plot_labels.get((name, metric), str(metric).replace("_", " "))
                if (
                    module != "preparation"
                    and len(name.split("/")) > 2
                    and not (module == "gait" and (name, metric) in self._plot_labels)
                ):
                    title += (
                        " ("
                        + " / ".join(part.replace("_", " ").title() for part in name.split("/")[2:])
                        + ")"
                    )
                elif title_counts[module, title] > 1:
                    title += " (" + output_label(name).split(" · ", 1)[-1] + ")"
                item = QTreeWidgetItem(roots[module], [title])
                item.setData(0, Qt.UserRole, (name, metric))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    0,
                    Qt.Checked
                    if name.startswith("preparation/") or choose and metric == default
                    else Qt.Unchecked,
                )
                if module == "preparation":
                    tooltip = (
                        title + "\nCoverage of the prepared samples supplied to these pipelines."
                    )
                elif name.startswith("classifications/gait/") and metric in (
                    "pred_gait_window",
                    "pred_no_other_arm_activity_window",
                ):
                    threshold = gait_model_threshold(name.rsplit("/", 1)[-1])
                    tooltip = (
                        title
                        + f"\nPresent when the window probability is ≥ {threshold:.5g} (bundled model threshold)."
                        "\nThese window predictions precede the final merged sample labels."
                        "\nFiltered presence is intersected with detected gait. Both epoch percentages use the same observed time."
                    )
                else:
                    tooltip = f"{name}\n{metric}"
                item.setToolTip(0, tooltip)
                self._series_items[(name, metric)] = item
            if choose and default is not None:
                default_modules.add(module)
        self.result_series.blockSignals(False)

    def selected_result_series(self):
        chosen = []
        for index in range(self.result_series.topLevelItemCount()):
            module = self.result_series.topLevelItem(index)
            for row in range(module.childCount()):
                item = module.child(row)
                if item.checkState(0) == Qt.Checked:
                    chosen.append(item.data(0, Qt.UserRole))
        return chosen

    def select_plot_series(self, item, previous=None):
        key = item.data(0, Qt.UserRole) if item is not None else None
        if key is None or key[0] not in self.tables:
            return
        name, metric = key
        self.dataset.setCurrentText(name)
        self.y_column.blockSignals(True)
        self.y_column.setCurrentIndex(self.y_column.findData(metric))
        self.y_column.blockSignals(False)

    def analyzed(self, results):
        self._sensor_time_indices.clear()
        self._plot_signature = None
        self._epoch_views.clear()
        self._epoch_presence_views.clear()
        self._gait_presence_cache = self._gait_epoch_cache = None
        self._table_views.clear()
        self._table_output_names = None
        self.results = results
        if self.current_run is None:
            self.result_source_frame = self.recordings if self.recordings else self.frame
        settings = self.provenance.get("settings", {})
        batch_clock = None
        self._recording_bases = {}
        if isinstance(self.result_source_frame, dict):
            (
                self.result_timeline,
                self._source_timelines,
                self._display_offsets,
                batch_clock,
                self._recording_bases,
            ) = align_recordings(self.result_source_frame, settings, results)
        else:
            self.result_timeline, self._source_timelines, self._display_offsets = (
                analysis_alignment(
                    self.result_source_frame,
                    settings,
                    results,
                    self.provenance.get("display_offsets"),
                )
            )
        if self._display_offsets:
            self.provenance["display_offsets"] = dict(self._display_offsets)
        extent = recording_extent(self.result_timeline, self._recording_bases)
        if extent is not None:
            self.provenance["recording_extent"] = extent
        self.display_clock = None
        if self.provenance.get("display_clock"):
            try:
                self.display_clock = normalise_clock(self.provenance["display_clock"])
            except (ValueError, TypeError, KeyError, OverflowError):
                self.append_log(
                    "Stored recording clock is invalid; using available recording timing."
                )
                self.provenance.pop("display_clock", None)
        if self.display_clock is None:
            self.display_clock = (
                batch_clock
                if isinstance(self.result_source_frame, dict)
                else recording_clock(self.result_source_frame, settings, self.result_timeline)
            )
        origin = settings.get("plot_time_origin", {})
        if not self.provenance.get("display_clock") and origin.get("mode") == "custom":
            self.display_clock = normalise_clock(origin["clock"])
        elif origin.get("mode") == "elapsed":
            self.display_clock = None
        if self.display_clock is not None:
            self.provenance["display_clock"] = dict(self.display_clock)
        if self.active_run is not None:
            self.active_run["_results"] = results
            self.active_run["_provenance"] = dict(self.provenance)
        self._detail_selections = {}
        data = prepare_result_data(results, self._display_offsets)
        self.tables, self.aggregation_tables = data.tables, data.aggregates
        self._plot_tables, self._plot_labels = data.plot_frames, data.plot_labels
        self._timings, self._interval_ends = data.timings, data.interval_ends
        self._bar_bounds = data.bar_bounds
        coverage, labels = data.coverage, data.coverage_labels
        sources = self.provenance.get("sources", {})
        self.results_source.setText(
            f"{len(sources)} recordings · One subject"
            if len(sources) > 1
            else Path(self.provenance.get("source", self.source)).name or "Current analysis"
        )
        self.build_result_overview((coverage, labels))
        self.populate_result_series()
        self.dataset.blockSignals(True)
        self.dataset.clear()
        self.dataset.addItems(self.tables)
        preferred = next(
            (
                name
                for name, _ in self.selected_result_series()
                if name.startswith("quantifications/")
            ),
            None,
        )
        if preferred is None:
            preferred = next(
                (
                    name
                    for name, frame in self.tables.items()
                    if name.startswith("quantifications/") and len(frame)
                ),
                None,
            )
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
            has_rows = any(
                len(v) for k, v in self.tables.items() if k.startswith("quantifications/")
            )
            message = (
                "Analysis completed."
                if has_rows
                else "No quantified windows. See Runs for details."
            )
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
        self.context_button.setToolTip(
            "Select a result row or click a graph point"
            if self.result_source_frame is not None
            else "Original sensor data unavailable"
        )
        self.y_column.blockSignals(True)
        self.y_column.clear()
        if frame is not None:
            plot_frame = self._plot_tables[name]
            for column in plot_metrics(name, plot_frame):
                self.y_column.addItem(str(column), column)
            preferred = next(
                (metric for dataset, metric in self.selected_result_series() if dataset == name),
                preferred_metric(name, plot_frame),
            )
            if preferred is not None:
                self.y_column.setCurrentIndex(self.y_column.findData(preferred))
        self.y_column.blockSignals(False)
        self.activate_dataset_rows()
        self.sync_table_outputs(force_detail=True)
        if self.result_tabs.currentIndex() != 1 and not any(
            dataset == name for dataset, metric in self.selected_result_series()
        ):
            item = self._series_items.get((name, self.y_column.currentData()))
            if item is not None:
                item.setCheckState(0, Qt.Checked)

    def activate_dataset_rows(self, *_):
        # All official output rows are available; zooming changes only the plot.
        if not self._detail_selections:
            self._detail_selections = {
                key: (self.tables.get(key, frame), np.arange(len(frame)))
                for key, frame in self._plot_tables.items()
            }
        self.active_frame, self.active_positions = self._detail_selections.get(
            self.dataset.currentText(), (None, np.array([], dtype=int))
        )
        self.active_selection = {}
        self.refresh_detail_table()
        self.plot()

    # Compatibility for existing integrations; there are no row filters.
    apply_filters = activate_dataset_rows

    def refresh_detail_table(self):
        self.context_button.setEnabled(False)
        self.context_button.setToolTip(
            "Select a result row or click a graph point"
            if self.result_source_frame is not None
            else "Original sensor data unavailable"
        )
        frame = self.active_frame
        if frame is None:
            self.display_frame = None
            self.result_table.setModel(None)
            self.selection_note.setText("No detailed outputs returned.")
            return
        name = self.dataset.currentText()
        key = name, self.timing_toggle.isChecked()
        view = self._table_views.get(key)
        if view is None:
            timing = self._timings[name].iloc[self.active_positions] if key[1] else None
            view = detail_table_view(frame, name, timing, self._display_offsets, self.display_clock)
        self._table_views[key] = view
        self._table_views.move_to_end(key)
        while len(self._table_views) > 4:
            self._table_views.popitem(last=False)
        self.display_frame = view
        self.result_table.setModel(FrameModel(view))
        self.result_table.selectionModel().currentRowChanged.connect(self.result_row_changed)
        self.update_detail_note()

    def update_detail_note(self):
        name, frame = self.dataset.currentText(), self.active_frame
        if frame is None:
            return
        clock_note = (
            f"Recording time ({self.display_clock.get('timezone') or 'timezone unspecified'})"
            if self.display_clock
            else "Elapsed time · Set a time origin in Analyze to display dates"
        )
        if self.display_clock is None and len(self.provenance.get("sources", {})) > 1:
            clock_note = "File-order timeline · Recording clocks unavailable"
        estimated = name.startswith("quantifications/gait/") and "time" not in frame
        self.selection_note.setText(
            f"{len(frame):,} / {len(self.tables[name]):,} rows · {clock_note}"
            + (" · Gait positions estimated within segments" if estimated else "")
        )
        if not self.timing_toggle.isChecked():
            self.selection_note.setText(f"{len(frame):,} / {len(self.tables[name]):,} rows")
        if self.table_dataset.currentData() in self.aggregation_tables:
            self.selection_note.setText("Full-run aggregates")

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

    def inspect_sensor_context(self):
        import pandas as pd

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
                index = self.sensor_time_index(common, self._recording_bases[key])
                display_timeline = index.times
            else:
                if self.result_timeline is None:
                    self.result_timeline = source_timeline(
                        source_frame, self.provenance.get("settings", {})
                    )
                module_timeline = self._source_timelines.get(module, self.result_timeline)
                index = self.sensor_time_index(self.result_timeline)
                display_timeline = index.times
            segment = gait_context(self.results, self.dataset.currentText(), selected)
            if "time" in selected and pd.notna(selected["time"]):
                anchor = float(selected["time"])
                radius = 10.0
                start, end = anchor - radius, anchor + radius
                include_end = True
            elif segment is not None:
                start, end, _ = segment
                include_end = False
            else:
                raise ValueError("No explicit sensor time context is available.")
            source_name = ""
            if isinstance(self.result_source_frame, dict):
                path = self.provenance.get("sources", {}).get(key, key)
                source_name = Path(path).name
            timing = self._timings[self.dataset.currentText()].iloc[self.active_positions[row]]
            self._sensor_context = SensorContext(
                source_frame,
                module_timeline,
                display_timeline,
                start,
                end,
                float(timing["Timeline time (s)"]),
                source_name=source_name,
                include_end=include_end,
            )
            self._sensor_navigator = SensorNavigator(
                self._sensor_context, self.display_clock, index=index
            )
            self.show_sensor_context()
            self.result_tabs.setTabVisible(self.sensor_tab_index, True)
            self.result_tabs.setCurrentIndex(self.sensor_tab_index)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            message = f"Sensor context unavailable: {exc}"
            self.context_button.setToolTip(message)
            self.status.setText(message)

    def show_sensor_context(self):
        context = self._sensor_context
        positions = context.positions()
        self.sensor_frame = context.frame.iloc[positions]
        self.sensor_times = context.display_times[positions]
        self.sensor_table.setModel(FrameModel(self.sensor_frame))
        self.populate_sensor_channels()
        self.plot_sensor()

    def sensor_time_index(self, times, offset=0.0):
        key = id(times), offset
        if key not in self._sensor_time_indices:
            display = np.asarray(times, dtype=float)
            if offset:
                display = display + offset
            # Retain the timeline reference so a later array cannot reuse its id.
            self._sensor_time_indices[key] = times, SensorTimeIndex(display)
        self._sensor_time_indices.move_to_end(key)
        while len(self._sensor_time_indices) > 4:
            self._sensor_time_indices.popitem(last=False)
        return self._sensor_time_indices[key][1]

    def update_sensor_view(self, axes):
        navigator = self._sensor_navigator
        if navigator is None or axes not in self.sensor_figure.axes:
            return
        limits = navigator.bounded_limits(axes.get_xlim())
        if tuple(axes.get_xlim()) != limits:
            axes.set_xlim(*limits, emit=False)
        if limits == navigator.limits:
            return
        navigator.limits = limits
        positions = navigator.positions(limits)
        self.update_sensor_samples(positions, limits)

    def update_sensor_samples(self, positions, limits):
        navigator = self._sensor_navigator
        self.sensor_frame = navigator.context.frame.iloc[positions]
        self.sensor_times = navigator.context.display_times[positions]
        self.sensor_table.setModel(FrameModel(self.sensor_frame))
        xs = navigator.coordinates_at(self.sensor_times)
        step = max(1, int(np.ceil(len(xs) / 20000)))
        channels = self.selected_sensor_channels()
        for ax in self.sensor_figure.axes:
            for line in ax.lines:
                if line.get_label() in channels and line.get_gid() is None:
                    line.set_data(xs[::step], self.sensor_frame[line.get_label()].iloc[::step])
                elif line.get_gid() is not None:
                    line.set_visible(limits[0] <= navigator.anchor <= limits[1])
            for collection in ax.collections:
                if collection.get_label() in channels:
                    present = (
                        self.sensor_frame[collection.get_label()]
                        .eq(1)
                        .fillna(False)
                        .to_numpy(dtype=bool)
                    )
                    collection.set_offsets(np.column_stack((xs[present], np.ones(present.sum()))))
            for text in ax.texts:
                if text.get_gid() == "sensor-no-data":
                    text.set_visible(self.sensor_frame.empty)
                elif text.get_gid() == "selected-result-label":
                    text.set_visible(limits[0] <= navigator.anchor <= limits[1])
            ax.relim()

    def reset_sensor_context(self):
        navigator = self._sensor_navigator
        if navigator is None or navigator.home_limits is None:
            return
        self.sensor_toolbar.push_current()
        navigator.limits = navigator.home_limits
        for ax in self.sensor_figure.axes:
            ax.set_xlim(*navigator.home_limits, emit=False)
        self.update_sensor_samples(navigator.context.positions(), navigator.home_limits)
        for ax in self.sensor_figure.axes:
            if any(line.get_gid() is None for line in ax.lines):
                ax.set_autoscaley_on(True)
                ax.autoscale_view(scalex=False, scaley=True)
        self.sensor_toolbar.push_current()
        if self.sensor_toolbar.settings_action.isChecked():
            self.sensor_toolbar.settings.read_axes()
        self.sensor_canvas.draw_idle()

    def hide_sensor_context(self):
        if self.result_tabs.currentIndex() == self.sensor_tab_index:
            self.result_tabs.setCurrentIndex(1)
        self.result_tabs.setTabVisible(self.sensor_tab_index, False)

    def selected_sensor_channels(self):
        return self.selected_channels(self.sensor_channels)

    def set_sensor_channels(self, channels):
        self.check_channels(self.sensor_channels, channels)
        self.plot_sensor()

    def populate_sensor_channels(self):
        selection = self.selected_sensor_channels() if self.sensor_channels.count() else None
        mapping = self.provenance.get("settings", {}).get("column_mapping", {})
        self._sensor_channel_colors = self.populate_channels(
            self.sensor_channels,
            self.sensor_frame,
            excluded={column for column, target in mapping.items() if target == "time"},
            selection=selection,
        )
        # Keep the chosen channels across context windows. A different recording
        # with no matching channels gets its first channel; an explicit Clear
        # remains empty until the user selects channels again.
        if selection and not self.selected_sensor_channels() and self.sensor_channels.count():
            self.check_channels(
                self.sensor_channels, [self.sensor_channels.item(0).data(Qt.UserRole)]
            )

    def plot_sensor(self, *_):
        # Clearing axes emits limit changes. These belong to the old figure,
        # not a user pan, and must not replace the current context samples.
        self.disconnect_sensor_view()
        context = self._sensor_context
        navigator = self._sensor_navigator
        if context is not None and (
            navigator is None
            or navigator.context is not context
            or navigator.clock != self.display_clock
        ):
            navigator = self._sensor_navigator = SensorNavigator(
                context, self.display_clock, index=self.sensor_time_index(context.display_times)
            )
        view_limits = navigator.limits if navigator is not None else None
        xs = (
            clock_times(self.sensor_times, self.display_clock)
            if self.sensor_frame is not None
            else []
        )
        calendar = self.display_clock is not None
        self.plot_channel_signals(
            self.sensor_figure,
            self.sensor_frame,
            self.selected_sensor_channels(),
            self._sensor_channel_colors,
            xs,
            "Recording date/time" if calendar else "Analysis time (s)",
            column_mapping=self.provenance.get("settings", {}).get("column_mapping", {}),
            calendar=calendar,
            timezone=clock_origin(self.display_clock).tz if calendar else None,
            allow_empty=self._sensor_context is not None,
            empty_schema=self._sensor_context.frame if self._sensor_context is not None else None,
        )
        if context is not None and self.selected_sensor_channels():
            mark_sensor_time(self.sensor_figure, context.selected_time, self.display_clock)
            if navigator is not None:
                if view_limits is not None or self.sensor_frame.empty:
                    for ax in self.sensor_figure.axes:
                        ax.set_xlim(*(view_limits or navigator.initial_limits), emit=False)
                navigator.limits = self.sensor_figure.axes[0].get_xlim()
                if navigator.home_limits is None:
                    navigator.home_limits = navigator.limits
                for ax in self.sensor_figure.axes:
                    for artist in [*ax.lines, *ax.texts]:
                        if artist.get_gid() is not None:
                            artist.set_visible(
                                navigator.limits[0] <= navigator.anchor <= navigator.limits[1]
                            )
                    self._sensor_view_callbacks[ax] = ax.callbacks.connect(
                        "xlim_changed", self.update_sensor_view
                    )
                    message = ax.text(
                        0.5,
                        0.5,
                        "No original samples in this context",
                        ha="center",
                        transform=ax.transAxes,
                        color="#60728A",
                    )
                    message.set_gid("sensor-no-data")
                    message.set_visible(self.sensor_frame.empty)
        self.sensor_toolbar.refresh()
        self.sensor_canvas.draw_idle()

    def disconnect_sensor_view(self):
        for ax, callback in self._sensor_view_callbacks.items():
            ax.callbacks.disconnect(callback)
        self._sensor_view_callbacks.clear()

    def refresh_runs(self):
        selected_ids = {record["id"] for record in self.selected_run_records()}
        if self.selected_run is not None and not any(
            record is self.selected_run for record in getattr(self, "_run_row_records", ())
        ):
            selected_ids = {self.selected_run["id"]}
        model = RecordModel(
            [
                {
                    "Started": datetime.fromisoformat(record["started"])
                    .astimezone()
                    .strftime("%d %b %Y · %H:%M"),
                    "Status": run_status(record),
                    "Input": (
                        f"{len(record['sources'])} recordings"
                        if len(record.get("sources", {})) > 1
                        else Path(record["source"]).name
                    ),
                    "Modules": ", ".join(record["settings"].get("pipelines", [])),
                    "Warnings": len(record["warnings"]),
                    "Errors": len(record.get("errors", [])),
                    "Exports": len(record["outputs"]),
                }
                for record in self.runs
            ],
            columns=["Started", "Status", "Input", "Modules", "Warnings", "Errors", "Exports"],
        )
        self._run_row_records = tuple(self.runs)
        self.run_table.setModel(model)
        self.run_table.setColumnWidth(0, 176)
        self.run_table.setColumnWidth(2, 170)
        self.run_table.selectionModel().currentRowChanged.connect(self.select_run)
        self.run_table.selectionModel().selectionChanged.connect(self.update_run_actions)
        if self.runs:
            index = next(
                (i for i, record in enumerate(self.runs) if record is self.selected_run), 0
            )
            selection = self.run_table.selectionModel()
            selection.blockSignals(True)
            selection.setCurrentIndex(
                self.run_table.model().index(index, 0), QItemSelectionModel.NoUpdate
            )
            rows = [i for i, record in enumerate(self.runs) if record["id"] in selected_ids] or [
                index
            ]
            for row in rows:
                selection.select(
                    self.run_table.model().index(row, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows,
                )
            selection.blockSignals(False)
            self.select_run(selection.currentIndex(), None)
        else:
            self.selected_run = None
        self.update_run_actions()

    def select_run(self, current, previous):
        if not current.isValid() or current.row() >= len(self.runs):
            return
        record = self.runs[current.row()]
        self.selected_run = record
        self.run_heading.setText(
            f"{run_status(record)} · "
            + (
                f"{len(record['sources'])} recordings"
                if len(record.get("sources", {})) > 1
                else Path(record["source"]).name
            )
        )
        self.run_heading.setToolTip(f"Run ID: {record['id']}")
        self.run_summary.setText(self.run_summary_text(record))
        self.run_details.setPlainText(
            "\n".join(
                f"{key.replace('_', ' ').capitalize()}: {json.dumps(value, ensure_ascii=False)}"
                for key, value in record["settings"].items()
            )
        )
        self.run_warnings.setPlainText(
            "\n\n".join(str(value) for value in record["warnings"]) or "No recorded warnings."
        )
        self.run_errors.setPlainText("\n\n".join(record.get("errors", [])) or "No recorded errors.")
        self.run_outputs.setPlainText(
            "\n\n".join(
                f"{item.get('kind', 'Export')}: {item.get('path', '')}"
                for item in record["outputs"]
            )
            or "No exports saved."
        )
        self.log.setPlainText(record.get("log", ""))
        self.update_run_actions()

    @staticmethod
    def run_summary_text(record):
        started = (
            datetime.fromisoformat(record["started"]).astimezone().strftime("%d %b %Y, %H:%M:%S")
        )
        finished = (
            datetime.fromisoformat(record["finished"]).astimezone().strftime("%H:%M:%S")
            if record.get("finished")
            else "—"
        )
        return (
            f"{started} – {finished} · ParaDigMa {record.get('paradigma_version', '—')} · "
            f"{len(record['warnings'])} warning(s), {len(record.get('errors', []))} error(s)\n{chr(10).join(record.get('sources', {}).values()) or record['source']}"
        )

    def selected_run_records(self):
        selection = self.run_table.selectionModel()
        rows = selection.selectedRows() if selection is not None else []
        records = getattr(self, "_run_row_records", ())
        return [
            records[index.row()]
            for index in sorted(rows, key=lambda index: index.row())
            if index.row() < len(records)
        ]

    def update_run_actions(self, *_):
        records = self.selected_run_records()
        count = len(records)
        current = self.run_table.currentIndex()
        desired = (
            records[0]
            if count == 1
            else (self._run_row_records[current.row()] if count > 1 and current.isValid() else None)
        )
        if desired is not None and self.selected_run is not desired:
            row = next(i for i, record in enumerate(self._run_row_records) if record is desired)
            self.select_run(self.run_table.model().index(row, 0), None)
            return
        record = self.selected_run
        available = record is not None and (
            "_results" in record or any(item.get("kind") == "JSON" for item in record["outputs"])
        )
        self.open_run_button.setEnabled(bool(available) and count == 1 and self.worker is None)
        self.use_parameters_button.setEnabled(
            record is not None and count == 1 and self.worker is None
        )
        self.delete_run_button.setEnabled(count > 0 and self.worker is None)
        self.delete_run_button.setText(f"Delete {count} Runs…" if count > 1 else "Delete Run…")
        self.clear_runs_button.setEnabled(bool(self.runs) and self.worker is None)

    def delete_run(self):
        self.delete_runs(self.selected_run_records())

    def clear_runs(self):
        self.delete_runs(list(self.runs), clear_all=True)

    def delete_runs(self, records, *, clear_all=False):
        if not records or self.worker is not None:
            return
        original_runs = list(self.runs)
        protected = [
            self.source,
            *self.sources.values(),
            *self.provenance.get("sources", {}).values(),
        ]
        removed = []
        try:
            files = list(
                dict.fromkeys(
                    path
                    for record in records
                    for path in self.history.removal_files(
                        record, original_runs, protected, removing=records
                    )
                )
            )
            warning = QMessageBox(self)
            warning.setPalette(light_palette())
            warning.setStyleSheet(STYLESHEET)
            warning.setIcon(QMessageBox.Warning)
            warning.setWindowTitle(
                "Clear all runs"
                if clear_all
                else "Delete runs"
                if len(records) > 1
                else "Delete run"
            )
            warning.setText(
                "Delete all runs and their associated exports?"
                if clear_all
                else f"Delete these {len(records)} runs and their associated exports?"
                if len(records) > 1
                else "Delete this run and its associated exports?"
            )
            warning.setInformativeText(
                f"{len(records)} history entry/entries and {len(files)} export file(s) will be permanently deleted. "
                "Original sensor files and exports referenced by runs you keep are preserved."
            )
            warning.setDetailedText(
                "\n".join(str(path) for path in files) or "No associated export files exist."
            )
            warning.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
            warning.setDefaultButton(QMessageBox.Cancel)
            warning.button(QMessageBox.Yes).setText(
                "Delete all runs"
                if clear_all
                else "Delete runs"
                if len(records) > 1
                else "Delete run"
            )
            if warning.exec() != QMessageBox.Yes:
                return
            for record in records:
                self.history.remove(record, original_runs, protected, removing=records)
                removed.append(record["id"])
            self.status.setText(f"{len(removed)} run(s) and associated exports deleted.")
        except (OSError, ValueError) as exc:
            self.show_notice(
                f"Could not finish deleting runs ({len(removed)} deleted): {exc}", "error"
            )
        finally:
            if removed:
                self.runs[:] = [record for record in self.runs if record["id"] not in removed]
                if self.selected_run is not None and self.selected_run["id"] in removed:
                    self.selected_run = None
                if self.current_run is not None and self.current_run["id"] in removed:
                    self.current_run = None
                    self.provenance = {}
                    self.result_source_frame = self.result_timeline = None
                    self.clear_results()
                self.refresh_runs()
                if not self.runs:
                    self.run_heading.setText("Select a run")
                    self.run_summary.clear()
                    for view in (
                        self.run_details,
                        self.run_warnings,
                        self.run_errors,
                        self.run_outputs,
                        self.log,
                    ):
                        view.clear()

    def open_run(self):
        record = self.selected_run
        if record is None or self.worker is not None:
            return
        if "_results" in record:
            self.restore_run((record["id"], record.get("_provenance", {}), record["_results"]))
            return
        output = next(
            (item for item in reversed(record["outputs"]) if item.get("kind") == "JSON"), None
        )
        if output:
            self.status.setText("Opening exported results…")
            self.start_job(
                lambda logger: (record["id"], *load_result_export(output["path"])), self.restore_run
            )

    def restore_run(self, payload):
        run_id, provenance, results = payload
        record = next(record for record in self.runs if record["id"] == run_id)
        self.current_run = record
        self.provenance = provenance or {
            "source": record["source"],
            "settings": record["settings"],
            "paradigma_version": record["paradigma_version"],
            "sources": record.get("sources", {}),
        }
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
        for widget, key in (
            (self.side, "watch_side"),
            (self.acc, "accelerometer_units"),
            (self.gyro, "gyroscope_units"),
            (self.time, "time_input_unit"),
        ):
            if key in settings:
                widget.setCurrentText(str(settings[key]))
        self.orientation.setText(",".join(settings.get("device_orientation") or ["x", "y", "z"]))
        self.mapping.setPlainText(json.dumps(settings.get("column_mapping", {})))
        self.prepared.setChecked(settings.get("skip_preparation", False))
        self.gaps.setChecked(settings.get("split_by_gaps", False))
        self.drop_missing.setChecked(settings.get("drop_missing_samples", False))
        self.max_gap.setValue(
            settings.get("max_gap_seconds", DEFAULT_MAX_GAP_SECONDS) or DEFAULT_MAX_GAP_SECONDS
        )
        self.min_segment.setValue(
            settings.get("min_segment_seconds", DEFAULT_MIN_SECTION_SECONDS)
            or DEFAULT_MIN_SECTION_SECONDS
        )
        origin = settings.get("plot_time_origin", {"mode": "automatic"})
        self._origin_override = origin.get("mode") != "automatic"
        if self._origin_override:
            self.origin_edited()
        if origin.get("mode") == "custom":
            self.clock_input.set_clock(origin["clock"])
            self.clock_input.setText(origin["clock"]["origin"])
        elif origin.get("mode") == "elapsed":
            self.clock_input.clear()
        else:
            self.update_origin_default()
        self.preparation_changed()
        self.navigate(1)
        self.status.setText("Run parameters restored. Check the selected input before running.")

    def record_output(self, path, kind):
        if self.current_run is not None:
            name, frame = self.selected_export_table()
            self.current_run["outputs"].append(
                {
                    "kind": kind,
                    "path": str(Path(path).resolve()),
                    "saved": now(),
                    "dataset": name if kind == "CSV" else "all results",
                }
            )
            if kind == "CSV":
                aggregation = name.startswith("aggregations/")
                self.current_run["outputs"][-1].update(
                    selected_rows=len(frame),
                    selection={"scope": "Full run"} if aggregation else self.active_selection,
                )
            self.persist_run(self.current_run)
            self.refresh_runs()

    def export(self):
        if self.results is None or self.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export complete results", "paradigma-results.json", "JSON (*.json)"
        )
        if path:
            try:
                export_results(
                    path,
                    self.results,
                    self.provenance,
                    protected_sources=[
                        *self.sources.values(),
                        *self.provenance.get("sources", {}).values(),
                    ],
                )
                self.record_output(path, "JSON")
                self.status.setText(f"Results exported to {path}")
            except Exception as exc:
                self.failure(str(exc))

    def choose_export(self):
        if self.results is None or self.worker is not None:
            return
        from .exports import ExportDialog, export_selection

        dialog = ExportDialog(self.results, self)
        if not dialog.exec():
            return
        extension = dialog.extension()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export results",
            f"paradigma-results.{extension}",
            f"{extension.upper()} (*.{extension})",
        )
        if not path:
            return
        selected, format_name = dialog.selected(), dialog.format.currentText()
        results, provenance, run = self.results, self.provenance, self.current_run
        protected = [*self.sources.values(), *provenance.get("sources", {}).values()]

        def write(logger):
            export_selection(
                path, results, provenance, selected, format_name, protected_sources=protected
            )
            return str(Path(path).resolve())

        def completed(output_path):
            if run is not None:
                run["outputs"].append(
                    {"kind": format_name, "path": output_path, "saved": now(), "selected": selected}
                )
                self.persist_run(run)
                self.refresh_runs()
            self.status.setText(f"Results exported to {output_path}")

        self.status.setText("Exporting results…")
        self.start_job(write, completed)

    def export_csv(self):
        name, frame = self.selected_export_table()
        if frame is None or self.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export selected rows", "output.csv", "CSV (*.csv)"
        )
        if path:
            try:
                export_table_csv(
                    path,
                    frame,
                    source=self.provenance.get("source", self.source),
                    protected_sources=[
                        *self.sources.values(),
                        *self.provenance.get("sources", {}).values(),
                    ],
                )
                self.record_output(path, "CSV")
                self.status.setText(f"{len(frame):,} rows from {name} exported to {path}")
            except Exception as exc:
                self.failure(str(exc))

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "Processing in progress", "Wait for processing to finish before closing."
            )
            event.ignore()
        else:
            self._origin_preview.shutdown()
            self._time_preview.shutdown()
            self._sensor_preview.shutdown()
            if getattr(self, "_acknowledgements_dialog", None) is not None:
                self._acknowledgements_dialog.close()
            event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "data_details"):
            orientation = Qt.Horizontal if self.width() >= 1280 else Qt.Vertical
            if self.data_details.orientation() != orientation:
                self.data_details.setOrientation(orientation)
                self.data_details.setSizes(
                    [660, 400] if orientation == Qt.Horizontal else [220, 300]
                )


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ParaDigMa")
    app.setStyle("Fusion")
    window = MainWindow()
    screen = app.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        window.resize(
            max(window.minimumWidth(), min(window.width(), available.width() - 48)),
            max(window.minimumHeight(), min(window.height(), available.height() - 48)),
        )
    app.setWindowIcon(window.windowIcon())
    window.show()
    sys.exit(app.exec())
