"""Owned result files must match their recorded bytes and selected run."""

import hashlib
import json
import logging
from pathlib import Path

import pandas as pd
import pytest
from conftest import wait_for_job
from PySide6.QtTest import QTest
from run_fixtures import make_run

from paradigma_studio.history import RunHistory
from paradigma_studio.result_integrity import provenance_for_run
from paradigma_studio.result_reopening import load_saved_results
from paradigma_studio.serialization import export_results


def owned_output(path, results):
    record = make_run("sensor.csv", {"pipelines": ["tremor"]})
    record["status"] = "Completed"
    provenance = {
        "run_id": record["id"],
        "source": record["source"],
        "settings": record["settings"],
    }
    checksum = export_results(path, results, provenance)
    record["outputs"] = [
        {
            "kind": "JSON",
            "path": str(path),
            "complete": True,
            "sha256": checksum,
            "saved": "2026-10-24T00:00:00Z",
        }
    ]
    return record, provenance, checksum


def test_export_fingerprint_covers_exact_committed_bytes_without_another_read(
    tmp_path, monkeypatch
):
    path = tmp_path / "results.json"
    results = {"table": pd.DataFrame({"value": range(2003)}), "label": 'µ\nquoted"'}

    def unexpected_read(path):
        raise AssertionError("An export must hash its writes, not reread a possibly replaced path")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    _, _, checksum = owned_output(path, results)
    with path.open("rb") as stream:
        raw = stream.read()
    assert checksum == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw)["results"]["label"] == results["label"]


@pytest.mark.parametrize("isolate_bytes", [0, 10**9], ids=["isolated", "small"])
def test_verified_read_preserves_values_after_restart(tmp_path, tremor_outputs, isolate_bytes):
    path = tmp_path / "export.json"
    history = RunHistory(tmp_path / "runs")
    record, provenance, checksum = owned_output(path, tremor_outputs)
    history.save(record)
    records, issues = RunHistory(history.directory).load()
    assert not issues and records[0]["outputs"][0]["sha256"] == checksum
    restored_provenance, results = load_saved_results(
        path,
        logging.getLogger(__name__),
        run_id=records[0]["id"],
        checksum=records[0]["outputs"][0]["sha256"],
        isolate_bytes=isolate_bytes,
    )
    assert restored_provenance == provenance
    pd.testing.assert_frame_equal(
        results["quantifications"]["tremor"], tremor_outputs["quantifications"]["tremor"]
    )


@pytest.mark.parametrize("isolate_bytes", [0, 10**9], ids=["isolated", "small"])
@pytest.mark.parametrize(
    "problem", ["missing_checksum", "invalid_checksum", "missing_id", "different_id", "edited"]
)
def test_both_reader_paths_reject_unverified_or_changed_files(
    tmp_path, tremor_outputs, isolate_bytes, problem
):
    path = tmp_path / "export.json"
    record, provenance, checksum = owned_output(path, tremor_outputs)
    message = "checksum"
    if problem == "missing_checksum":
        checksum = None
    elif problem == "invalid_checksum":
        checksum = "invalid"
    elif problem == "missing_id":
        provenance.pop("run_id")
        checksum = export_results(path, tremor_outputs, provenance)
        message = "run ID"
    elif problem == "different_id":
        provenance["run_id"] = make_run("other.csv", {})["id"]
        checksum = export_results(path, tremor_outputs, provenance)
        message = "different run"
    else:
        changed = {**tremor_outputs, "errors": ["edited"]}
        export_results(path, changed, provenance)
    before = path.read_bytes()
    with pytest.raises(ValueError, match=message):
        load_saved_results(
            path,
            logging.getLogger(__name__),
            run_id=record["id"],
            checksum=checksum,
            isolate_bytes=isolate_bytes,
        )
    assert path.read_bytes() == before


