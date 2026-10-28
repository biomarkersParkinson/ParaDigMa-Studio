"""Job lifecycle, control restoration and cancellation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QTimer, Slot
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
        self._progress_worker: object | None = None
        self._analysis_completed: JobCompletion | None = None
        self._pending_progress = 0
        self._progress_timer = QTimer(self)
        self._progress_timer.setSingleShot(True)
        self._progress_timer.setInterval(200)
        self._progress_timer.timeout.connect(self._flush_progress)

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
        self._progress_timer.stop()
        self._pending_progress = 0
        analysis = self.jobs._analysis_stop is not None
        self.view.progress.setRange(0, 1000 if analysis else 0)
        if analysis:
            self.view.progress.setValue(0)
        self.view.progress.show()
        self.jobs.worker = self.services.worker_factory(operation)
        worker = self.jobs.worker
        self._progress_worker = worker if analysis else None

        self._analysis_completed = completed if analysis else None
        self.callbacks.connect_worker(worker, self._analysis_ready if analysis else completed)
        self.jobs.worker.start()

    @Slot(object)
    def _analysis_ready(self, payload: Any) -> None:
        worker = self._progress_worker
        sender = self.sender()
        if worker is not self.jobs.worker or (sender is not None and sender is not worker):
            return
        if self._analysis_completed is not None:
            self._analysis_completed(payload)
            if self._accept_progress(worker):
                self._progress_timer.stop()
                self._pending_progress = 1000
                self.view.progress.setValue(1000)

    def _accept_progress(self, worker: object) -> bool:
        cancel = self.jobs._analysis_stop
        return (
            worker is self.jobs.worker
            and worker is self._progress_worker
            and cancel is not None
            and not cancel.is_set()
        )

    @Slot(object, int)
    def analysis_progress(self, worker: object, value: int) -> None:
        if self._accept_progress(worker) and 0 <= value < 1000:
            self._pending_progress = max(self._pending_progress, value)
            if (
                self._pending_progress > self.view.progress.value()
                and not self._progress_timer.isActive()
            ):
                self._progress_timer.start()

    def _flush_progress(self) -> None:
        if self._accept_progress(self._progress_worker):
            self.view.progress.setValue(self._pending_progress)

    def job_finished(self) -> None:
        self._progress_timer.stop()
        self._progress_worker = None
        self._analysis_completed = None
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
        self._progress_timer.stop()
        self._progress_worker = None
        self.runs._close_after_save = False
        self.view.status.setText("Operation failed. See the processing log.")
        self.callbacks.append_log(message)
        self.callbacks.show_notice(message, "error")
        self.callbacks.finish_run("Failed", [message])

    def stop_analysis(self) -> None:
        cancel = getattr(self.jobs, "_analysis_stop", None)
        if self.jobs.worker is not None and cancel is not None:
            cancel.set()
            self._progress_timer.stop()
            self.view.stop_button.setEnabled(False)
            self.view.status.setText("Stopping analysis…")

    def analysis_cancelled(self) -> None:
        self._progress_timer.stop()
        self._progress_worker = None
        self.callbacks.append_log("Analysis stopped by the user.")
        self.callbacks.finish_run("Cancelled")
        self.view.status.setText("Analysis cancelled.")
        self.callbacks.show_notice("")
