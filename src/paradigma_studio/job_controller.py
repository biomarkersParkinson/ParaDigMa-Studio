"""Job lifecycle, control restoration and cancellation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QComboBox, QLabel, QProgressBar, QPushButton, QWidget

from .contracts import (
    ConnectWorkerCallback,
    FinishRunCallback,
    JobCompletion,
    JobOperation,
    NoticeCallback,
)
from .widgets import WrappedForm
from .workspace_state import JobState, ResultState, RunState

if TYPE_CHECKING:
    from .jobs import Worker


@dataclass(frozen=True)
class JobView:
    parent: QWidget
    analysis_controls: WrappedForm
    clear_runs_button: QPushButton
    data_time_channel: QComboBox
    data_time_unit: QComboBox
    delete_run_button: QPushButton
    export_button: QPushButton
    input_recording: QComboBox
    open_button: QPushButton
    open_run_button: QPushButton
    progress: QProgressBar
    run_button: QPushButton
    save_results_button: QPushButton
    settings_panel: QWidget
    status: QLabel
    stop_button: QPushButton
    use_parameters_button: QPushButton


@dataclass(frozen=True)
class JobCallbacks:
    connect_worker: ConnectWorkerCallback
    append_log: Callable[[str], None]
    close: Callable[[], object]
    finish_run: FinishRunCallback
    refresh_analysis: Callable[[], None]
    show_notice: NoticeCallback
    update_run_actions: Callable[[], None]


@dataclass(frozen=True)
class JobServices:
    worker_factory: Callable[[JobOperation], Worker]


class JobController(QObject):
    """Own job behavior through explicit state, frozen views and callbacks."""

    def __init__(
        self,
        jobs: JobState,
        results: ResultState,
        runs: RunState,
        view: JobView,
        callbacks: JobCallbacks,
        services: JobServices,
    ) -> None:
        super().__init__(view.parent)
        self.jobs = jobs
        self.results = results
        self.runs = runs
        self.view = view
        self.callbacks = callbacks
        self.services = services

    def start_job(self, operation: JobOperation, completed: JobCompletion) -> None:
        if self.jobs.worker is not None:
            return
        for widget in (
            self.view.open_button,
            self.view.run_button,
            self.view.settings_panel,
            self.view.analysis_controls,
            self.view.export_button,
            self.view.save_results_button,
            self.view.open_run_button,
            self.view.use_parameters_button,
            self.view.delete_run_button,
            self.view.clear_runs_button,
            self.view.data_time_channel,
            self.view.data_time_unit,
            self.view.input_recording,
        ):
            widget.setEnabled(False)
        self.view.progress.setRange(0, 0)
        self.view.progress.show()
        self.jobs.worker = self.services.worker_factory(operation)
        self.callbacks.connect_worker(self.jobs.worker, completed)
        self.jobs.worker.start()

    def job_finished(self) -> None:
        worker = self.jobs.worker
        self.jobs.worker = None
        self.view.open_button.setEnabled(True)
        self.view.settings_panel.setEnabled(True)
        self.view.analysis_controls.setEnabled(True)
        self.view.data_time_channel.setEnabled(True)
        self.view.data_time_unit.setEnabled(True)
        self.view.input_recording.setEnabled(True)
        self.callbacks.refresh_analysis()
        self.view.export_button.setEnabled(self.results.results is not None)
        self.view.save_results_button.setEnabled(
            self.results.results is not None and self.runs.current_run is not None
        )
        self.view.stop_button.setEnabled(False)
        self.jobs._analysis_stop = None
        self.view.progress.hide()
        if worker is not None:
            worker.deleteLater()
        self.callbacks.update_run_actions()
        if self.runs._close_after_save:
            self.runs._close_after_save = False
            QTimer.singleShot(0, self.callbacks.close)

    def failure(self, message: str) -> None:
        self.runs._close_after_save = False
        self.view.status.setText("Operation failed. See the processing log.")
        self.callbacks.append_log(message)
        self.callbacks.show_notice(message, "error")
        self.callbacks.finish_run("Failed", [message])

    def stop_analysis(self) -> None:
        cancel = getattr(self.jobs, "_analysis_stop", None)
        if self.jobs.worker is not None and cancel is not None:
            cancel.set()
            self.view.stop_button.setEnabled(False)
            self.view.status.setText("Stopping analysis…")

    def analysis_cancelled(self) -> None:
        self.callbacks.append_log("Analysis stopped by the user.")
        self.callbacks.finish_run("Cancelled")
        self.view.status.setText("Analysis cancelled.")
        self.callbacks.show_notice("")
