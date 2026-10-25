"""Protect worker wiring, lifecycle ordering and independent UI composition."""

from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pandas as pd
import pytest
from PySide6.QtCore import QModelIndex, QObject, QThread, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow

from paradigma_studio import app as desktop
from paradigma_studio.ui.layout import WorkspaceCallbacks, WorkspaceLayout
from paradigma_studio.ui.result_graphs import ResultGraphCallbacks, ResultGraphs
from paradigma_studio.workspace_state import GraphState, ResultState, ShellState


class RecordingSignal:
    def __init__(self, name, events):
        self.name, self.events, self.slots = name, events, []

    def connect(self, slot):
        self.events.append(self.name)
        self.slots.append(slot)

    def emit(self, *args):
        for slot in self.slots:
            slot(*args)


def observe_analysis_launch(controller, monkeypatch):
    events, operations, applications = [], [], []
    clear_log = controller.view.log.clear

    def persist(record):
        events.append("persist")
        assert record is controller.runs.active_run is controller.runs.current_run
        assert controller.results.result_source_frame is record["_frame"]
        assert controller.view.log.toPlainText() == ""
        assert controller.jobs._analysis_stop is None

    def navigate(index):
        events.append(("navigate", index))
        assert controller.view.status.text() == "Running ParaDigMa… Review progress in Runs."
        record = controller.runs.current_run
        origin = controller.results.provenance
        assert origin["run_id"] == record["id"]
        assert origin["studio_version"] == record["studio_version"]
        assert origin["paradigma_version"] == record["paradigma_version"]
        assert origin["sources"] == controller.inputs.sources

    def start_job(operation, completed):
        events.append("start")
        assert controller.jobs._analysis_stop is not None
        operations.append((operation, completed))
        controller.jobs.worker = object()

    def clear():
        events.append("clear log")
        clear_log()

    monkeypatch.setattr(controller.view.log, "clear", clear)
    monkeypatch.setattr(
        controller,
        "callbacks",
        replace(
            controller.callbacks,
            show_notice=lambda text: events.append(("notice", text)),
            clear_results=lambda: events.append("clear results"),
            persist_run=persist,
            refresh_runs=lambda: events.append("refresh"),
            navigate=navigate,
            start_job=start_job,
        ),
    )
    monkeypatch.setattr(
        controller,
        "services",
        replace(
            controller.services,
            run_isolated_analysis=lambda *args: applications.append(args),
        ),
    )
    return events, operations, applications


