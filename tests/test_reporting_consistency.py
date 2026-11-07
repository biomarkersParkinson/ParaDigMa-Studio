"""Reporting remains owned, persistent and consistent across operation boundaries."""

import logging
import time
from copy import deepcopy
from threading import Event

import pandas as pd
import pytest
from conftest import wait_for_previews
from gui_helpers import wait_until
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel
from run_fixtures import make_run

from paradigma_studio.error_reporting import merge_errors
from paradigma_studio.exports import ExportDialog
from paradigma_studio.history import now
from paradigma_studio.module_issues import result_issue_summary
from paradigma_studio.provenance import run_provenance
from paradigma_studio.serialization import export_results


def wait_for_job(window):
    deadline = time.monotonic() + 10
    while window._job_state.worker is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)  # Allow cold Python imports in the worker to acquire the GIL.
    assert window._job_state.worker is None


def returned_error(**changes):
    return {
        "pipeline": "tremor",
        "stage": "pipeline_execution",
        "file": "segment_1",
        "error": "Classification failed: Original failure",
        **changes,
    }


def outputs(errors=()):
    return {
        "errors": list(errors),
        "quantifications": {"tremor": pd.DataFrame({"time": [0.0], "tremor_power": [1.0]})},
    }


def install(window, values, *, errors=(), active=False):
    record = make_run()
    record.update(
        status="Running" if active else "Completed",
        finished=None if active else now(),
        errors=list(errors),
    )
    record["_results"] = values
    record["_provenance"] = run_provenance(record)
    window._run_state.runs.insert(0, record)
    window._run_state.current_run = window._run_state.selected_run = record
    window._run_state.active_run = record if active else None
    window._result_state.provenance = dict(record["_provenance"])
    window.history.save(record)
    window.refresh_runs()
    return record


@pytest.mark.parametrize("context", ["Export", "Open results", "Save results"])
def test_operation_problems_persist_on_the_owner_even_after_history_selection_changes(
    window, context
):
    owner = install(window, outputs())
    other = make_run("other.csv")
    window._run_state.runs.insert(0, other)
    entered, release = Event(), Event()

    def operation(logger):
        entered.set()
        assert release.wait(10)
        logger.warning("Original operation warning")
        raise OSError("Original operation failure")

    window._job_controller.start_job(operation, lambda _: None, owner=owner, context=context)
    try:
        wait_until(entered.is_set)
        window.refresh_runs()
        window.run_table.setCurrentIndex(window.run_table.model().index(0, 0))
        assert window._run_state.selected_run is other
    finally:
        release.set()
        wait_for_job(window)
    assert owner["status"] == "Completed" and other["errors"] == other["warnings"] == []
    stored, issues = window.history.load()
    assert not issues
    restored = next(record for record in stored if record["id"] == owner["id"])
    assert restored["errors"] == [f"{context}: OSError: Original operation failure"]
    assert restored["warnings"] == [f"{context}: Original operation warning"]
    assert "Traceback" in restored["log"] and "in operation" in restored["log"]
    summary = result_issue_summary(outputs(), run_provenance(owner), restored["errors"])
    assert "operation error" in summary.message and "processing error" not in summary.message


def test_reopening_uses_all_owned_diagnostics_without_replaying_completion(window):
    error = returned_error()
    orphan = "Failed to aggregate tremor results: Original log-only failure"
    values = outputs([error])
    owner = install(window, values, errors=merge_errors([orphan], [error]))
    owner.update(status="Partial", warnings=["Original warning"])
    original = deepcopy({key: owner[key] for key in ("status", "finished", "warnings", "errors")})
    for _ in range(2):
        window._run_controller.open_run()
        wait_for_job(window)
        assert "2 processing errors" in window.notice.text() and "1 warning" in window.notice.text()
        assert window.notice.property("severity") == "warning"
        card = window._result_state.overview_module_cards["tremor"]
        notice = next(item for item in card.findChildren(QLabel) if item.objectName() == "notice")
        assert "2 processing errors" in notice.text() and notice.property("severity") == "warning"
        assert {key: owner[key] for key in original} == original
        pd.testing.assert_frame_equal(
            window._result_state.results["quantifications"]["tremor"],
            values["quantifications"]["tremor"],
        )


