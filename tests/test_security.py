"""Regression checks for unsafe deserialization, exports and diagnostic writes."""
import logging
import json
import os
import pickle
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from paradigma_desktop import core
from scripts.audit_dependencies import is_python_arrow_exception
from scripts import audit_dependencies


class TouchFileOnUnpickle:
    def __init__(self, marker):
        self.marker = marker

    def __reduce__(self):
        return Path.touch, (self.marker,)


@pytest.mark.parametrize("suffix", ["pkl", "PICKLE"])
def test_pickle_payload_cannot_execute_without_explicit_trust(tmp_path, suffix):
    marker = tmp_path / "unpickle-executed"
    path = tmp_path / f"input.{suffix}"
    path.write_bytes(pickle.dumps(TouchFileOnUnpickle(marker)))
    with pytest.raises(ValueError, match="explicitly trusted"):
        core.load_sensor_file(path)
    assert not marker.exists()


def test_csv_formula_text_is_neutralized_without_changing_numbers(tmp_path):
    path = tmp_path / "results.csv"
    original = pd.DataFrame({
        "=malicious_header": ["=1+1", " +1+1", "\t@SUM(1)", "-1+1", "normal"],
        "numeric": [-2.5, 0, 1, 2, 3],
    })
    core.export_table_csv(path, original)
    exported = pd.read_csv(path)
    assert exported.columns[0] == "'=malicious_header"
    assert exported.iloc[:, 0].tolist() == ["'=1+1", "' +1+1", "'\t@SUM(1)", "'-1+1", "normal"]
    assert exported["numeric"].tolist() == original["numeric"].tolist()
    assert original.columns[0] == "=malicious_header"
    assert original.iloc[0, 0] == "=1+1"


@pytest.mark.parametrize("kind", ["json", "csv"])
@pytest.mark.parametrize("alias", [False, True])
def test_exports_cannot_overwrite_recording_or_hardlink(tmp_path, kind, alias):
    source = tmp_path / "sensor.csv"
    source.write_text("original samples", encoding="utf-8")
    target = source
    if alias:
        target = tmp_path / "alias.csv"
        os.link(source, target)
    with pytest.raises(ValueError, match="cannot overwrite"):
        if kind == "json":
            core.export_results(target, {}, {"source": str(source)})
        else:
            core.export_table_csv(target, pd.DataFrame({"time": [1]}), source=source)
    assert source.read_text() == "original samples"


def test_failed_export_preserves_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "results.json"
    target.write_text("previous results", encoding="utf-8")

    def fail_after_partial_write(value, stream, **kwargs):
        stream.write("partial new results")
        raise OSError("simulated disk write failure")

    monkeypatch.setattr(core.json, "dump", fail_after_partial_write)
    with pytest.raises(OSError, match="disk write"):
        core.export_results(target, {}, {})
    assert target.read_text() == "previous results"
    assert list(tmp_path.iterdir()) == [target]


def test_default_diagnostics_are_isolated_and_cleaned_on_failure(monkeypatch):
    directories = []
    handlers = []

    def fail(**kwargs):
        directory = Path(kwargs["output_dir"])
        directories.append(directory)
        assert directory.is_dir()
        handler = logging.FileHandler(directory / "diagnostics.log")
        handlers.append(handler)
        logging.getLogger("paradigma").addHandler(handler)
        raise RuntimeError("simulated pipeline failure")

    monkeypatch.setattr(core, "run_paradigma", fail)
    frame = pd.DataFrame({"time": [0, 1], **{f"gyroscope_{a}": [0, 1] for a in "xyz"}})
    for _ in range(2):
        with pytest.raises(RuntimeError, match="pipeline failure"):
            core.analyze(frame, pipelines=["tremor"])
    assert directories[0] != directories[1]
    assert all(not directory.exists() for directory in directories)
    assert all(handler.stream is None for handler in handlers)
    assert not any(handler in logging.getLogger("paradigma").handlers for handler in handlers)


def test_arrow_advisory_exception_is_limited_to_reviewed_issue_and_package():
    advisory = {"id": "PYSEC-2026-113", "aliases": ["CVE-2026-25087"]}
    assert is_python_arrow_exception("pyarrow", advisory)
    assert not is_python_arrow_exception("another-package", advisory)
    assert not is_python_arrow_exception("pyarrow", {"id": "unreviewed-advisory"})


def test_audit_failure_cannot_reuse_a_previous_success_report(tmp_path, monkeypatch):
    report = tmp_path / "audit.json"
    previous = json.dumps({"dependencies": [{"name": "numpy", "version": "2", "vulns": []}]})
    report.write_text(previous, encoding="utf-8")
    monkeypatch.setattr(audit_dependencies.subprocess, "run",
                        lambda args, **kwargs: subprocess.CompletedProcess(args, 1))
    with pytest.raises(RuntimeError, match="did not complete"):
        audit_dependencies.main(report)
    assert report.read_text() == previous