@pytest.mark.parametrize("multiple", [False, True])
def test_analysis_launch_order_and_queued_input_cancel_snapshots(window, monkeypatch, multiple):
    controller = window._analysis_controller
    controller.set_modules(["tremor"])
    controller.view.log.setPlainText("Previous run log")
    frame = pd.DataFrame({"time": [0.0, 0.01], "gyroscope_x": [1.0, 2.0]})
    controller.inputs.frame, controller.inputs.source = frame, "sensor.csv"
    if multiple:
        controller.inputs.recordings = {"first": frame, "second": frame.copy()}
        controller.inputs.sources = {"first": "first.csv", "second": "second.csv"}
    expected_input = controller.inputs.recordings if multiple else frame
    events, operations, applications = observe_analysis_launch(controller, monkeypatch)
    try:
        controller.run_analysis()
        assert events == [
            ("notice", ""),
            "clear results",
            "clear log",
            "persist",
            "refresh",
            ("navigate", 1),
            "start",
        ]
        assert controller.view.stop_button.isEnabled()
        record = controller.runs.current_run
        assert record is controller.runs.selected_run is controller.runs.runs[0]
        assert record["_frame"] is expected_input
        if multiple:
            assert record["sources"] == controller.inputs.sources
            assert controller.results.provenance["sources"] == controller.inputs.sources
        assert len(operations) == 1 and operations[0][1] is controller.callbacks.analyzed
        cancel, logger = controller.jobs._analysis_stop, object()
        controller.jobs._analysis_stop = Event()
        controller.inputs.frame, controller.inputs.recordings = frame.copy(), {}
        record["settings"]["watch_side"] = "changed after launch"
        operations[0][0](logger)
        assert len(applications) == 1
        source, settings, observed_logger, observed_cancel = applications[0]
        assert source is expected_input and observed_logger is logger and observed_cancel is cancel
        assert observed_cancel is not controller.jobs._analysis_stop
        assert "plot_time_origin" not in settings
        assert settings["watch_side"] != record["settings"]["watch_side"]
        assert "plot_time_origin" in record["settings"]
        pd.testing.assert_frame_equal(
            frame, pd.DataFrame({"time": [0.0, 0.01], "gyroscope_x": [1.0, 2.0]})
        )
    finally:
        controller.jobs.worker = None
        controller.jobs._analysis_stop = None


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_job_callbacks_connect_before_start_and_terminal_cleanup_restores_controls(
    window, monkeypatch, outcome
):
    connections, events = [], []

    class RecordingWorker:
        def __init__(self, operation):
            self.operation = operation
            for name in (
                "completed",
                "failed",
                "cancelled",
                "message",
                "warning",
                "error",
                "finished",
            ):
                setattr(self, name, RecordingSignal(name, connections))

        def start(self):
            assert set(connections) == set(callbacks)
            assert len(connections) == len(callbacks)
            for name, callback in callbacks.items():
                assert getattr(self, name).slots == [callback], name
            connections.append("start")
            assert window._job_state.worker is self
            assert not window.open_button.isEnabled()
            assert not window.settings_panel.isEnabled()

        def deleteLater(self):
            events.append("delete worker")

    def completed(value):
        assert window._job_state.worker is worker and not window.open_button.isEnabled()
        events.append(("completed", value))

    monkeypatch.setattr(desktop, "Worker", RecordingWorker)
    monkeypatch.setattr(window, "failure", lambda message: events.append(("failed", message)))
    monkeypatch.setattr(window, "analysis_cancelled", lambda: events.append("cancelled"))
    callbacks = {
        "completed": completed,
        "failed": window.failure,
        "cancelled": window.analysis_cancelled,
        "message": window.append_log,
        "warning": window.capture_warning,
        "error": window.capture_error,
        "finished": window.job_finished,
    }
    try:
        window.start_job(lambda logger: None, completed)
        worker = window._job_state.worker
        assert connections[-1] == "start"

        def restored(name):
            assert window._job_state.worker is None
            assert window.open_button.isEnabled() and window.settings_panel.isEnabled()
            events.append(name)

        monkeypatch.setattr(window._analysis_controller, "refresh", lambda: restored("refresh"))
        monkeypatch.setattr(window, "update_run_actions", lambda: events.append("run actions"))
        if outcome == "completed":
            worker.completed.emit("output")
            terminal = ("completed", "output")
        elif outcome == "failed":
            worker.failed.emit("failure")
            terminal = ("failed", "failure")
        else:
            worker.cancelled.emit()
            terminal = "cancelled"
        worker.finished.emit()
        assert events == [terminal, "refresh", "delete worker", "run actions"]
        assert window._job_state.worker is None and window._job_state._analysis_stop is None
        assert not window.stop_button.isEnabled() and window.progress.isHidden()
    finally:
        # An early assertion must not leave a fake worker for fixture teardown to await.
        window._job_state.worker = None
        window._job_state._analysis_stop = None


def test_save_close_is_queued_after_job_cleanup(window, monkeypatch):
    events = []
    worker = SimpleNamespace(deleteLater=lambda: events.append("delete worker"))
    window._job_state.worker = worker
    window._run_state._close_after_save = True
    monkeypatch.setattr(window, "close", lambda: events.append(("close", window._job_state.worker)))
    window.job_finished()
    assert events == ["delete worker"] and not window._run_state._close_after_save
    QApplication.processEvents()
    assert events == ["delete worker", ("close", None)]


