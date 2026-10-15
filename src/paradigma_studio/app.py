"""Native scientific workspace with separate configuration and exploration."""

import json
import sys
from importlib.metadata import version
from pathlib import Path
from threading import Event

import numpy as np
from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
)

from .bootstrap import PLOT_CACHE_DIRECTORY as PLOT_CACHE_DIRECTORY

# Configure Matplotlib's cache before importing plotting-dependent components.
# isort: split
from .analysis_help import DEFAULT_MAX_GAP_SECONDS, DEFAULT_MIN_SECTION_SECONDS
from .analysis_process import run_isolated_analysis
from .assets import DATA_DIRECTORY
from .branding import APP_NAME, user_storage_path
from .channels import (
    check_channels,
    plot_channel_signals,
    populate_channels,
    selected_channels,
)
from .core import (
    analyze as analyze,
    export_results,
    export_table_csv,
    load_sensor_file as load_sensor_file,
    validate_column_mapping,
    validate_orientation,
)
from .history import RunHistory, new_run, now, run_is_saved
from .inspection import input_plot_time, inspect_recording, sensor_descriptives, time_descriptives
from .jobs import SignalHandler as SignalHandler, Worker
from .previews import CachedPreview
from .recordings import align_recordings, load_recordings, preview_recording_clock
from .result_controller import ResultCallbacks, ResultController, ResultView
from .result_data import detail_table_view
from .results_view import (
    MODULE_NAMES,
    analysis_alignment,
    normalise_clock,
    output_label,
    plot_metrics,
    preferred_metric,
    recording_clock,
)
from .run_controller import RunCallbacks, RunController, RunView
from .sensor_controller import ChannelServices, SensorController, SensorView
from .theme import STYLESHEET, light_palette, module_color
from .ui.layout import WorkspaceLayout
from .ui.result_graphs import ResultGraphs
from .ui.result_overview import ResultOverview
from .ui.result_series import ResultSeries
from .widgets import FrameModel, ReadableTable as ReadableTable, WrappedForm
from .workspace_state import InputState, ResultState, RunState, SensorState, state_property


