"""Native scientific workspace with separate configuration and exploration."""

import sys
from functools import cached_property

import numpy as np
from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog as QFileDialog,
    QMainWindow,
    QMessageBox as QMessageBox,
)

from .bootstrap import PLOT_CACHE_DIRECTORY as PLOT_CACHE_DIRECTORY

# Configure Matplotlib's cache before importing plotting-dependent components.
# isort: split
from .analysis_controller import AnalysisCallbacks, AnalysisController, AnalysisServices
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
)
from .data_controller import DataCallbacks, DataController, DataServices
from .export_controller import ExportCallbacks, ExportController, ExportServices
from .history import RunHistory
from .inspection import input_plot_time, inspect_recording, sensor_descriptives, time_descriptives
from .job_controller import JobCallbacks, JobController, JobServices
from .jobs import SignalHandler as SignalHandler, Worker
from .previews import CachedPreview
from .recordings import align_recordings, load_recordings, preview_recording_clock
from .result_controller import ResultCallbacks, ResultController, ResultView
from .result_workspace_controller import ResultWorkspaceCallbacks, ResultWorkspaceController
from .results_view import (
    analysis_alignment,
    recording_clock,
)
from .run_controller import RunCallbacks, RunController, RunView
from .sensor_controller import ChannelServices, SensorController, SensorView
from .shell_controller import ShellCallbacks, ShellController
from .theme import STYLESHEET, light_palette
from .ui.compatibility import workspace_ports
from .ui.layout import WorkspaceCallbacks, WorkspaceLayout
from .ui.result_graphs import ResultGraphCallbacks, ResultGraphs
from .ui.result_overview import ResultOverview
from .ui.result_series import ResultSeries
from .widgets import ReadableTable as ReadableTable
from .workspace_state import (
    AnalysisState,
    DataState,
    GraphState,
    InputState,
    JobState,
    PreviewServices,
    ResultState,
    RunState,
    SensorState,
    ShellState,
)


