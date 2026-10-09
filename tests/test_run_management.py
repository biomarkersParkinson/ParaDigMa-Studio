"""Cancellation, process cleanup and confirmed deletion of owned exports."""
import logging
from pathlib import Path
from threading import Event
import time

import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from paradigma_desktop import app as desktop
from paradigma_desktop.app import MainWindow, Worker
from paradigma_desktop import analysis_process
from paradigma_desktop.history import RunHistory, new_run


def slow_child(input_path, output_path, settings, queue):
    queue.put(("log", logging.INFO, "Child started"))
    time.sleep(60)


def wait_for(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.01)
    assert predicate()


def test_stopping_an_owned_analysis_process_cleans_temporary_files(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(analysis_process, "_analyze_child", slow_child)
    original = analysis_process.tempfile.TemporaryDirectory
    monkeypatch.setattr(analysis_process.tempfile, "TemporaryDirectory", lambda **kwargs: original(dir=tmp_path, **kwargs))
    cancel = Event()
    messages, cancelled, completed, failed = [], [], [], []
    worker = Worker(lambda logger: analysis_process.run_isolated_analysis(pd.DataFrame({"time": [0.]}), {}, logger, cancel))
    worker.message.connect(messages.append)
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.completed.connect(completed.append)
    worker.failed.connect(failed.append)
    worker.start()
    try:
        wait_for(lambda: "Child started" in messages)
        assert list(tmp_path.glob("paradigma-analysis-*"))
        cancel.set()
        wait_for(lambda: not worker.isRunning(), seconds=10)
        app.processEvents()
        assert cancelled == [True] and not completed and not failed
        assert not list(tmp_path.iterdir())
    finally:
        cancel.set()
        assert worker.wait(10000)


def test_stop_button_cancels_run_without_error_and_controls_recover(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(history_dir=tmp_path / "runs")
    def run(frame, settings, logger, cancel):
        while not cancel.wait(.01):
            pass
        raise analysis_process.AnalysisCancelled()
    monkeypatch.setattr(desktop, "run_isolated_analysis", run)
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0., 1.]})))
    window.run_analysis()
    assert window.stop_button.isEnabled() and not window.run_button.isEnabled()
    assert window.stop_button.parentWidget() is window.status_row
    assert not window.delete_run_button.isEnabled()
    window.stop_button.click()
    wait_for(lambda: window.worker is None)
    record = window.runs[0]
    assert record["status"] == "Cancelled" and record["finished"]
    assert record["errors"] == [] and not record["outputs"]
    assert window.run_button.isEnabled() and not window.stop_button.isEnabled()
    assert window.history.load()[0][0]["status"] == "Cancelled"
    window.close()


def test_history_removal_protects_sources_companions_shared_outputs_and_directories(tmp_path):
    history = RunHistory(tmp_path / "runs")
    source = tmp_path / "imu_meta.json"
    source.write_text("original")
    binary = tmp_path / "imu_values.bin"
    binary.write_bytes(b"original")
    export, shared = tmp_path / "result.zip", tmp_path / "shared.json"
    export.write_bytes(b"export")
    shared.write_text("shared")
    directory = tmp_path / "do-not-delete"
    directory.mkdir()
    first, second = new_run(str(source), {}), new_run(str(source), {})
    first["status"], second["status"] = "Cancelled", "Completed"
    first["outputs"] = [{"kind": "CSV", "path": str(path)} for path in (source, binary, export, shared, directory)]
    second["outputs"] = [{"kind": "JSON", "path": str(shared)}]
    history.save(first)
    history.save(second)
    assert history.removal_files(first, [first, second]) == [export]
    history.remove(first, [first, second])
    assert not export.exists() and not (history.directory / f"{first['id']}.json").exists()
    assert source.exists() and binary.exists() and shared.exists() and directory.is_dir()
    assert (history.directory / f"{second['id']}.json").exists()


@pytest.mark.parametrize("confirm", [False, True])
def test_delete_key_prompts_and_removes_only_confirmed_run(monkeypatch, tmp_path, confirm):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(history_dir=tmp_path / "runs")
    source = tmp_path / "sensor.csv"
    source.write_text("original")
    output = tmp_path / "result.json"
    output.write_text("export")
    record = new_run(str(source), {})
    record["status"] = "Completed"
    record["outputs"] = [{"kind": "JSON", "path": str(output)}]
    window.history.save(record)
    window.runs = [record]
    window.refresh_runs()
    prompts = []
    def answer(dialog):
        prompts.append(dialog)
        assert dialog.defaultButton().text() == "Cancel"
        assert str(output) in dialog.detailedText()
        assert "Original sensor files" in dialog.informativeText()
        assert "color: #22324a" in dialog.styleSheet()
        return QMessageBox.Yes if confirm else QMessageBox.Cancel
    monkeypatch.setattr(QMessageBox, "exec", answer)
    window.navigate(3)
    window.show()
    window.run_table.setFocus()
    QTest.qWait(30)
    QTest.keyClick(window.run_table, Qt.Key_Delete)
    app.processEvents()
    assert len(prompts) == 1
    assert source.read_text() == "original"
    assert output.exists() != confirm
    assert bool(window.runs) != confirm
    assert (window.history.directory / f"{record['id']}.json").exists() != confirm
    window.close()
