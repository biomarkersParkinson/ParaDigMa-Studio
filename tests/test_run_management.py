"""Cancellation, process cleanup and confirmed deletion of owned exports."""

import json
import logging
import time
from threading import Event

import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from run_fixtures import export_receipt, make_run

from paradigma_studio import analysis_process, app as desktop
from paradigma_studio.app import MainWindow, Worker
from paradigma_studio.history import RunHistory, run_is_saved
from paradigma_studio.run_controller import RunController


def test_history_never_persists_or_restores_transient_workspace_caches(tmp_path, tremor_outputs):
    history = RunHistory(tmp_path / "runs")
    record = make_run("sensor.csv", {})
    record.update(
        _frame=pd.DataFrame({"time": [0.0]}),
        _results=tremor_outputs,
        _provenance={"source": "sensor.csv"},
        _unsaved_results=True,
    )
    history.save(record)
    path = history.directory / f"{record['id']}.json"
    public = json.loads(path.read_text(encoding="utf-8"))
    assert not any(key.startswith("_") for key in public)
    public.update(_frame="not a frame", _results={"cached": True}, _unsaved_results=True)
    path.write_text(json.dumps(public), encoding="utf-8")
    before = path.read_bytes()
    restored, issues = history.load()
    assert not issues and len(restored) == 1
    assert not any(key.startswith("_") for key in restored[0])
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "invalid",
    [{"status": "Unknown"}, {"paradigma_version": 112}, {"finished": False}],
    ids=["unknown-status", "numeric-version", "boolean-finish-time"],
)
def test_malformed_run_fields_skip_only_the_damaged_history_entry(tmp_path, invalid):
    history = RunHistory(tmp_path / "runs")
    good, bad = make_run("good.csv", {}), make_run("bad.csv", {})
    bad.update(invalid)
    for record in (good, bad):
        history.save(record)
    restored, issues = history.load()
    assert [record["id"] for record in restored] == [good["id"]]
    assert len(issues) == 1 and bad["id"] in issues[0]


@pytest.mark.parametrize(
    "invalid",
    [
        {"kind": "ZIP"},
        {"path": None},
        {"local": "false"},
        {"complete": "false"},
        {"saved": 123},
        {"dataset": []},
        {"selected": "quantifications/tremor"},
        {"selected": [42]},
        {"selected_rows": True},
        {"selected_rows": -1},
        {"selected_rows": 1.5},
        {"selection": []},
        {"sha256": "invalid"},
        {"sha256": 123},
    ],
)
def test_malformed_output_metadata_cannot_change_saved_or_export_state(tmp_path, invalid):
    history = RunHistory(tmp_path / "runs")
    output = tmp_path / "result.json"
    output.write_text("{}", encoding="utf-8")
    good, bad = make_run("good.csv", {}), make_run("bad.csv", {})
    good["outputs"] = [
        {
            "kind": "JSON",
            "path": str(output),
            "local": False,
            "complete": False,
            "saved": "2026-10-23T00:00:00+00:00",
            "sha256": "0" * 64,
            "dataset": "quantifications/tremor",
            "selected": ["quantifications/tremor"],
            "selected_rows": 0,
            "selection": {"scope": "Full run"},
        }
    ]
    bad["outputs"] = [{**good["outputs"][0], **invalid}]
    for record in (good, bad):
        history.save(record)
    restored, issues = history.load()
    assert [record["id"] for record in restored] == [good["id"]]
    assert restored[0]["outputs"] == good["outputs"]
    assert not run_is_saved(restored[0])
    assert RunController.reopen_output(restored[0]) is None
    assert len(issues) == 1 and bad["id"] in issues[0]


def slow_child(input_path, output_path, settings, queue):
    queue.put(("log", logging.INFO, "Child started"))
    time.sleep(60)


def wait_for(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert predicate()


def test_stopping_an_owned_analysis_process_cleans_temporary_files(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(analysis_process, "_analyze_child", slow_child)
    original = analysis_process.tempfile.TemporaryDirectory
    monkeypatch.setattr(
        analysis_process.tempfile,
        "TemporaryDirectory",
        lambda **kwargs: original(dir=tmp_path, **kwargs),
    )
    cancel = Event()
    messages, cancelled, completed, failed = [], [], [], []
    worker = Worker(
        lambda logger: analysis_process.run_isolated_analysis(
            pd.DataFrame({"time": [0.0]}), {}, logger, cancel
        )
    )
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
    _app = QApplication.instance() or QApplication([])
    window = MainWindow(history_dir=tmp_path / "runs")

    def run(frame, settings, logger, cancel):
        while not cancel.wait(0.01):
            pass
        raise analysis_process.AnalysisCancelled()

    monkeypatch.setattr(desktop, "run_isolated_analysis", run)
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0.0, 1.0]})))
    window.run_analysis()
    assert window.stop_button.isEnabled() and not window.run_button.isEnabled()
    assert window.stop_button.parentWidget() is window.status_row
    assert not window.delete_run_button.isEnabled()
    window.stop_button.click()
    wait_for(lambda: window._job_state.worker is None)
    record = window._run_state.runs[0]
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
    first, second = make_run(str(source), {}), make_run(str(source), {})
    first["status"], second["status"] = "Cancelled", "Completed"
    first["outputs"] = [
        export_receipt(path, "CSV") for path in (source, binary, export, shared, directory)
    ]
    second["outputs"] = [export_receipt(shared)]
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
    record = make_run(str(source), {})
    record["status"] = "Completed"
    record["outputs"] = [export_receipt(output)]
    window.history.save(record)
    window._run_state.runs = [record]
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
    assert bool(window._run_state.runs) != confirm
    assert (window.history.directory / f"{record['id']}.json").exists() != confirm
    window.close()


def test_parameter_and_delete_actions_are_adjacent(window):
    window.navigate(3)
    QTest.qWait(30)
    use, delete = window.use_parameters_button, window.delete_run_button
    assert delete.y() == use.y() and 0 < delete.x() - (use.x() + use.width()) <= 20
