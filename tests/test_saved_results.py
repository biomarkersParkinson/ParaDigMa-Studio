"""Complete local snapshots, reopening, deletion and safe unsaved-run closing."""

import json
import logging
import multiprocessing
import pickle
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from paradigma_studio.app import MainWindow
from paradigma_studio.exports import ExportDialog, export_items
from paradigma_studio.history import load_result_export, new_run
from paradigma_studio.result_reopening import load_saved_results


def analyzed_run(window, results, tmp_path, name="sensor.csv"):
    source = tmp_path / name
    source.write_text("original recording", encoding="utf-8")
    record = new_run(str(source), {"pipelines": ["tremor"]})
    record["paradigma_version"] = "1.1.2"
    window._run_state.runs.insert(0, record)
    window._run_state.active_run = window._run_state.current_run = (
        window._run_state.selected_run
    ) = record
    window._result_state.provenance = {
        "source": str(source),
        "settings": record["settings"],
        "paradigma_version": "1.1.2",
        "run_id": record["id"],
        "display_clock": {"origin": "2026-10-10T12:00:00+00:00", "timezone": "UTC"},
    }
    window.analyzed(results)
    return record


def finish_job(window):
    deadline = time.monotonic() + 10
    while window._job_state.worker is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)  # Let background Python imports acquire the GIL.
    assert window._job_state.worker is None
    QTest.qWait(20)  # Deliver any requested close after the successful save.


def test_isolated_result_reader_retains_exact_values_and_cleans_private_files(
    tmp_path, tremor_outputs, monkeypatch
):
    from paradigma_studio import result_reopening
    from paradigma_studio.serialization import export_results

    frame = tremor_outputs["quantifications"]["tremor"]
    frame["precision"] = [np.nextafter(1.0, 2.0), -0.0, 1e-200]
    path = tmp_path / "saved.json"
    provenance = {"source": "missing.pkl", "settings": {"pipelines": ["tremor"]}}
    export_results(path, tremor_outputs, provenance)
    original = path.read_bytes()
    expected_provenance, expected = load_result_export(path)
    temporary = result_reopening.tempfile.TemporaryDirectory
    monkeypatch.setattr(
        result_reopening.tempfile,
        "TemporaryDirectory",
        lambda **kwargs: temporary(dir=tmp_path, **kwargs),
    )
    children = {child.pid for child in multiprocessing.active_children()}
    restored_provenance, restored = load_saved_results(
        path, logging.getLogger(__name__), isolate_bytes=0
    )
    assert restored_provenance == expected_provenance
    for stage in ("classifications", "quantifications"):
        pd.testing.assert_frame_equal(restored[stage]["tremor"], expected[stage]["tremor"])
    np.testing.assert_array_equal(
        restored["quantifications"]["tremor"].precision.to_numpy().view(np.uint64),
        expected["quantifications"]["tremor"].precision.to_numpy().view(np.uint64),
    )
    assert restored["aggregations"] == expected["aggregations"]
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("paradigma-result-open-*"))
    assert {child.pid for child in multiprocessing.active_children()} == children


@pytest.mark.parametrize("kind", ["json", "pickle"])
def test_isolated_result_reader_rejects_unsafe_input_and_retains_child_traceback(
    tmp_path, caplog, kind
):
    path = tmp_path / "malformed.json"
    marker = tmp_path / "unpickle-executed"
    if kind == "json":
        path.write_text('{"analysis":{},"results":')
    else:

        class Payload:
            def __reduce__(self):
                return Path.touch, (marker,)

        path.write_bytes(pickle.dumps(Payload()))
    children = {child.pid for child in multiprocessing.active_children()}
    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        load_saved_results(path, logging.getLogger(__name__), isolate_bytes=0)
    assert "Traceback (most recent call last)" in caplog.text
    assert ("JSONDecodeError" if kind == "json" else "UnicodeDecodeError") in caplog.text
    assert not marker.exists()
    assert {child.pid for child in multiprocessing.active_children()} == children