def test_verification_and_decoding_use_the_same_read_buffer(tmp_path, tremor_outputs, monkeypatch):
    path = tmp_path / "export.json"
    record, provenance, checksum = owned_output(path, tremor_outputs)
    read = Path.read_bytes

    def replace_after_read(source):
        raw = read(source)
        source.write_text('{"analysis":{},"results":{"replaced":true}}')
        return raw

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    restored_provenance, restored = load_saved_results(
        path, logging.getLogger(__name__), run_id=record["id"], checksum=checksum
    )
    assert restored_provenance == provenance
    assert "replaced" not in restored
    pd.testing.assert_frame_equal(
        restored["quantifications"]["tremor"], tremor_outputs["quantifications"]["tremor"]
    )
    assert json.loads(path.read_text())["results"] == {"replaced": True}


@pytest.mark.parametrize(
    "problem", ["reused_filename", "same_id_edit", "missing_id", "different_id"]
)
def test_failed_reopen_keeps_displayed_results_and_restores_controls(
    window, tmp_path, tremor_outputs, problem
):
    path = tmp_path / "export.json"
    record, provenance, checksum = owned_output(path, tremor_outputs)
    if problem == "reused_filename":
        record["outputs"].append(
            {
                "kind": "JSON",
                "path": str(tmp_path / "missing-snapshot.json"),
                "local": True,
                "complete": True,
                "saved": "2026-10-24T00:00:00Z",
                "sha256": checksum,
            }
        )
        owned_output(path, {**tremor_outputs, "errors": ["from another run"]})
    elif problem == "same_id_edit":
        export_results(path, {**tremor_outputs, "errors": ["edited"]}, provenance)
    elif problem == "missing_id":
        provenance.pop("run_id")
        record["outputs"][0]["sha256"] = export_results(path, tremor_outputs, provenance)
    else:
        provenance["run_id"] = make_run("other.csv", {})["id"]
        record["outputs"][0]["sha256"] = export_results(path, tremor_outputs, provenance)
    # Reload the disk history without an in-memory result cache.
    window.history.save(record)
    window._run_state.runs, issues = window.history.load()
    assert not issues
    window.analyzed(tremor_outputs)
    previous_results = window._result_state.results
    previous_provenance = window._result_state.provenance
    previous_run = window._run_state.current_run
    window.refresh_runs()
    window.navigate(3)
    window.open_run()
    wait_for_job(window)
    QTest.qWait(20)
    assert window._result_state.results is previous_results
    assert window._result_state.provenance is previous_provenance
    assert window._run_state.current_run is previous_run
    message = (
        "run ID"
        if problem == "missing_id"
        else "different run"
        if problem == "different_id"
        else "checksum"
    )
    assert message in window.notice.text()
    assert window.settings_panel.isEnabled() and window.open_run_button.isEnabled()
    assert window.pages.currentIndex() == 3
    assert "_results" not in window._run_state.runs[0]


def test_history_failure_keeps_previous_snapshot_and_matching_fingerprint(
    tmp_path, tremor_outputs, monkeypatch
):
    history = RunHistory(tmp_path / "runs")
    record = make_run("sensor.csv", {"pipelines": ["tremor"]})
    record["outputs"] = history.save_results(record, tremor_outputs, {})
    old_output = record["outputs"][0]
    old_bytes = Path(old_output["path"]).read_bytes()
    metadata = history.directory / f"{record['id']}.json"
    old_history = metadata.read_bytes()

    def fail_save(record):
        raise OSError("History write failed")

    monkeypatch.setattr(history, "save", fail_save)
    with pytest.raises(OSError, match="History write failed"):
        history.save_results(record, {**tremor_outputs, "errors": ["new values"]}, {})
    assert metadata.read_bytes() == old_history
    assert Path(old_output["path"]).read_bytes() == old_bytes
    assert list((history.directory / "results").iterdir()) == [Path(old_output["path"])]
    _, restored = load_saved_results(
        old_output["path"],
        logging.getLogger(__name__),
        run_id=record["id"],
        checksum=old_output["sha256"],
    )
    assert restored["errors"] == []


