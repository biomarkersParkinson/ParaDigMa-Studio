"""Analysis-time software identity survives saving, reopening and later exports."""

import hashlib
import json
import subprocess
import time
from types import SimpleNamespace
from zipfile import ZipFile

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication
from run_fixtures import make_run

from paradigma_studio import provenance
from paradigma_studio.exports import export_selection
from paradigma_studio.history import RunHistory, load_result_export
from paradigma_studio.provenance import provenance_for_record, run_provenance
from paradigma_studio.serialization import csv_metadata_path, export_table_csv


@pytest.mark.parametrize("format_name", ["JSON", "ZIP", "CSV", "rows"])
def test_app_export_actions_retain_the_run_versions_and_record_companions(
    window, tmp_path, monkeypatch, tremor_outputs, format_name
):
    from paradigma_studio import app as desktop
    from paradigma_studio.exports import ExportDialog

    record = make_run()
    record.update(studio_version="0.7.0", paradigma_version="1.1.2", studio_build_commit="a" * 40)
    window._run_state.runs = [record]
    window._run_state.current_run = window._run_state.selected_run = record
    origin = run_provenance(record)
    window._result_state.provenance = origin
    window.analyzed(tremor_outputs)
    path = tmp_path / f"export.{format_name.lower() if format_name != 'rows' else 'csv'}"
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *a: (str(path), ""))
    monkeypatch.setattr(provenance, "version", lambda _: pytest.fail("resolved current version"))
    monkeypatch.setattr(ExportDialog, "exec", lambda self: True)
    selected = ["quantifications/tremor"]
    if format_name == "ZIP":
        selected.append("metadata/tremor")
    monkeypatch.setattr(ExportDialog, "selected", lambda self: selected)
    if format_name == "rows":
        window.export_csv()
    else:
        original = ExportDialog.__init__

        def configure(dialog, *args):
            original(dialog, *args)
            dialog.format.setCurrentText("JSON" if format_name == "JSON" else "CSV")

        monkeypatch.setattr(ExportDialog, "__init__", configure)
        window.choose_export()
    deadline = time.monotonic() + 5
    while window._job_state.worker is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert window._job_state.worker is None and path.exists()
    receipt = record["outputs"][-1]
    if format_name in ("CSV", "rows"):
        companion = csv_metadata_path(path)
        saved = json.loads(companion.read_text())["analysis"]
        assert receipt["metadata_path"] == str(companion)
        assert companion.name in window.run_outputs.toPlainText()
    elif format_name == "ZIP":
        with ZipFile(path) as archive:
            saved = json.loads(archive.read("analysis.json"))
    else:
        saved, _ = load_result_export(path)
    assert saved["studio_version"] == "0.7.0" and saved["studio_build_commit"] == "a" * 40
    assert "Studio 0.7.0" in window.run_summary.text()
    assert "ParaDigMa 1.1.2" in window.run_summary.text()


@pytest.mark.parametrize("status", ["Completed", "Failed", "Cancelled"])
def test_run_captures_software_before_work_and_keeps_it_after_environment_changes(
    tmp_path, monkeypatch, status
):
    versions = {"paradigma-studio": "0.7.0", "paradigma": "1.1.2"}
    monkeypatch.setattr(provenance, "version", versions.__getitem__)
    monkeypatch.setattr(provenance, "_build_commit", lambda: "a" * 40)
    record = make_run()
    assert record["studio_version"] == "0.7.0"
    assert record["paradigma_version"] == "1.1.2"
    assert record["studio_build_commit"] == "a" * 40
    versions.update({"paradigma-studio": "0.8.0", "paradigma": "1.2.0"})
    record["status"] = status
    history = RunHistory(tmp_path)
    history.save(record)
    loaded, issues = history.load()
    assert not issues and loaded == [record]
    assert run_provenance(loaded[0])["studio_version"] == "0.7.0"


@pytest.mark.parametrize("value", [{"source_commit": "b" * 40}, {}, [], {"source_commit": 12}])
def test_frozen_app_uses_only_its_bundled_build_manifest(tmp_path, monkeypatch, value):
    monkeypatch.setattr(provenance.sys, "frozen", True, raising=False)
    monkeypatch.setattr(provenance.sys, "executable", str(tmp_path / "Studio.exe"))
    (tmp_path / "security").mkdir()
    (tmp_path / "security" / "build-info.json").write_text(json.dumps(value))
    monkeypatch.setattr(provenance.subprocess, "run", lambda *a, **kw: pytest.fail("used Git"))
    expected = "b" * 40 if value == {"source_commit": "b" * 40} else None
    assert provenance._build_commit() == expected


@pytest.mark.parametrize("content", [None, "not JSON"])
def test_frozen_app_can_run_without_optional_commit_metadata(tmp_path, monkeypatch, content):
    monkeypatch.setattr(provenance.sys, "frozen", True, raising=False)
    monkeypatch.setattr(provenance.sys, "executable", str(tmp_path / "Studio.exe"))
    if content is not None:
        (tmp_path / "security").mkdir()
        (tmp_path / "security" / "build-info.json").write_text(content)
    assert provenance._build_commit() is None


def test_source_commit_is_read_from_the_app_checkout_not_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance.sys, "frozen", False, raising=False)
    monkeypatch.chdir(tmp_path)
    calls = []

    def git(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="c" * 40 + "\n")

    monkeypatch.setattr(provenance.subprocess, "run", git)
    assert provenance._build_commit() == "c" * 40
    assert calls[0][0] == ["git", "rev-parse", "HEAD"]
    assert (calls[0][1]["cwd"] / ".git").exists()
    assert calls[0][1]["cwd"] != tmp_path