def test_data_time_and_mapping_connection_order(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    events = []
    names = (
        "mapping_changed",
        "update_time_statistics",
        "input_plot_changed",
        "update_origin_default",
    )
    owners = {
        "mapping_changed": desktop.AnalysisController,
        "update_time_statistics": desktop.DataController,
        "input_plot_changed": desktop.DataController,
        "update_origin_default": desktop.AnalysisController,
    }
    for name in names:
        owner = owners[name]
        original = getattr(owner, name)

        def observed(self, *args, _name=name, _original=original, **kwargs):
            events.append(_name)
            if _name == "input_plot_changed":
                return _original(self)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(owner, name, observed)
    window = desktop.MainWindow(history_dir=tmp_path)
    try:
        window.loaded(("sensor.csv", pd.DataFrame({"time": [0.0, 1.0], "gyroscope_x": [1.0, 2.0]})))
        events.clear()
        window.data_time_unit.setCurrentText("relative_ms")
        assert events == ["update_origin_default", "update_time_statistics", "input_plot_changed"]
        events.clear()
        window.mapping.set_mapping({"time": "time"})
        assert events == ["mapping_changed", "update_origin_default", "input_plot_changed"]
    finally:
        window.close()
        application.processEvents()


def test_layout_and_graph_components_need_only_declared_ports(tmp_path):
    application = QApplication.instance() or QApplication([])
    parent = QMainWindow()  # No MainWindow methods, state properties or compatibility facade.
    callbacks = WorkspaceCallbacks(
        **{field.name: lambda *args: None for field in fields(WorkspaceCallbacks)}
    )
    results, graphs = ResultState(), GraphState()
    layout = WorkspaceLayout(
        parent,
        callbacks,
        graphs,
        ShellState(),
        results,
        tmp_path,
        desktop.MainWindow.SECTIONS,
        desktop.MainWindow.MODULES,
    )
    try:
        views = [
            layout.data_view(),
            layout.analysis_view(),
            layout.job_view(),
            layout.workspace_view(),
            layout.export_view(),
            layout.shell_view(),
            layout.graph_view_model(),
        ]
        for view in views:
            assert view.__dataclass_params__.frozen
            with pytest.raises(FrozenInstanceError):
                view.parent = parent
        renderer = ResultGraphs(
            graphs, results, views[-1], ResultGraphCallbacks(lambda: [], lambda: None)
        )
        renderer.plot()
        renderer.result_row_changed(QModelIndex(), None)
        renderer.highlight_result_row()
        renderer.graph_clicked(SimpleNamespace(inaxes=None, xdata=None))
        assert not any(
            widget.initialized
            for widget in (layout._data_graph, layout.graph_view, layout._sensor_graph)
        )
        assert renderer.thread() is application.thread()
    finally:
        parent.close()
        parent.deleteLater()


def test_real_job_completion_preserves_gui_thread_and_cleanup_order(window):
    application = QApplication.instance()
    events = []

    class Receiver(QObject):
        @Slot(object)
        def completed(self, result):
            assert QThread.currentThread() is application.thread()
            assert window._job_state.worker is not None and not window.open_button.isEnabled()
            events.append(result)

    receiver = Receiver(window)

    def operation(logger):
        assert QThread.currentThread() is not application.thread()
        logger.info("Ordered worker message")
        return "completed on GUI thread"

    window.start_job(operation, receiver.completed)
    for _ in range(500):
        if window._job_state.worker is None:
            break
        QTest.qWait(10)
    assert window._job_state.worker is None
    assert events == ["completed on GUI thread"]
    assert "Ordered worker message" in window.log.toPlainText()
    assert window.open_button.isEnabled() and window.progress.isHidden()


def test_main_window_is_a_small_composition_root():
    assert desktop.MainWindow.__bases__ == (QMainWindow,)
    assert len(Path(desktop.__file__).read_text().splitlines()) < 800