@pytest.mark.parametrize("failure", ["start", "exit", "eof"])
def test_result_reader_recovers_from_child_start_exit_and_pipe_failure(
    tmp_path, monkeypatch, failure
):
    from paradigma_studio import result_reopening

    path = tmp_path / "saved.json"
    path.write_text('{"analysis":{},"results":{}}')
    receiver, sender = Mock(), Mock()
    receiver.poll.return_value = failure == "eof"
    receiver.recv.side_effect = EOFError
    process = SimpleNamespace(
        pid=None if failure == "start" else 123,
        exitcode=9,
        start=Mock(side_effect=OSError("Start failed") if failure == "start" else None),
        is_alive=Mock(return_value=False),
        join=Mock(),
        close=Mock(),
    )
    context = SimpleNamespace(
        Pipe=Mock(return_value=(receiver, sender)), Process=Mock(return_value=process)
    )
    monkeypatch.setattr(result_reopening.multiprocessing, "get_context", lambda method: context)
    with pytest.raises((OSError, RuntimeError)):
        load_saved_results(path, logging.getLogger(__name__), isolate_bytes=0)
    receiver.close.assert_called()
    sender.close.assert_called()
    if failure != "start":
        process.close.assert_called_once()
    output = Path(context.Process.call_args.kwargs["args"][1])
    assert not output.parent.exists()


@pytest.mark.parametrize("cached", [False, True], ids=["disk", "memory"])
def test_reopening_prepares_off_thread_keeps_events_running_and_defers_graphs(
    window, tremor_outputs, tmp_path, monkeypatch, cached
):
    from paradigma_studio.serialization import export_results

    record = new_run("missing-sensor.pkl", {"pipelines": ["tremor"]})
    record["status"] = "Completed"
    provenance = {"source": record["source"], "settings": record["settings"]}
    original = tremor_outputs["quantifications"]["tremor"].copy(deep=True)
    if cached:
        record.update(_results=tremor_outputs, _provenance=provenance)
    else:
        path = tmp_path / "saved.json"
        export_results(path, tremor_outputs, provenance)
        record["outputs"] = [{"kind": "JSON", "path": str(path), "local": True}]
    window._run_state.runs = [record]
    window.refresh_runs()
    window.navigate(3)
    entered, release = threading.Event(), threading.Event()
    prepare = window._result_controller.prepare
    ui_thread, beats, rendered = threading.get_ident(), [], []

    def slow_prepare(*args):
        assert threading.get_ident() != ui_thread
        entered.set()
        assert release.wait(10)
        return prepare(*args)

    render = window._graph_controller._render_result_series
    monkeypatch.setattr(window._result_controller, "prepare", slow_prepare)
    monkeypatch.setattr(
        window._graph_controller,
        "_render_result_series",
        lambda *args: (rendered.append(threading.get_ident()), render(*args))[1],
    )
    timer = QTimer(window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: beats.append(True))
    try:
        window.open_run()
        deadline = time.monotonic() + 10
        while not entered.is_set() and time.monotonic() < deadline:
            QTest.qWait(10)
        assert entered.is_set() and window._job_state.worker is not None
        timer.start()
        QTest.qWait(50)
        assert len(beats) >= 2 and window.pages.currentIndex() == 3
        assert window._result_state.results is None and not rendered
        release.set()
        finish_job(window)
        assert window.pages.currentIndex() == 2 and window.result_tabs.currentIndex() == 0
        assert not rendered and not window._layout.graph_view.initialized
        pd.testing.assert_frame_equal(
            window._result_state.tables["quantifications/tremor"], original
        )
        pd.testing.assert_frame_equal(tremor_outputs["quantifications"]["tremor"], original)
        window.result_tabs.setCurrentIndex(1)
        QApplication.processEvents()
        assert rendered and all(thread == ui_thread for thread in rendered)
        assert window.figure.axes and not window._result_state._installing_results
    finally:
        release.set()
        timer.stop()
        finish_job(window)


def test_reopen_preparation_failure_keeps_previous_results_and_restores_controls(
    window, tremor_outputs
):
    window.analyzed(tremor_outputs)
    previous = window._result_state.results
    record = new_run("missing.csv", {"pipelines": ["tremor"]})
    record.update(
        status="Completed",
        _results=tremor_outputs,
        _provenance={"settings": {"plot_time_origin": {"mode": "custom", "clock": {}}}},
    )
    window._run_state.runs = [record]
    window.refresh_runs()
    window.navigate(3)
    window.open_run()
    finish_job(window)
    assert window._result_state.results is previous
    assert window._run_state.current_run is None and record["status"] == "Completed"
    assert window.open_button.isEnabled() and window.open_run_button.isEnabled()
    assert "Traceback (most recent call last)" in window.log.toPlainText()
    assert "Operation failed" in window.status.text()
    assert not window._result_state._installing_results