class MainWindow(WorkspaceLayout, ResultGraphs, QMainWindow):
    # Keep the existing widget/mixin/integration API backed by one state owner.
    # Components receive the state objects directly, rather than this window.
    frame = state_property("_input_state", "frame")
    source = state_property("_input_state", "source")
    sources = state_property("_input_state", "sources")
    recordings = state_property("_input_state", "recordings")
    runs = state_property("_run_state", "runs")
    active_run = state_property("_run_state", "active_run")
    current_run = state_property("_run_state", "current_run")
    selected_run = state_property("_run_state", "selected_run")
    _run_row_records = state_property("_run_state", "_run_row_records")
    _close_after_save = state_property("_run_state", "_close_after_save")
    provenance = state_property("_result_state", "provenance")
    tables = state_property("_result_state", "tables")
    aggregation_tables = state_property("_result_state", "aggregation_tables")
    _plot_tables = state_property("_result_state", "_plot_tables")
    _plot_labels = state_property("_result_state", "_plot_labels")
    _timings = state_property("_result_state", "_timings")
    _interval_ends = state_property("_result_state", "_interval_ends")
    _bar_bounds = state_property("_result_state", "_bar_bounds")
    _display_offsets = state_property("_result_state", "_display_offsets")
    _source_timelines = state_property("_result_state", "_source_timelines")
    _recording_bases = state_property("_result_state", "_recording_bases")
    _epoch_views = state_property("_result_state", "_epoch_views")
    _epoch_presence_views = state_property("_result_state", "_epoch_presence_views")
    _detail_selections = state_property("_result_state", "_detail_selections")
    results = state_property("_result_state", "results")
    result_timeline = state_property("_result_state", "result_timeline")
    result_source_frame = state_property("_result_state", "result_source_frame")
    display_clock = state_property("_result_state", "display_clock")
    _gait_presence_cache = state_property("_result_state", "_gait_presence_cache")
    _gait_epoch_cache = state_property("_result_state", "_gait_epoch_cache")
    _plot_signature = state_property("_result_state", "_plot_signature")
    _profile_selection = state_property("_result_state", "_profile_selection")
    _table_output_names = state_property("_result_state", "_table_output_names")
    active_frame = state_property("_result_state", "active_frame")
    display_frame = state_property("_result_state", "display_frame")
    active_positions = state_property("_result_state", "active_positions")
    active_selection = state_property("_result_state", "active_selection")
    _table_views = state_property("_result_state", "_table_views")
    sensor_frame = state_property("_sensor_state", "sensor_frame")
    sensor_times = state_property("_sensor_state", "sensor_times")
    _sensor_context = state_property("_sensor_state", "_sensor_context")
    _sensor_navigator = state_property("_sensor_state", "_sensor_navigator")
    _sensor_time_indices = state_property("_sensor_state", "_sensor_time_indices")
    _sensor_view_callbacks = state_property("_sensor_state", "_sensor_view_callbacks")
    _sensor_channel_colors = state_property("_sensor_state", "_sensor_channel_colors")

    selected_channels = staticmethod(selected_channels)
    check_channels = staticmethod(check_channels)
    populate_channels = staticmethod(populate_channels)
    plot_channel_signals = staticmethod(plot_channel_signals)

    SECTIONS = ("Data", "Analyze", "Results", "Runs")
    MODULES = {"Gait": "gait", "Tremor": "tremor", "Pulse rate": "pulse_rate"}

    def __init__(self, history_dir=None):
        super().__init__()
        self._input_state = InputState()
        self._run_state = RunState()
        self._result_state = ResultState()
        self._sensor_state = SensorState()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(DATA_DIRECTORY / "app-icon.png")))
        self.resize(1450, 920)
        self.setMinimumSize(960, 650)
        self.setPalette(light_palette())
        self.setStyleSheet(STYLESHEET)
        self.worker = None
        self._input_descriptions = {}
        self._table_choices, self._series_items = {}, {}
        self._result_selection_artists = []
        self._result_shared_axes = None
        self._result_layout_index = None
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
        self.active_positions = np.array([], dtype=int)
        self.sidebar_collapsed = True
        directory = history_dir or user_storage_path(
            QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation), "runs"
        )
        self.history = RunHistory(directory)
        self.runs, history_issues = self.history.load()
        self._build_shell()
        self._build_data()
        self._build_analyze()
        self._build_results()
        self._build_runs()
        self._compose_controllers()
        self._connect()
        self.refresh_runs()
        self.navigate(0)
        self.build_result_overview()
        self.sync_table_outputs()
        self.plot()
        if history_issues:
            self.show_notice("\n".join(history_issues))

    def _compose_controllers(self):
        """Wire only the state, widgets and actions each component needs."""
        self._overview = ResultOverview(self.overview_layout, self._result_view_scrolls[0])
        self._series = ResultSeries(self.result_series)
        self._compose_run_controller()
        self._compose_result_controller()
        self._compose_sensor_controller()

    def _compose_run_controller(self):
        run_view = RunView(
            status=self.status,
            log=self.log,
            run_table=self.run_table,
            run_heading=self.run_heading,
            run_summary=self.run_summary,
            run_details=self.run_details,
            run_recordings=self.run_recordings,
            run_warnings=self.run_warnings,
            run_errors=self.run_errors,
            run_saved=self.run_saved,
            run_outputs=self.run_outputs,
            open_run_button=self.open_run_button,
            use_parameters_button=self.use_parameters_button,
            delete_run_button=self.delete_run_button,
            clear_runs_button=self.clear_runs_button,
        )
        run_callbacks = RunCallbacks(
            show_notice=lambda *args, **kwargs: self.show_notice(*args, **kwargs),
            clear_results=lambda *args, **kwargs: self.clear_results(*args, **kwargs),
            start_job=lambda *args, **kwargs: self.start_job(*args, **kwargs),
            analyzed=lambda *args, **kwargs: self.analyzed(*args, **kwargs),
            selected_export_table=lambda *args, **kwargs: self.selected_export_table(
                *args, **kwargs
            ),
            is_busy=lambda: self.worker is not None,
            select_run=lambda *args, **kwargs: self.select_run(*args, **kwargs),
            update_run_actions=lambda *args, **kwargs: self.update_run_actions(*args, **kwargs),
        )
        self._run_controller = RunController(
            self._run_state,
            self._result_state,
            self._input_state,
            self.history,
            run_view,
            run_callbacks,
            parent=self,
        )

    def _compose_result_controller(self):
        result_view = ResultView(
            results_source=self.results_source,
            dataset=self.dataset,
            export_button=self.export_button,
            save_results_button=self.save_results_button,
            status=self.status,
            result_tabs=self.result_tabs,
        )
        result_callbacks = ResultCallbacks(
            append_log=lambda *args, **kwargs: self.append_log(*args, **kwargs),
            build_result_overview=lambda *args, **kwargs: self.build_result_overview(
                *args, **kwargs
            ),
            populate_result_series=lambda *args, **kwargs: self.populate_result_series(
                *args, **kwargs
            ),
            selected_result_series=lambda *args, **kwargs: self.selected_result_series(
                *args, **kwargs
            ),
            select_dataset=lambda *args, **kwargs: self.select_dataset(*args, **kwargs),
            sync_table_outputs=lambda *args, **kwargs: self.sync_table_outputs(*args, **kwargs),
            show_notice=lambda *args, **kwargs: self.show_notice(*args, **kwargs),
            finish_run=lambda *args, **kwargs: self.finish_run(*args, **kwargs),
            capture_warning=lambda *args, **kwargs: self.capture_warning(*args, **kwargs),
            navigate=lambda *args, **kwargs: self.navigate(*args, **kwargs),
            is_busy=lambda: self.worker is not None,
            align_recordings=lambda *args, **kwargs: align_recordings(*args, **kwargs),
            analysis_alignment=lambda *args, **kwargs: analysis_alignment(*args, **kwargs),
        )
        self._result_controller = ResultController(
            self._result_state,
            self._input_state,
            self._run_state,
            self._sensor_state,
            result_view,
            result_callbacks,
        )

    def _compose_sensor_controller(self):
        sensor_view = SensorView(
            result_table=self.result_table,
            context_button=self.context_button,
            dataset=self.dataset,
            result_tabs=self.result_tabs,
            sensor_tab_index=self.sensor_tab_index,
            status=self.status,
            sensor_table=self.sensor_table,
            sensor_channels=self.sensor_channels,
            sensor_figure=self.sensor_figure,
            sensor_toolbar=self.sensor_toolbar,
            sensor_canvas=self.sensor_canvas,
        )
        channel_services = ChannelServices(
            selected_channels=lambda *args, **kwargs: self.selected_channels(*args, **kwargs),
            check_channels=lambda *args, **kwargs: self.check_channels(*args, **kwargs),
            populate_channels=lambda *args, **kwargs: self.populate_channels(*args, **kwargs),
            plot_channel_signals=lambda *args, **kwargs: self.plot_channel_signals(*args, **kwargs),
        )
        self._sensor_controller = SensorController(
            self._sensor_state,
            self._result_state,
            sensor_view,
            channel_services,
        )

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
        self.data_time_unit.currentTextChanged.connect(self.input_plot_changed)
        self.dataset.currentTextChanged.connect(self.select_dataset)
        self.table_dataset.currentIndexChanged.connect(self.select_output_table)
        self.table_module_tabs.currentChanged.connect(self.table_module_changed)
        self.timing_toggle.toggled.connect(self.table_timing_changed)
        self.y_column.currentIndexChanged.connect(self.update_metric)
        self.result_series.itemChanged.connect(self.plot)
        self.result_series.currentItemChanged.connect(self.select_plot_series)
        self.clock_input.valueEdited.connect(self.origin_edited)
        self.mapping.textChanged.connect(self.update_origin_default)
        self.mapping.textChanged.connect(self.input_plot_changed)
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
        for i, item in enumerate(self.nav_buttons):
            item.setText(f"{i + 1}    {self.SECTIONS[i]}" if expanded else str(i + 1))
            item.setToolTip("" if expanded else self.SECTIONS[i])

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
        self.side.set_relevant("gait" in selected)
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
            self.save_results_button,
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
        self.save_results_button.setEnabled(
            self.results is not None and self.current_run is not None
        )
        self.stop_button.setEnabled(False)
        self._analysis_stop = None
        self.progress.hide()
        if worker is not None:
            worker.deleteLater()
        self.update_run_actions()
        if self._close_after_save:
            self._close_after_save = False
            QTimer.singleShot(0, self.close)

    def append_log(self, message):
        return self._run_controller.append_log(message)

    def capture_warning(self, message):
        return self._run_controller.capture_warning(message)

    def capture_error(self, message):
        return self._run_controller.capture_error(message)

    def update_run_problems(self):
        return self._run_controller.update_run_problems()

    def persist_run(self, record):
        return self._run_controller.persist_run(record)

    def finish_run(self, status, errors=()):
        return self._run_controller.finish_run(status, errors)

    def failure(self, message):
        self._close_after_save = False
        self.status.setText("Operation failed. See the processing log.")
        self.append_log(message)
        self.show_notice(message, "error")
        self.finish_run("Failed", [message])

    def clear_results(self):
        self.disconnect_sensor_view()
        self.plot_toolbar.stop_navigation()
        for toolbar in (self.plot_toolbar, self.sensor_toolbar):
            if toolbar._pan_info is not None:
                toolbar.release_pan(None)
        self._plot_signature = None
        self._result_shared_axes = None
        self._result_selection_artists.clear()
        self._epoch_views.clear()
        self._epoch_presence_views.clear()
        self._profile_selection = None
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
        self.save_results_button.setEnabled(False)
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
        self.result_time_scroll.bind(None)
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

    def input_plot_changed(self):
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
                times, time_label, timezone = input_plot_time(
                    self.frame[column], self.data_time_unit.currentText()
                )
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
        if settings["skip_preparation"] or not settings["drop_missing_samples"]:
            settings["pipelines"] = []
        elif "gait" in settings["pipelines"]:
            # Gait already requires every channel needed by tremor. Adding
            # tremor cannot change which samples establish the clock.
            settings["pipelines"] = [name for name in settings["pipelines"] if name != "tremor"]
        frame, recordings = self.frame, self.recordings
        key = json.dumps(settings, sort_keys=True)
        if self._origin_preview.is_requested(key):
            return

        def preview():
            if recordings:
                return preview_recording_clock(recordings, settings)
            return recording_clock(frame, settings)

        # Keep the current value editable. A user edit cancels the automatic
        # preview, so its eventual result cannot overwrite that choice.
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
            settings = {
                "pipelines": pipelines,
                "watch_side": self.side.currentText(),
                "accelerometer_units": self.acc.currentText(),
                "gyroscope_units": self.gyro.currentText(),
                "time_input_unit": self.time.currentText(),
                "device_orientation": axes,
                "column_mapping": mapping,
                "skip_preparation": self.prepared.isChecked(),
                "split_by_gaps": self.gaps.isChecked(),
                "drop_missing_samples": self.drop_missing.isChecked(),
                "max_gap_seconds": self.max_gap.value(),
                "min_segment_seconds": self.min_segment.value(),
            }
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
        if self.results is not None:
            self.update_context_action(self.result_table.currentIndex())

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
        self.overview_values, self.overview_module_cards, self.overview_gait_charts = (
            self._overview.render(self.results, self.provenance, self.display_clock, prepared_views)
        )

    def populate_result_series(self):
        self._series_items = self._series.populate(
            self._plot_tables, self._plot_labels, self.tables
        )

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
        return self._result_controller.analyzed(results)

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
        return self._sensor_controller.inspect_sensor_context()

    def show_sensor_context(self):
        return self._sensor_controller.show_sensor_context()

    def sensor_time_index(self, times, offset=0.0):
        return self._sensor_controller.sensor_time_index(times, offset)

    def update_sensor_view(self, axes):
        return self._sensor_controller.update_sensor_view(axes)

    def update_sensor_samples(self, positions, limits):
        return self._sensor_controller.update_sensor_samples(positions, limits)

    def reset_sensor_context(self):
        return self._sensor_controller.reset_sensor_context()

    def hide_sensor_context(self):
        return self._sensor_controller.hide_sensor_context()

    def selected_sensor_channels(self):
        return self._sensor_controller.selected_sensor_channels()

    def set_sensor_channels(self, channels):
        return self._sensor_controller.set_sensor_channels(channels)

    def populate_sensor_channels(self):
        return self._sensor_controller.populate_sensor_channels()

    def plot_sensor(self, *_):
        return self._sensor_controller.plot_sensor(*_)

    def disconnect_sensor_view(self):
        return self._sensor_controller.disconnect_sensor_view()

    def refresh_runs(self):
        return self._run_controller.refresh_runs()

    def select_run(self, current, previous):
        return self._run_controller.select_run(current, previous)

    @staticmethod
    def run_summary_text(record):
        return RunController.run_summary_text(record)

    def selected_run_records(self):
        return self._run_controller.selected_run_records()

    def update_run_actions(self, *_):
        return self._run_controller.update_run_actions(*_)

    def delete_run(self):
        self.delete_runs(self.selected_run_records())

    def clear_runs(self):
        self.delete_runs(list(self.runs), clear_all=True)

    def delete_runs(self, records, *, clear_all=False):
        return self._run_controller.delete_runs(records, clear_all=clear_all)

    def open_run(self):
        return self._run_controller.open_run()

    def restore_run(self, payload):
        return self._run_controller.restore_run(payload)

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
        return self._run_controller.record_output(path, kind)

    def export(self):
        if self.results is None or self.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export complete results", "paradigma-results.json", "JSON (*.json)"
        )
        if path:
            try:
                self.history.validate_export_destination(path, self.runs)
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
        from .exports import ExportDialog, export_items, export_selection

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
        tables, metadata = export_items(results)
        complete = format_name == "JSON" and set(selected) == set(tables) | set(metadata)
        protected = [*self.sources.values(), *provenance.get("sources", {}).values()]

        def write(logger):
            self.history.validate_export_destination(path, self.runs)
            export_selection(
                path, results, provenance, selected, format_name, protected_sources=protected
            )
            return str(Path(path).resolve())

        def completed(output_path):
            if run is not None:
                run["outputs"].append(
                    {
                        "kind": format_name,
                        "path": output_path,
                        "saved": now(),
                        "selected": selected,
                        "complete": complete,
                    }
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
                self.history.validate_export_destination(path, self.runs)
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

    def unsaved_result_runs(self):
        return [
            record
            for record in self.runs
            if "_results" in record and (record.get("_unsaved_results") or not run_is_saved(record))
        ]

    def save_results(self):
        if self.worker is not None or self.current_run is None or self.results is None:
            return
        self.current_run["_results"] = self.results
        self.current_run["_provenance"] = dict(self.provenance)
        self.save_run_results([self.current_run])

    def save_run_results(self, records, *, close_after=False):
        return self._run_controller.save_run_results(records, close_after=close_after)

    def closeEvent(self, event):
        if self.worker is not None:
            QMessageBox.information(
                self, "Processing in progress", "Wait for processing to finish before closing."
            )
            event.ignore()
        else:
            unsaved = self.unsaved_result_runs()
            if unsaved:
                warning = QMessageBox(self)
                warning.setObjectName("unsavedResults")
                warning.setPalette(light_palette())
                warning.setStyleSheet(STYLESHEET)
                warning.setIcon(QMessageBox.Warning)
                warning.setWindowTitle("Unsaved results")
                warning.setText("Save results before closing?")
                warning.setInformativeText(
                    f"{len(unsaved)} run(s) have unsaved results. Closing without saving loses "
                    "these results; run history alone cannot restore them."
                )
                warning.setDetailedText(
                    "\n".join(
                        f"{record['started']} · {Path(record['source']).name}" for record in unsaved
                    )
                )
                warning.setStandardButtons(
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
                )
                warning.setDefaultButton(QMessageBox.Cancel)
                warning.button(QMessageBox.Save).setText("Save all" if len(unsaved) > 1 else "Save")
                answer = warning.exec()
                if answer != QMessageBox.Discard:
                    event.ignore()
                    if answer == QMessageBox.Save:
                        self.save_run_results(unsaved, close_after=True)
                    return
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