def test_optional_commit_is_omitted_when_git_is_unavailable(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 2)

    monkeypatch.setattr(provenance.sys, "frozen", False, raising=False)
    monkeypatch.setattr(provenance.subprocess, "run", fail)
    assert "studio_build_commit" not in provenance.software_versions()


def test_saved_results_and_all_export_formats_keep_original_software(tmp_path, monkeypatch):
    record = make_run()
    record.update(studio_version="0.7.0", paradigma_version="1.1.2", studio_build_commit="a" * 40)
    results = {"quantifications": {"tremor": pd.DataFrame({"time": [0.0], "metric": [2.0]})}}
    history = RunHistory(tmp_path / "runs")
    outputs = history.save_results(record, results, run_provenance(record))
    origin, reopened = load_result_export(outputs[0]["path"])
    monkeypatch.setattr(provenance, "version", lambda _: pytest.fail("resolved current version"))
    names = ["quantifications/tremor"]
    export_selection(tmp_path / "results.json", reopened, origin, names, "JSON")
    export_selection(tmp_path / "results.csv", reopened, origin, names, "CSV")
    reopened["metadata"] = {"tremor": {"test": True}}
    export_selection(tmp_path / "results.zip", reopened, origin, [*names, "metadata/tremor"], "CSV")
    json_origin, _ = load_result_export(tmp_path / "results.json")
    csv_origin = json.loads(csv_metadata_path(tmp_path / "results.csv").read_text())["analysis"]
    with ZipFile(tmp_path / "results.zip") as archive:
        zip_origin = json.loads(archive.read("analysis.json"))
    assert json_origin == csv_origin == zip_origin == origin
    assert origin["studio_version"] == "0.7.0" and origin["studio_build_commit"] == "a" * 40


@pytest.mark.parametrize("key", ["studio_version", "paradigma_version", "studio_build_commit"])
def test_software_conflicts_cannot_silently_relabel_a_run(key):
    record = make_run()
    with pytest.raises(ValueError, match=key):
        provenance_for_record({"run_id": record["id"], key: "different"}, record)


def test_csv_companion_identifies_the_exact_table_bytes(tmp_path):
    path = tmp_path / "results.csv"
    origin = run_provenance(make_run())
    frame = pd.DataFrame({"text": ["µ", "=2+2"], "value": [-1.25, 2.0]})
    export_table_csv(path, frame, provenance=origin)
    metadata = json.loads(csv_metadata_path(path).read_text(encoding="utf-8"))
    assert metadata["analysis"] == origin
    assert metadata["csv"] == {
        "file": "results.csv",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    assert pd.read_csv(path)["text"].tolist() == ["µ", "'=2+2"]


@pytest.mark.parametrize("write_stage", ["CSV", "metadata"])
def test_csv_pair_encoding_failure_preserves_both_destinations(tmp_path, monkeypatch, write_stage):
    from paradigma_studio import serialization

    path = tmp_path / "results.csv"
    companion = csv_metadata_path(path)
    path.write_bytes(b"previous table")
    companion.write_bytes(b"previous metadata")

    def fail(*args, **kwargs):
        raise OSError("export write failed")

    if write_stage == "CSV":
        monkeypatch.setattr(pd.DataFrame, "to_csv", fail)
    else:
        monkeypatch.setattr(serialization, "_write_json", fail)
    with pytest.raises(OSError, match="export write failed"):
        export_table_csv(path, pd.DataFrame({"value": [1]}), provenance={})
    assert path.read_bytes() == b"previous table"
    assert companion.read_bytes() == b"previous metadata"
    assert set(tmp_path.iterdir()) == {path, companion}


def test_csv_companion_cannot_overwrite_a_source_recording(tmp_path):
    path = tmp_path / "results.csv"
    source = csv_metadata_path(path)
    source.write_bytes(b"original samples")
    with pytest.raises(ValueError, match="cannot overwrite"):
        export_table_csv(path, pd.DataFrame({"value": [1]}), provenance={"source": str(source)})
    assert source.read_bytes() == b"original samples" and not path.exists()


def test_csv_companion_follows_run_deletion_and_shared_file_protection(tmp_path):
    path = tmp_path / "results.csv"
    metadata = csv_metadata_path(path)
    path.touch()
    metadata.touch()
    first, second = make_run(), make_run()
    output = {"kind": "CSV", "path": str(path), "metadata_path": str(metadata)}
    first["outputs"] = [output]
    second["outputs"] = [output.copy()]
    history = RunHistory(tmp_path / "runs")
    assert history.removal_files(first, [first, second]) == []
    assert set(history.removal_files(first, [first, second], removing=[second])) == {path, metadata}
    assert history.removal_files(first, [first], protected_sources=[metadata]) == [path]


def test_history_rejects_a_companion_path_that_is_not_attached_to_its_csv(tmp_path):
    record = make_run()
    record["outputs"] = [
        {
            "kind": "CSV",
            "path": str(tmp_path / "table.csv"),
            "metadata_path": str(tmp_path / "unrelated.json"),
            "saved": record["started"],
            "complete": False,
        }
    ]
    history = RunHistory(tmp_path / "runs")
    history.save(record)
    runs, issues = history.load()
    assert not runs and len(issues) == 1 and "Invalid CSV metadata companion" in issues[0]