def test_reopen_replaces_existing_graphs_when_graphs_are_shown(window, monkeypatch):
    first = {"quantifications": {"test": pd.DataFrame({"time": [0.0, 1.0], "metric": [1, 2]})}}
    second = {"quantifications": {"test": pd.DataFrame({"time": [10.0, 20.0], "metric": [7, 9]})}}
    window.analyzed(first)
    window.result_tabs.setCurrentIndex(1)
    old = window.figure.axes[0]
    record = new_run("second.csv", {})
    record.update(status="Completed", _results=second)
    window._run_state.runs = [record]
    window.refresh_runs()
    window.navigate(3)
    rendered = []
    render = window._graph_controller._render_result_series
    monkeypatch.setattr(
        window._graph_controller,
        "_render_result_series",
        lambda *args: (rendered.append(True), render(*args))[1],
    )
    window.open_run()
    finish_job(window)
    assert not rendered and window.result_tabs.currentIndex() == 0
    window.result_tabs.setCurrentIndex(1)
    QApplication.processEvents()
    assert rendered and window.figure.axes[0] is not old
    assert window.figure.axes[0].get_xlim()[0] <= 10
    assert window.figure.axes[0].get_xlim()[1] >= 20
    pd.testing.assert_frame_equal(
        window._result_state.tables["quantifications/test"], second["quantifications"]["test"]
    )


def test_save_all_outputs_reopens_after_restart_and_remains_available_across_tabs(
    window, tremor_outputs, tmp_path
):
    tremor_outputs["metadata"]["desktop_preparation"] = {"excluded_samples": 2}
    record = analyzed_run(window, tremor_outputs, tmp_path)
    for tab in range(3):
        window.result_tabs.setCurrentIndex(tab)
        assert window.save_results_button.isVisible() and window.save_results_button.isEnabled()
    window.save_results_button.click()
    finish_job(window)
    assert not window.unsaved_result_runs()
    shown = window.run_table.model().frame.iloc[0]
    assert shown["Saved"] == "Yes" and shown["Exports"] == 0
    assert window.run_outputs.toPlainText() == "No exports."
    assert "Saved locally" in window.run_saved.toPlainText()
    saved = Path(record["outputs"][-1]["path"])
    assert saved.parent == window.history.directory / "results"
    provenance, results = load_result_export(saved)
    assert provenance == window._result_state.provenance
    for kind in ("classifications", "quantifications"):
        pd.testing.assert_frame_equal(results[kind]["tremor"], tremor_outputs[kind]["tremor"])
    assert results["aggregations"] == tremor_outputs["aggregations"]
    assert results["metadata"] == tremor_outputs["metadata"]
    assert results["errors"] == []
    assert not any(key.startswith("_") for key in json.loads(saved.read_text()))
    window.close()
    reopened = MainWindow(window.history.directory)
    reopened.show()
    try:
        assert not reopened.save_results_button.isEnabled()
        assert reopened._run_state.runs[0]["id"] == record["id"]
        reopened.open_run()
        finish_job(reopened)
        assert reopened.pages.currentIndex() == 2
        assert not reopened.unsaved_result_runs()
        assert reopened._result_state.result_source_frame is None
        assert reopened._result_state.display_clock == window._result_state.display_clock
        pd.testing.assert_frame_equal(
            reopened._result_state.results["quantifications"]["tremor"],
            tremor_outputs["quantifications"]["tremor"],
        )
    finally:
        reopened.close()
        QApplication.instance().processEvents()


def test_local_save_is_preferred_over_a_modified_export(window, tremor_outputs, tmp_path):
    from paradigma_studio.core import export_results

    record = analyzed_run(window, tremor_outputs, tmp_path)
    window.save_results()
    finish_job(window)
    changed = {
        **tremor_outputs,
        "quantifications": {
            "tremor": tremor_outputs["quantifications"]["tremor"].assign(tremor_power=999.0)
        },
    }
    path = tmp_path / "user-export.json"
    export_results(path, changed, window._result_state.provenance)
    window.record_output(path, "JSON")
    shown = window.run_table.model().frame.iloc[0]
    assert shown["Saved"] == "Yes" and shown["Exports"] == 1
    assert str(path) in window.run_outputs.toPlainText()
    assert str(path) not in window.run_saved.toPlainText()
    window.close()
    reopened = MainWindow(window.history.directory)
    try:
        reopened.open_run()
        finish_job(reopened)
        pd.testing.assert_frame_equal(
            reopened._result_state.results["quantifications"]["tremor"],
            tremor_outputs["quantifications"]["tremor"],
        )
        assert reopened._run_state.current_run["id"] == record["id"]
    finally:
        reopened.close()


