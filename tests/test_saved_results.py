"""Complete local snapshots, reopening, deletion and safe unsaved-run closing."""

import json
import threading
import time
from pathlib import Path

import pandas as pd
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from paradigma_desktop.app import MainWindow
from paradigma_desktop.exports import ExportDialog, export_items
from paradigma_desktop.history import load_result_export, new_run


def analyzed_run(window, results, tmp_path, name="sensor.csv"):
    source = tmp_path / name
    source.write_text("original recording", encoding="utf-8")
    record = new_run(str(source), {"pipelines": ["tremor"]})
    record["paradigma_version"] = "1.1.2"
    window.runs.insert(0, record)
    window.active_run = window.current_run = window.selected_run = record
    window.provenance = {
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
    while window.worker is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert window.worker is None
    QTest.qWait(20)  # Deliver any requested close after the successful save.


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
    saved = Path(record["outputs"][-1]["path"])
    assert saved.parent == window.history.directory / "results"
    provenance, results = load_result_export(saved)
    assert provenance == window.provenance
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
        assert reopened.runs[0]["id"] == record["id"]
        reopened.open_run()
        finish_job(reopened)
        assert reopened.pages.currentIndex() == 2
        assert not reopened.unsaved_result_runs()
        assert reopened.result_source_frame is None
        assert reopened.display_clock == window.display_clock
        pd.testing.assert_frame_equal(
            reopened.results["quantifications"]["tremor"],
            tremor_outputs["quantifications"]["tremor"],
        )
    finally:
        reopened.close()
        QApplication.instance().processEvents()


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
    assert window.results is None and not window.save_results_button.isEnabled()


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


def test_failed_history_save_keeps_window_open_and_results_unsaved(
    window, tremor_outputs, tmp_path, monkeypatch
):
    record = analyzed_run(window, tremor_outputs, tmp_path)

    def fail(record):
        raise OSError("Storage is full")

    monkeypatch.setattr(window.history, "save", fail)
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: QMessageBox.Save)
    window.close()
    finish_job(window)
    assert window.isVisible() and window.unsaved_result_runs() == [record]
    assert record["outputs"] == []
    assert record["status"] == "Completed"
    assert "Storage is full" in window.notice.text()
    assert not list((window.history.directory / "results").glob("*.json"))
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: QMessageBox.Discard)


@pytest.mark.parametrize("complete", [False, True])
def test_only_complete_json_export_clears_unsaved_warning(
    window, tremor_outputs, tmp_path, monkeypatch, complete
):
    record = analyzed_run(window, tremor_outputs, tmp_path)
    tables, metadata = export_items(tremor_outputs)
    chosen = [*tables, *metadata] if complete else ["quantifications/tremor"]
    monkeypatch.setattr(ExportDialog, "exec", lambda dialog: True)
    monkeypatch.setattr(ExportDialog, "selected", lambda dialog: chosen)
    monkeypatch.setattr(
        "paradigma_desktop.app.QFileDialog.getSaveFileName",
        lambda *args: (str(tmp_path / "export.json"), "JSON"),
    )
    window.choose_export()
    finish_job(window)
    assert bool(window.unsaved_result_runs()) != complete
    assert record["outputs"][-1]["complete"] == complete


def test_local_save_does_not_overwrite_original_recordings(window, tremor_outputs, tmp_path):
    record = analyzed_run(window, tremor_outputs, tmp_path)
    target = window.history.directory / "results" / f"{record['id']}.json"
    target.parent.mkdir()
    target.write_text("original sensor file")
    with pytest.raises(ValueError, match="overwrite"):
        window.history.save_results(
            record, tremor_outputs, window.provenance, protected_sources=[target]
        )
    assert target.read_text() == "original sensor file"


def test_failed_overwrite_retains_previous_saved_result(
    window, tremor_outputs, tmp_path, monkeypatch
):
    from paradigma_desktop import serialization

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
        window.history.save_results(record, tremor_outputs, window.provenance)
    assert target.read_bytes() == before
    assert not list(target.parent.glob("*.tmp"))