def test_successful_resave_publishes_new_fingerprint_and_removes_previous_snapshot(
    tmp_path, tremor_outputs
):
    history = RunHistory(tmp_path / "runs")
    record = make_run("sensor.csv", {"pipelines": ["tremor"]})
    record["outputs"] = history.save_results(record, tremor_outputs, {})
    previous = Path(record["outputs"][0]["path"])
    next_outputs = history.save_results(record, {**tremor_outputs, "errors": ["new values"]}, {})
    records, issues = history.load()
    assert not issues and records[0]["outputs"] == next_outputs
    assert not previous.exists()
    output = next_outputs[0]
    assert list((history.directory / "results").iterdir()) == [Path(output["path"])]
    _, restored = load_saved_results(
        output["path"], logging.getLogger(__name__), run_id=record["id"], checksum=output["sha256"]
    )
    assert restored["errors"] == ["new values"]


def test_owned_writes_reject_another_runs_provenance_without_modifying_it():
    record = make_run("sensor.csv", {})
    other = {"run_id": make_run("other.csv", {})["id"]}
    before = dict(other)
    with pytest.raises(ValueError, match="different run"):
        provenance_for_run(other, record["id"])
    assert other == before


def test_contradictory_snapshot_identity_leaves_files_and_history_unchanged(
    tmp_path, tremor_outputs
):
    history = RunHistory(tmp_path / "runs")
    record = make_run("sensor.csv", {})
    record["outputs"] = history.save_results(record, tremor_outputs, {})
    previous = Path(record["outputs"][0]["path"])
    before = previous.read_bytes()
    with pytest.raises(ValueError, match="different run"):
        history.save_results(record, tremor_outputs, {"run_id": make_run("other.csv", {})["id"]})
    records, issues = history.load()
    assert not issues and records[0]["outputs"] == record["outputs"]
    assert previous.read_bytes() == before
    assert list(previous.parent.iterdir()) == [previous]


def test_old_snapshot_cleanup_failure_leaves_new_snapshot_verified_and_usable(
    tmp_path, tremor_outputs, monkeypatch, caplog
):
    history = RunHistory(tmp_path / "runs")
    record = make_run("sensor.csv", {})
    record["outputs"] = history.save_results(record, tremor_outputs, {})
    previous = Path(record["outputs"][0]["path"])
    unlink = Path.unlink

    def locked_snapshot(path, *args, **kwargs):
        if path == previous:
            raise OSError("Snapshot is locked")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_snapshot)
    outputs = history.save_results(record, {**tremor_outputs, "errors": ["updated"]}, {})
    records, issues = history.load()
    assert not issues and records[0]["outputs"] == outputs
    assert previous.exists() and "Snapshot is locked" in caplog.text
    output = outputs[0]
    _, restored = load_saved_results(
        output["path"], logging.getLogger(__name__), run_id=record["id"], checksum=output["sha256"]
    )
    assert restored["errors"] == ["updated"]


@pytest.mark.parametrize("protected", ["source", "outside_directory"])
def test_resaving_does_not_remove_protected_or_unowned_old_files(
    tmp_path, tremor_outputs, protected
):
    history = RunHistory(tmp_path / "runs")
    record = make_run("sensor.csv", {})
    record["outputs"] = history.save_results(record, tremor_outputs, {})
    previous = Path(record["outputs"][0]["path"])
    if protected == "outside_directory":
        moved = tmp_path / previous.name
        previous.rename(moved)
        previous = moved
        record["outputs"][0]["path"] = str(previous)
    sources = [previous] if protected == "source" else []
    before = previous.read_bytes()
    history.save_results(record, tremor_outputs, {}, protected_sources=iter(sources))
    assert previous.read_bytes() == before