def test_missing_local_snapshot_is_unsaved_even_if_exports_exist(window, tremor_outputs, tmp_path):
    record = analyzed_run(window, tremor_outputs, tmp_path)
    window.save_results()
    finish_job(window)
    Path(record["outputs"][-1]["path"]).unlink()
    window.refresh_runs()
    assert window.run_table.model().frame.iloc[0]["Saved"] == "No"
    assert "unavailable" in window.run_saved.toPlainText()
    assert window.unsaved_result_runs() == [record]


@pytest.mark.parametrize("destination", ["saved", "history"])
def test_exports_cannot_replace_saved_runs_or_their_history(
    window, tremor_outputs, tmp_path, monkeypatch, destination
):
    record = analyzed_run(window, tremor_outputs, tmp_path)
    window.save_results()
    finish_job(window)
    path = (
        Path(record["outputs"][-1]["path"])
        if destination == "saved"
        else window.history.directory / f"{record['id']}.json"
    )
    original = path.read_bytes()
    monkeypatch.setattr(ExportDialog, "exec", lambda dialog: True)
    monkeypatch.setattr(
        "paradigma_studio.app.QFileDialog.getSaveFileName", lambda *args: (str(path), "JSON")
    )
    window.choose_export()
    finish_job(window)
    assert path.read_bytes() == original
    assert "cannot overwrite a saved run" in window.notice.text()
    assert window.run_table.model().frame.iloc[0]["Exports"] == 0


def test_repeated_local_save_reuses_file_and_run_deletion_removes_it(
    window, tremor_outputs, tmp_path, monkeypatch
):
    record = analyzed_run(window, tremor_outputs, tmp_path)
    for _ in range(2):
        window.save_results()
        finish_job(window)
    assert len(record["outputs"]) == 1
    saved = Path(record["outputs"][0]["path"])
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: QMessageBox.Yes)
    window.delete_runs([record])
    assert not saved.exists()
    assert not (window.history.directory / f"{record['id']}.json").exists()
    assert Path(record["source"]).read_text() == "original recording"
    assert window._result_state.results is None and not window.save_results_button.isEnabled()


def test_save_does_not_block_navigation_or_allow_competing_operations(
    window, tremor_outputs, tmp_path, monkeypatch
):
    analyzed_run(window, tremor_outputs, tmp_path)
    started, release = threading.Event(), threading.Event()
    save = window.history.save_results

    def slow_save(*args):
        started.set()
        assert release.wait(5)
        return save(*args)

    monkeypatch.setattr(window.history, "save_results", slow_save)
    window.save_results()
    try:
        assert started.wait(2)
        assert not window.save_results_button.isEnabled()
        assert not window.delete_run_button.isEnabled()
        window.navigate(0)
        QApplication.instance().processEvents()
        assert window.pages.currentIndex() == 0
        assert (
            window.progress.isVisible()
            and window.progress.minimum() == window.progress.maximum() == 0
        )
        QTest.qWait(80)
        first = window.progress.grab().toImage()
        QTest.qWait(120)
        assert window.progress.grab().toImage() != first
    finally:
        release.set()
        finish_job(window)
    assert not window.unsaved_result_runs()
    assert window.pages.currentIndex() == 0


@pytest.mark.parametrize("answer", [QMessageBox.Cancel, QMessageBox.Discard, QMessageBox.Save])
def test_close_warns_and_respects_save_discard_and_cancel(
    window, tremor_outputs, tmp_path, monkeypatch, answer
):
    record = analyzed_run(window, tremor_outputs, tmp_path)
    prompts = []

    def respond(dialog):
        prompts.append(dialog)
        assert dialog.windowTitle() == "Unsaved results"
        assert dialog.defaultButton().text() == "Cancel"
        assert "color: #22324a" in dialog.styleSheet()
        assert "1 run(s)" in dialog.informativeText()
        return answer

    monkeypatch.setattr(QMessageBox, "exec", respond)
    window.close()
    finish_job(window)
    assert len(prompts) == 1
    assert window.isVisible() == (answer == QMessageBox.Cancel)
    restored, issues = window.history.load()
    assert not issues
    assert bool(restored[0]["outputs"]) == (answer == QMessageBox.Save)
    assert bool(window.unsaved_result_runs()) == (answer != QMessageBox.Save)
    assert Path(record["source"]).exists()
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: QMessageBox.Discard)


