"""Check startup isolation in a fresh interpreter, independent of test imports."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from paradigma_studio import plot_cache
from paradigma_studio.plot_cache import configure_plot_cache


def test_portable_font_cache_is_reused_and_changes_after_relocation(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "app" / "_internal"), raising=False)
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "temporary"))
    first = configure_plot_cache(tmp_path / "cache")
    assert first.is_dir()
    (first / "font-cache.json").write_text("cached fonts")
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "next-temporary"))
    assert configure_plot_cache(tmp_path / "cache") == first
    assert (first / "font-cache.json").read_text() == "cached fonts"
    assert os.environ["MPLCONFIGDIR"] == str(first)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "moved-app" / "_internal"))
    assert configure_plot_cache(tmp_path / "cache") != first
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "app" / "_internal"))
    monkeypatch.setattr(plot_cache, "version", lambda package: "updated-version")
    assert configure_plot_cache(tmp_path / "cache") != first


def test_font_cache_falls_back_when_storage_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "app" / "_internal"), raising=False)
    original = str(tmp_path / "temporary")
    monkeypatch.setenv("MPLCONFIGDIR", original)
    unavailable = tmp_path / "unavailable"
    unavailable.write_text("This is a file, not a cache directory.")
    assert configure_plot_cache(unavailable) is None
    assert os.environ["MPLCONFIGDIR"] == original


def test_source_and_onefile_keep_their_existing_font_configuration(tmp_path, monkeypatch):
    original = str(tmp_path / "custom-cache")
    monkeypatch.setenv("MPLCONFIGDIR", original)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert configure_plot_cache(tmp_path) is None
    monkeypatch.setattr(sys, "frozen", True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI123"), raising=False)
    assert configure_plot_cache(tmp_path) is None
    assert os.environ["MPLCONFIGDIR"] == original


def test_font_cache_falls_back_when_version_metadata_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "app" / "_internal"), raising=False)
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "temporary"))

    def missing_metadata(package):
        raise plot_cache.PackageNotFoundError(package)

    monkeypatch.setattr(plot_cache, "version", missing_metadata)
    assert configure_plot_cache(tmp_path / "cache") is None
    assert os.environ["MPLCONFIGDIR"] == str(tmp_path / "temporary")


def test_first_window_does_not_load_analysis_stack(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report = tmp_path / "startup.json"
    result = subprocess.run(
        [sys.executable, str(root / "desktop.py"), "--startup-test", str(report)],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "MPLCONFIGDIR": str(tmp_path / "mpl")},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, (
        result.stdout
        + result.stderr
        + (report.read_text() if report.exists() else "No startup report")
    )
    data = json.loads(report.read_text())
    assert data["status"] == "passed"
    assert data["analysis_modules_loaded"] == []
    assert data["data_modules_loaded"] == []
    assert data["empty_history"]
    assert data["qt_platform"] == "offscreen"
    assert 0 < data["import_seconds"] <= data["first_paint_seconds"]


def test_empty_graph_views_do_not_import_the_data_or_analysis_stack(tmp_path):
    report = tmp_path / "startup-empty-graphs.json"
    code = """import sys, time
started = time.perf_counter()
from paradigma_studio.startup import startup_test
from paradigma_studio.app import MainWindow
original = MainWindow.show
def show_graphs(self):
    self.navigate(2)
    self.result_tabs.setCurrentIndex(1)
    for index in range(self.result_graph_view.count()):
        self.result_graph_view.setCurrentIndex(index)
        assert not self.context_button.isEnabled()
    original(self)
MainWindow.show = show_graphs
sys.exit(startup_test(sys.argv[1], started))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(report)],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "MPLCONFIGDIR": str(tmp_path / "mpl")},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(report.read_text())
    assert data["status"] == "passed"
    assert data["data_modules_loaded"] == []
    assert data["analysis_modules_loaded"] == []


@pytest.mark.parametrize("run_count", [0, 200])
def test_runs_page_starts_without_tabular_imports_even_with_saved_history(tmp_path, run_count):
    from paradigma_studio.history import new_run

    directory = tmp_path / "runs"
    directory.mkdir()
    for index in range(run_count):
        record = new_run(f"sensor-{index}.csv", {"pipelines": ["tremor"]})
        record["status"] = "Completed"
        (directory / f"{record['id']}.json").write_text(json.dumps(record), encoding="utf-8")
    report = tmp_path / "startup-runs.json"
    code = """import sys, time
started = time.perf_counter()
from paradigma_studio.startup import startup_test
from paradigma_studio.app import MainWindow
original = MainWindow.show
def show_runs(self):
    self.navigate(3)
    original(self)
MainWindow.show = show_runs
sys.exit(startup_test(sys.argv[1], started, history_dir=sys.argv[2]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(report), str(directory)],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "MPLCONFIGDIR": str(tmp_path / "mpl")},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(report.read_text())
    assert data["status"] == "passed"
    assert data["run_history_count"] == run_count
    assert data["data_modules_loaded"] == []
    assert data["analysis_modules_loaded"] == []