@workspace_ports
class MainWindow(QMainWindow):
    """Composition root and ordered Qt signal wiring for the workspace."""

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
        self._data_state = DataState()
        self._analysis_state = AnalysisState()
        self._job_state = JobState()
        self._graph_state = GraphState()
        self._shell_state = ShellState()

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(DATA_DIRECTORY / "app-icon.png")))
        self.resize(1450, 920)
        self.setMinimumSize(960, 650)
        self.setPalette(light_palette())
        self.setStyleSheet(STYLESHEET)
        self._job_state.worker = None
        self._data_state._input_descriptions = {}
        self._result_state._table_choices, self._result_state._series_items = {}, {}
        self._graph_state._result_selection_artists = []
        self._graph_state._result_shared_axes = None
        self._result_state._result_layout_index = None
        self._analysis_state._origin_override = False
        self._origin_preview = CachedPreview(self)
        self._origin_preview.value_ready.connect(self.apply_origin_preview)
        self._origin_preview.failed.connect(self.append_log)
        self._time_preview = CachedPreview(self)
        self._time_preview.value_ready.connect(self.apply_time_preview)
        self._time_preview.failed.connect(self.append_log)
        self._sensor_preview = CachedPreview(self)
        self._sensor_preview.value_ready.connect(self.apply_sensor_preview)
        self._sensor_preview.failed.connect(self.append_log)
        for preview in (self._origin_preview, self._time_preview, self._sensor_preview):
            preview.diagnostic.connect(self.append_log)
        self._data_state._data_plot_dirty = True
        self._result_state.active_positions = np.array([], dtype=int)
        self._shell_state.sidebar_collapsed = True
        directory = history_dir or user_storage_path(
            QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation), "runs"
        )
        self.history = RunHistory(directory)
        self._run_state.runs, history_issues = self.history.load()
        callbacks = self._workspace_callbacks()
        self._layout = WorkspaceLayout(
            self,
            callbacks,
            self._graph_state,
            self._shell_state,
            self._result_state,
            self.history.directory,
            self.SECTIONS,
            self.MODULES,
        )
        self._compose_controllers()
        self._connect()
        self._run_controller.refresh_runs()
        self._shell_controller.navigate(0)
        self._workspace_controller.build_result_overview()
        self._workspace_controller.sync_table_outputs()
        self._graph_controller.plot()
        if history_issues:
            self._shell_controller.show_notice("\n".join(history_issues))

    def _workspace_callbacks(self) -> WorkspaceCallbacks:
        return WorkspaceCallbacks(
            update_context_action=lambda *args, **kwargs: (
                self._graph_controller.update_context_action(*args, **kwargs)
            ),
            choose_export=lambda *args, **kwargs: self._export_controller.choose_export(
                *args, **kwargs
            ),
            clear_runs=lambda *args, **kwargs: self._run_controller.clear_runs(*args, **kwargs),
            delete_run=lambda *args, **kwargs: self._run_controller.delete_run(*args, **kwargs),
            graph_clicked=lambda *args, **kwargs: self._graph_controller.graph_clicked(
                *args, **kwargs
            ),
            hide_sensor_context=lambda *args, **kwargs: self._sensor_controller.hide_sensor_context(
                *args, **kwargs
            ),
            inspect_input_recording=lambda *args, **kwargs: (
                self._data_controller.inspect_input_recording(*args, **kwargs)
            ),
            inspect_sensor_context=lambda *args, **kwargs: (
                self._sensor_controller.inspect_sensor_context(*args, **kwargs)
            ),
            navigate=lambda *args, **kwargs: self._shell_controller.navigate(*args, **kwargs),
            open_file=lambda *args, **kwargs: self._data_controller.open_file(*args, **kwargs),
            open_run=lambda *args, **kwargs: self._run_controller.open_run(*args, **kwargs),
            plot=lambda *args, **kwargs: self._graph_controller.plot(*args, **kwargs),
            reset_origin=lambda *args, **kwargs: self._analysis_controller.reset_origin(
                *args, **kwargs
            ),
            reset_sensor_context=self.reset_sensor_context,
            results_tab_changed=lambda *args, **kwargs: (
                self._workspace_controller.results_tab_changed(*args, **kwargs)
            ),
            run_analysis=lambda *args, **kwargs: self._analysis_controller.run_analysis(
                *args, **kwargs
            ),
            save_results=lambda *args, **kwargs: self._export_controller.save_results(
                *args, **kwargs
            ),
            selected_result_series=lambda *args, **kwargs: (
                self._workspace_controller.selected_result_series(*args, **kwargs)
            ),
            set_input_channels=lambda *args, **kwargs: self._data_controller.set_input_channels(
                *args, **kwargs
            ),
            set_sensor_channels=lambda *args, **kwargs: self._sensor_controller.set_sensor_channels(
                *args, **kwargs
            ),
            show_acknowledgements=lambda *args, **kwargs: (
                self._shell_controller.show_acknowledgements(*args, **kwargs)
            ),
            stop_analysis=lambda *args, **kwargs: self._job_controller.stop_analysis(
                *args, **kwargs
            ),
            toggle_analysis_help=lambda *args, **kwargs: (
                self._analysis_controller.toggle_analysis_help(*args, **kwargs)
            ),
            use_run_parameters=lambda *args, **kwargs: self._analysis_controller.use_run_parameters(
                *args, **kwargs
            ),
        )

    def _compose_controllers(self):
        """Wire only the state, widgets and actions each component needs."""
        self._overview = ResultOverview(
            self._layout.overview_layout, self._layout._result_view_scrolls[0]
        )
        self._series = ResultSeries(self._layout.result_series)
        self._compose_run_controller()
        self._compose_result_controller()

        self._previews = PreviewServices(
            self._origin_preview, self._time_preview, self._sensor_preview
        )
        self._compose_data()
        self._compose_analysis()
        self._compose_job()
        self._compose_workspace()
        self._compose_export()
        self._compose_shell()
        self._compose_graph()

    def _compose_run_controller(self):
        run_view = RunView(
            status=self._layout.status,
            log=self._layout.log,
            run_table=self._layout.run_table,
            run_heading=self._layout.run_heading,
            run_summary=self._layout.run_summary,
            run_details=self._layout.run_details,
            run_recordings=self._layout.run_recordings,
            run_warnings=self._layout.run_warnings,
            run_errors=self._layout.run_errors,
            run_saved=self._layout.run_saved,
            run_outputs=self._layout.run_outputs,
            open_run_button=self._layout.open_run_button,
            use_parameters_button=self._layout.use_parameters_button,
            delete_run_button=self._layout.delete_run_button,
            clear_runs_button=self._layout.clear_runs_button,
        )
        run_callbacks = RunCallbacks(
            show_notice=lambda *args, **kwargs: self._shell_controller.show_notice(*args, **kwargs),
            clear_results=lambda *args, **kwargs: self._workspace_controller.clear_results(
                *args, **kwargs
            ),
            start_job=lambda *args, **kwargs: self._job_controller.start_job(*args, **kwargs),
            analyzed=lambda *args, **kwargs: self.analyzed(*args, **kwargs),
            prepare_results=lambda *args: self._result_controller.prepare(*args),
            install_prepared=lambda prepared: self._result_controller.install_prepared(prepared),
            selected_export_table=lambda *args, **kwargs: (
                self._workspace_controller.selected_export_table(*args, **kwargs)
            ),
            is_busy=lambda: self._job_state.worker is not None,
            select_run=lambda *args, **kwargs: self._run_controller.select_run(*args, **kwargs),
            update_run_actions=lambda *args, **kwargs: self._run_controller.update_run_actions(
                *args, **kwargs
            ),
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
            results_source=self._layout.results_source,
            dataset=self._layout.dataset,
            export_button=self._layout.export_button,
            save_results_button=self._layout.save_results_button,
            status=self._layout.status,
            result_tabs=self._layout.result_tabs,
        )
        result_callbacks = ResultCallbacks(
            append_log=lambda *args, **kwargs: self.append_log(*args, **kwargs),
            build_result_overview=lambda *args, **kwargs: (
                self._workspace_controller.build_result_overview(*args, **kwargs)
            ),
            populate_result_series=lambda *args, **kwargs: (
                self._workspace_controller.populate_result_series(*args, **kwargs)
            ),
            selected_result_series=lambda *args, **kwargs: (
                self._workspace_controller.selected_result_series(*args, **kwargs)
            ),
            select_dataset=lambda *args, **kwargs: self._workspace_controller.select_dataset(
                *args, **kwargs
            ),
            sync_table_outputs=lambda *args, **kwargs: (
                self._workspace_controller.sync_table_outputs(*args, **kwargs)
            ),
            show_notice=lambda *args, **kwargs: self._shell_controller.show_notice(*args, **kwargs),
            finish_run=lambda *args, **kwargs: self._run_controller.finish_run(*args, **kwargs),
            capture_warning=lambda *args, **kwargs: self.capture_warning(*args, **kwargs),
            navigate=lambda *args, **kwargs: self._shell_controller.navigate(*args, **kwargs),
            is_busy=lambda: self._job_state.worker is not None,
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

    @cached_property
    def _sensor_controller(self):
        sensor_view = SensorView(
            result_table=self._layout.result_table,
            context_button=self._layout.context_button,
            dataset=self._layout.dataset,
            result_tabs=self._layout.result_tabs,
            sensor_tab_index=self._layout.sensor_tab_index,
            status=self._layout.status,
            sensor_tabs=self._layout.sensor_tabs,
            sensor_table=self._layout.sensor_table,
            sensor_channels=self._layout.sensor_channels,
            sensor_figure=self._layout.sensor_figure,
            sensor_toolbar=self._layout.sensor_toolbar,
            sensor_canvas=self._layout.sensor_canvas,
        )
        channel_services = ChannelServices(
            selected_channels=lambda *args, **kwargs: self.selected_channels(*args, **kwargs),
            check_channels=lambda *args, **kwargs: self.check_channels(*args, **kwargs),
            populate_channels=lambda *args, **kwargs: self.populate_channels(*args, **kwargs),
            plot_channel_signals=lambda *args, **kwargs: self.plot_channel_signals(*args, **kwargs),
        )
        return SensorController(
            self._sensor_state,
            self._result_state,
            sensor_view,
            channel_services,
        )

    def _compose_data(self):
        callbacks = DataCallbacks(
            append_log=lambda *args, **kwargs: self.append_log(*args, **kwargs),
            navigate=lambda *args, **kwargs: self._shell_controller.navigate(*args, **kwargs),
            reset_analysis=lambda: self._analysis_controller.reset_for_input(),
            show_notice=lambda *args, **kwargs: self._shell_controller.show_notice(*args, **kwargs),
            start_job=lambda *args, **kwargs: self._job_controller.start_job(*args, **kwargs),
        )
        services = DataServices(
            load_recordings=lambda *args, **kwargs: load_recordings(*args, **kwargs),
            inspect_recording=lambda *args, **kwargs: inspect_recording(*args, **kwargs),
            sensor_descriptives=lambda *args, **kwargs: sensor_descriptives(*args, **kwargs),
            time_descriptives=lambda *args, **kwargs: time_descriptives(*args, **kwargs),
            input_plot_time=lambda *args, **kwargs: input_plot_time(*args, **kwargs),
        )
        channels = ChannelServices(
            check_channels=lambda *args, **kwargs: self.check_channels(*args, **kwargs),
            plot_channel_signals=lambda *args, **kwargs: self.plot_channel_signals(*args, **kwargs),
            populate_channels=lambda *args, **kwargs: self.populate_channels(*args, **kwargs),
            selected_channels=lambda *args, **kwargs: self.selected_channels(*args, **kwargs),
        )
        self._data_controller = DataController(
            analysis=self._analysis_state,
            state=self._data_state,
            inputs=self._input_state,
            jobs=self._job_state,
            view=self._layout.data_view(),
            callbacks=callbacks,
            services=services,
            channels=channels,
            previews=self._previews,
        )

    def _compose_analysis(self):
        callbacks = AnalysisCallbacks(
            analyzed=lambda *args, **kwargs: self.analyzed(*args, **kwargs),
            clear_results=lambda *args, **kwargs: self._workspace_controller.clear_results(
                *args, **kwargs
            ),
            failure=lambda *args, **kwargs: self.failure(*args, **kwargs),
            navigate=lambda *args, **kwargs: self._shell_controller.navigate(*args, **kwargs),
            persist_run=lambda *args, **kwargs: self._run_controller.persist_run(*args, **kwargs),
            refresh_runs=lambda *args, **kwargs: self._run_controller.refresh_runs(*args, **kwargs),
            show_notice=lambda *args, **kwargs: self._shell_controller.show_notice(*args, **kwargs),
            start_job=lambda *args, **kwargs: self._job_controller.start_job(*args, **kwargs),
            sync_input=lambda unit, mapping: self._data_controller.sync_analysis_settings(
                unit, mapping
            ),
        )
        services = AnalysisServices(
            recording_clock=lambda *args, **kwargs: recording_clock(*args, **kwargs),
            preview_recording_clock=lambda *args, **kwargs: preview_recording_clock(
                *args, **kwargs
            ),
            run_isolated_analysis=lambda *args, **kwargs: run_isolated_analysis(*args, **kwargs),
        )
        self._analysis_controller = AnalysisController(
            analysis=self._analysis_state,
            inputs=self._input_state,
            jobs=self._job_state,
            results=self._result_state,
            runs=self._run_state,
            view=self._layout.analysis_view(),
            callbacks=callbacks,
            services=services,
            previews=self._previews,
            modules=self.MODULES,
        )

    def _compose_job(self):
        callbacks = JobCallbacks(
            append_log=lambda *args, **kwargs: self.append_log(*args, **kwargs),
            close=lambda *args, **kwargs: self.close(*args, **kwargs),
            finish_run=lambda *args, **kwargs: self._run_controller.finish_run(*args, **kwargs),
            refresh_analysis=lambda: self._analysis_controller.refresh(),
            show_notice=lambda *args, **kwargs: self._shell_controller.show_notice(*args, **kwargs),
            update_run_actions=lambda *args, **kwargs: self._run_controller.update_run_actions(
                *args, **kwargs
            ),
            connect_worker=self._connect_worker,
        )
        services = JobServices(
            worker_factory=lambda *args, **kwargs: Worker(*args, **kwargs),
        )
        self._job_controller = JobController(
            jobs=self._job_state,
            results=self._result_state,
            runs=self._run_state,
            view=self._layout.job_view(),
            callbacks=callbacks,
            services=services,
        )

    def _compose_workspace(self):
        callbacks = ResultWorkspaceCallbacks(
            disconnect_sensor_view=lambda *args, **kwargs: (
                self._sensor_controller.disconnect_sensor_view(*args, **kwargs)
            ),
            hide_sensor_context=lambda *args, **kwargs: self._sensor_controller.hide_sensor_context(
                *args, **kwargs
            ),
            highlight_result_row=lambda *args, **kwargs: (
                self._graph_controller.highlight_result_row(*args, **kwargs)
            ),
            plot=lambda *args, **kwargs: self._graph_controller.plot(*args, **kwargs),
            result_row_changed=lambda *args, **kwargs: self._graph_controller.result_row_changed(
                *args, **kwargs
            ),
            update_context_action=lambda *args, **kwargs: (
                self._graph_controller.update_context_action(*args, **kwargs)
            ),
        )
        self._workspace_controller = ResultWorkspaceController(
            graphs=self._graph_state,
            results=self._result_state,
            sensors=self._sensor_state,
            view=self._layout.workspace_view(),
            callbacks=callbacks,
            overview=self._overview,
            series=self._series,
        )

    def _compose_export(self):
        callbacks = ExportCallbacks(
            append_log=lambda *args, **kwargs: self.append_log(*args, **kwargs),
            failure=lambda *args, **kwargs: self.failure(*args, **kwargs),
            persist_run=lambda *args, **kwargs: self._run_controller.persist_run(*args, **kwargs),
            record_output=lambda *args, **kwargs: self._run_controller.record_output(
                *args, **kwargs
            ),
            refresh_runs=lambda *args, **kwargs: self._run_controller.refresh_runs(*args, **kwargs),
            save_run_results=lambda *args, **kwargs: self._run_controller.save_run_results(
                *args, **kwargs
            ),
            selected_export_table=lambda *args, **kwargs: (
                self._workspace_controller.selected_export_table(*args, **kwargs)
            ),
            start_job=lambda *args, **kwargs: self._job_controller.start_job(*args, **kwargs),
        )
        services = ExportServices(
            export_results=lambda *args, **kwargs: export_results(*args, **kwargs),
            export_table_csv=lambda *args, **kwargs: export_table_csv(*args, **kwargs),
        )
        self._export_controller = ExportController(
            inputs=self._input_state,
            jobs=self._job_state,
            results=self._result_state,
            runs=self._run_state,
            shell=self._shell_state,
            view=self._layout.export_view(),
            callbacks=callbacks,
            services=services,
            previews=self._previews,
            history=self.history,
        )

    def _compose_shell(self):
        callbacks = ShellCallbacks(
            data_tab_changed=lambda *args, **kwargs: self._data_controller.data_tab_changed(
                *args, **kwargs
            ),
        )
        self._shell_controller = ShellController(
            shell=self._shell_state,
            view=self._layout.shell_view(),
            callbacks=callbacks,
            sections=self.SECTIONS,
        )

    def _compose_graph(self):
        callbacks = ResultGraphCallbacks(
            selected_result_series=lambda *args, **kwargs: (
                self._workspace_controller.selected_result_series(*args, **kwargs)
            ),
            sync_table_outputs=lambda *args, **kwargs: (
                self._workspace_controller.sync_table_outputs(*args, **kwargs)
            ),
        )
        self._graph_controller = ResultGraphs(
            graphs=self._graph_state,
            results=self._result_state,
            view=self._layout.graph_view_model(),
            callbacks=callbacks,
        )

    def _connect(self):
        self._layout.result_graph_view.currentIndexChanged.connect(self._graph_controller.plot)
        self._layout.data_tabs.currentChanged.connect(self._data_controller.data_tab_changed)
        self._layout.gaps.toggled.connect(self._analysis_controller.update_gap_controls)
        self._layout.drop_missing.toggled.connect(self._analysis_controller.update_origin_default)
        for item in self._layout.module_buttons.values():
            item.toggled.connect(self._analysis_controller.modules_changed)
        self._layout.time.currentTextChanged.connect(self._analysis_controller.time_unit_changed)
        self._layout.data_channels.itemChanged.connect(self._data_controller.plot_input)
        self._layout.data_time_channel.currentIndexChanged.connect(
            self._data_controller.refresh_data_descriptives
        )
        self._layout.data_time_unit.currentTextChanged.connect(
            self._data_controller.update_time_statistics
        )
        self._layout.data_time_unit.currentTextChanged.connect(
            self._data_controller.input_plot_changed
        )
        self._layout.dataset.currentTextChanged.connect(self._workspace_controller.select_dataset)
        self._layout.table_dataset.currentIndexChanged.connect(
            self._workspace_controller.select_output_table
        )
        self._layout.table_module_tabs.currentChanged.connect(
            self._workspace_controller.table_module_changed
        )
        self._layout.timing_toggle.toggled.connect(self._workspace_controller.table_timing_changed)
        self._layout.y_column.currentIndexChanged.connect(self._workspace_controller.update_metric)
        self._layout.result_series.itemChanged.connect(self._graph_controller.plot)
        self._layout.result_series.currentItemChanged.connect(
            self._workspace_controller.select_plot_series
        )
        self._layout.clock_input.valueEdited.connect(self._analysis_controller.origin_edited)
        self._layout.mapping.changed.connect(self._analysis_controller.mapping_changed)
        self._layout.sensor_channels.itemChanged.connect(self.plot_sensor)
        self._analysis_controller.refresh()

    def _connect_worker(self, worker, completed):
        worker.completed.connect(completed)
        worker.failed.connect(self.failure)
        worker.cancelled.connect(self.analysis_cancelled)
        worker.message.connect(self.append_log)
        worker.warning.connect(self.capture_warning)
        worker.error.connect(self.capture_error)
        worker.finished.connect(self.job_finished)

    def apply_origin_preview(self, clock):
        return self._analysis_controller.apply_origin_preview(clock)

    def apply_sensor_preview(self, description):
        return self._data_controller.apply_sensor_preview(description)

    def apply_time_preview(self, description):
        return self._data_controller.apply_time_preview(description)

    def append_log(self, message):
        return self._run_controller.append_log(message)

    def capture_warning(self, message):
        return self._run_controller.capture_warning(message)

    def capture_error(self, message):
        return self._run_controller.capture_error(message)

    def job_finished(self):
        return self._job_controller.job_finished()

    def failure(self, message):
        return self._job_controller.failure(message)

    def analysis_cancelled(self):
        return self._job_controller.analysis_cancelled()

    def analyzed(self, results):
        return self._result_controller.analyzed(results)

    def plot_sensor(self, *_):
        # Connecting this slot must not create the deferred sensor controller.
        return self._sensor_controller.plot_sensor(*_)

    def reset_sensor_context(self):
        return self._sensor_controller.reset_sensor_context()

    combo = staticmethod(WorkspaceLayout.combo)
    run_summary_text = staticmethod(RunController.run_summary_text)

    def closeEvent(self, event):
        self._export_controller.closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_layout"):
            self._layout.resize_data(self.width())


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