@pytest.mark.parametrize("save_current_first", [False, True])
def test_close_saves_all_unsaved_runs_even_when_another_run_is_displayed(
    window, tremor_outputs, tmp_path, monkeypatch, save_current_first
):
    first = analyzed_run(window, tremor_outputs, tmp_path, "first.csv")
    second = analyzed_run(window, tremor_outputs, tmp_path, "second.csv")
    if save_current_first:
        window.save_results()
        finish_job(window)
        assert window.unsaved_result_runs() == [first]
    else:
        assert len(window.unsaved_result_runs()) == 2
    # The warning must include unsaved earlier results, not only the current view.
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: QMessageBox.Save)
    window.close()
    finish_job(window)
    assert not window.isVisible() and not window.unsaved_result_runs()
    records, issues = window.history.load()
    assert not issues and len(records) == 2
    assert all(Path(record["outputs"][0]["path"]).exists() for record in records)
    assert second["outputs"][0]["local"]


@pytest.mark.parametrize(
    "failure", [OSError("Storage is full"), TypeError("Unsupported result value")]
)
def test_failed_history_save_keeps_window_open_and_results_unsaved(
    window, tremor_outputs, tmp_path, monkeypatch, failure
):
    record = analyzed_run(window, tremor_outputs, tmp_path)

    def fail(record):
        raise failure

    monkeypatch.setattr(window.history, "save", fail)
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: QMessageBox.Save)
    window.close()
    finish_job(window)
    assert window.isVisible() and window.unsaved_result_runs() == [record]
    assert record["outputs"] == []
    assert record["status"] == "Completed"
    assert str(failure) in window.notice.text()
    assert "Traceback" in window.log.toPlainText()
    assert "in fail" in window.log.toPlainText()
    assert not list((window.history.directory / "results").glob("*.json"))
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: QMessageBox.Discard)


@pytest.mark.parametrize("complete", [False, True])
def test_json_exports_remain_separate_from_local_saved_status(
    window, tremor_outputs, tmp_path, monkeypatch, complete
):
    record = analyzed_run(window, tremor_outputs, tmp_path)
    tables, metadata = export_items(tremor_outputs)
    chosen = [*tables, *metadata] if complete else ["quantifications/tremor"]
    monkeypatch.setattr(ExportDialog, "exec", lambda dialog: True)
    monkeypatch.setattr(ExportDialog, "selected", lambda dialog: chosen)
    monkeypatch.setattr(
        "paradigma_studio.app.QFileDialog.getSaveFileName",
        lambda *args: (str(tmp_path / "export.json"), "JSON"),
    )
    window.choose_export()
    finish_job(window)
    assert window.unsaved_result_runs() == [record]
    assert record["outputs"][-1]["complete"] == complete
    shown = window.run_table.model().frame.iloc[0]
    assert shown["Saved"] == "No" and shown["Exports"] == 1


def test_local_save_does_not_overwrite_original_recordings(window, tremor_outputs, tmp_path):
    record = analyzed_run(window, tremor_outputs, tmp_path)
    target = window.history.directory / "results" / f"{record['id']}.json"
    target.parent.mkdir()
    target.write_text("original sensor file")
    with pytest.raises(ValueError, match="overwrite"):
        window.history.save_results(
            record, tremor_outputs, window._result_state.provenance, protected_sources=[target]
        )
    assert target.read_text() == "original sensor file"


def test_failed_overwrite_retains_previous_saved_result(
    window, tremor_outputs, tmp_path, monkeypatch
):
    from paradigma_studio import serialization

    record = analyzed_run(window, tremor_outputs, tmp_path)
    window.save_results()
    finish_job(window)
    target = Path(record["outputs"][0]["path"])
    before = target.read_bytes()

    def fail(stream, value):
        stream.write("partial")
        raise OSError("Write failed")

    monkeypatch.setattr(serialization, "_write_json", fail)
    with pytest.raises(OSError, match="Write failed"):
        window.history.save_results(record, tremor_outputs, window._result_state.provenance)
    assert target.read_bytes() == before
    assert not list(target.parent.glob("*.tmp"))