@pytest.mark.parametrize("available", [True, False])
def test_skip_only_outcomes_agree_in_banner_and_module_card(window, available):
    skip = returned_error(stage="preparation", skipped=True, error="Skipped recording: Too short")
    values = outputs([skip]) if available else {"errors": [skip]}
    owner = install(window, values, active=True)
    window.analyzed(values)
    assert "processing error" not in window.notice.text()
    assert "skipped" in window.notice.text().lower()
    expected = "warning" if available else "error"
    assert window.notice.property("severity") == expected
    card = window._result_state.overview_module_cards["tremor"]
    notice = next(item for item in card.findChildren(QLabel) if item.objectName() == "notice")
    assert notice.property("severity") == expected and owner["status"] == "Partial"


def test_empty_outcome_is_neutral_and_reopening_does_not_add_warnings(window):
    values = {"quantifications": {"tremor": pd.DataFrame()}, "errors": []}
    owner = install(window, values, active=True)
    window.analyzed(values)
    for _ in range(2):
        window._run_controller.open_run()
        wait_for_job(window)
        assert owner["status"] == "Completed" and owner["errors"] == owner["warnings"] == []
        assert "No quantified windows" in window.status.text()
        assert not window.notice.text()


@pytest.mark.parametrize("obsolete", [False, True])
def test_preview_failure_keeps_original_owner_and_only_current_failures_show_warnings(
    window, obsolete
):
    original = window._run_controller.start_loading(["first.csv"])
    data = pd.DataFrame({"time": [0.0, 1.0]})
    window.loaded(("first.csv", data))
    wait_for_previews(window)
    preview = window._time_preview
    entered, release = Event(), Event()

    def fail():
        entered.set()
        assert release.wait(10)
        raise ValueError("Original preview failure")

    preview.request("held-preview", fail)
    try:
        wait_until(entered.is_set)
        if obsolete:
            preview.clear()
            current = window._run_controller.start_loading(["second.csv"])
        release.set()
        wait_for_previews(window)
    finally:
        release.set()
    assert "Original preview failure" in original["log"] and "in fail" in original["log"]
    if obsolete:
        assert "Original preview failure" not in current["log"] and not original["warnings"]
        assert "Original preview failure" not in window.notice.text()
    else:
        assert original["warnings"] == [
            "Recording preview unavailable: ValueError: Original preview failure"
        ]
        assert "Recording preview unavailable" in window.notice.text()
    stored, _ = window.history.load()
    owner = next(record for record in stored if record["id"] == original["id"])
    assert owner["warnings"] == original["warnings"] and owner["log"] == original["log"]


def test_loading_compatibility_warning_is_counted_and_saved_with_loading_context(window):
    record = window._run_controller.start_loading(["sensor.avro"])
    data = pd.DataFrame(
        {"time": [0.0, 0.01, 0.02], **{f"accelerometer_{axis}": [0.1, 0.2, 0.3] for axis in "xyz"}}
    )
    data.attrs["source_format"] = "empatica"
    window.loaded(("sensor.avro", data))
    assert record["status"] == "Loaded"
    assert record["warnings"] == record["loading"]["warnings"] == [window.notice.text()]
    assert window.run_table.model().frame.loc[0, "Warnings"] == 1
    stored, issues = window.history.load()
    assert not issues and stored[0]["warnings"] == record["warnings"]
    assert stored[0]["loading"]["warnings"] == record["warnings"]


def test_failed_reopening_records_its_operation_without_changing_the_analysis(window, tmp_path):
    values = outputs()
    owner = install(window, values)
    path = tmp_path / "saved.json"
    export_results(path, values, owner["_provenance"])
    original = path.read_bytes()
    owner["outputs"] = [
        {
            "kind": "JSON",
            "path": str(path),
            "local": True,
            "complete": True,
            "saved": now(),
            "sha256": "0" * 64,
        }
    ]
    owner.pop("_results")
    window.history.save(owner)
    window._run_controller.open_run()
    wait_for_job(window)
    assert path.read_bytes() == original and owner["status"] == "Completed"
    stored, issues = window.history.load()
    assert not issues and stored[0]["errors"][0].startswith("Open results: ")
    assert "Traceback" in stored[0]["log"] and "checksum" in stored[0]["errors"][0].lower()


