"""Pin observable connection and lifecycle ordering before extracting the window."""

from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QThread, Slot
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


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_job_connections_and_finished_restore_order(window, monkeypatch, outcome):
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
    window.start_job(lambda logger: None, completed)
    worker = window._job_state.worker
    assert connections == [
        "completed",
        "failed",
        "cancelled",
        "message",
        "warning",
        "error",
        "finished",
        "start",
    ]

    def restored(name):
        assert window._job_state.worker is None
        assert window.open_button.isEnabled() and window.settings_panel.isEnabled()
        events.append(name)

    monkeypatch.setattr(window, "modules_changed", lambda: restored("modules"))
    monkeypatch.setattr(window, "preparation_changed", lambda: restored("preparation"))
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
    assert events == [terminal, "modules", "preparation", "delete worker", "run actions"]
    assert window._job_state.worker is None and window._job_state._analysis_stop is None
    assert not window.stop_button.isEnabled() and window.progress.isHidden()


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
        "preparation_changed",
        "update_time_statistics",
        "input_plot_changed",
        "update_origin_default",
    )
    for name in names:
        original = getattr(desktop.MainWindow, name)

        def observed(self, *args, _name=name, _original=original, **kwargs):
            events.append(_name)
            if _name == "input_plot_changed":
                return _original(self)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(desktop.MainWindow, name, observed)
    window = desktop.MainWindow(history_dir=tmp_path)
    try:
        events.clear()
        window.data_time_unit.setCurrentText("relative_ms")
        assert events == ["update_time_statistics", "input_plot_changed"]
        events.clear()
        window.mapping.setPlainText('{"time": "time"}')
        assert events == ["update_origin_default", "input_plot_changed"]
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