def test_operation_warning_updates_status_label_count_and_saved_history(window):
    owner = install(window, outputs())
    window._job_controller.start_job(
        lambda logger: logger.warning("Original warning"),
        lambda _: None,
        owner=owner,
        context="Export",
    )
    wait_for_job(window)
    assert window.run_table.model().frame.loc[0, "Status"] == "Completed with warnings"
    assert window.run_table.model().frame.loc[0, "Warnings"] == 1
    assert window._layout.run_heading.text().startswith("Completed with warnings")
    stored, _ = window.history.load()
    assert stored[0]["warnings"] == ["Export: Original warning"]


def test_bulk_save_routes_warnings_to_individual_records(window, monkeypatch):
    first = install(window, outputs())
    second = install(window, outputs())
    original = window.history.save_results

    def save(record, *args, **kwargs):
        logging.getLogger("paradigma").warning(f"Original warning for {record['id']}")
        return original(record, *args, **kwargs)

    monkeypatch.setattr(window.history, "save_results", save)
    window._run_controller.save_run_results([first, second])
    wait_for_job(window)
    stored, issues = window.history.load()
    assert not issues
    for record in stored:
        message = f"Original warning for {record['id']}"
        assert record["warnings"] == [f"Save results: {message}"]
        assert record["log"].count(message) == 1 and record["status"] == "Completed"


def test_diagnostic_persistence_failure_is_visible_without_recursive_saves(window, monkeypatch):
    owner = install(window, outputs())
    calls = []

    def unavailable(record):
        calls.append(record["id"])
        raise OSError("Original history write failure")

    monkeypatch.setattr(window.history, "save", unavailable)
    window._job_controller.start_job(
        lambda logger: logger.warning("Original warning"),
        lambda _: None,
        owner=owner,
        context="Export",
    )
    wait_for_job(window)
    assert calls == [owner["id"]]
    assert "Run history could not be saved" in window.notice.text()
    assert "Original history write failure" in window.notice.text()
    assert owner["warnings"] == ["Export: Original warning"] and owner["_history_dirty"]


def test_preview_diagnostics_survive_a_concurrent_snapshot_writer(window, monkeypatch):
    owner = install(window, outputs())
    window._input_state.load_run_id = owner["id"]
    entered, release = Event(), Event()
    original = window.history.save_results

    def held(record, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(record, *args, **kwargs)

    def fail_preview():
        raise ValueError("Original concurrent preview failure")

    monkeypatch.setattr(window.history, "save_results", held)
    window._run_controller.save_run_results([owner])
    try:
        wait_until(entered.is_set)
        window._time_preview.request("concurrent-preview", fail_preview)
        wait_for_previews(window)
        assert "Original concurrent preview failure" in owner["log"]
        release.set()
        wait_for_job(window)
    finally:
        release.set()
    stored, issues = window.history.load()
    assert not issues and stored[0]["warnings"] == owner["warnings"]
    assert "Original concurrent preview failure" in stored[0]["log"]
    assert "in fail_preview" in stored[0]["log"]


def test_pending_import_does_not_take_ownership_of_previews_of_previous_inputs(window):
    previous = window._run_controller.start_loading(["previous.csv"])
    window.loaded(("previous.csv", pd.DataFrame({"time": [0.0, 1.0]})))
    wait_for_previews(window)
    pending = window._run_controller.start_loading(["pending.csv"])

    def fail():
        raise ValueError("Original previous-input preview failure")

    window._time_preview.request("previous-inputs-during-import", fail)
    wait_for_previews(window)
    assert previous["warnings"] == [
        "Recording preview unavailable: ValueError: Original previous-input preview failure"
    ]
    assert "Original previous-input preview failure" in previous["log"]
    assert pending["warnings"] == pending["errors"] == []
    assert "Original previous-input preview failure" not in pending["log"]


@pytest.mark.parametrize("error", [OSError, RuntimeError])
def test_inaccessible_export_destination_is_reported_before_any_write(window, monkeypatch, error):
    owner = install(window, outputs())
    window._result_state.results = owner["_results"]
    metadata = window.history.directory / f"{owner['id']}.json"
    original = metadata.read_bytes()
    monkeypatch.setattr(ExportDialog, "exec", lambda _: True)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(metadata), "JSON"))

    def unavailable(*args):
        raise error("Original destination check failure")

    monkeypatch.setattr(window.history, "validate_export_destination", unavailable)
    window._export_controller.choose_export()
    assert window._job_state.worker is None and owner["errors"] == []
    assert window.notice.text() == "Original destination check failure"
    assert window.notice.property("severity") == "error" and metadata.read_bytes() == original
