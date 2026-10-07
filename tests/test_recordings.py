"""Multiple same-subject recordings, pooled outputs and source-safe exploration."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paradigma_desktop import app as desktop
from paradigma_desktop import core
from paradigma_desktop.app import MainWindow
from paradigma_desktop.history import RunHistory, load_result_export, new_run
from paradigma_desktop.inspection import inspect_recording
from paradigma_desktop.recordings import align_recordings, load_recordings


@pytest.fixture
def window(tmp_path):
    application = QApplication.instance() or QApplication([])
    widget = MainWindow(history_dir=tmp_path / "runs")
    yield widget
    wait_for_worker(widget)
    widget.close()
    application.processEvents()


def wait_for_worker(window):
    deadline = time.monotonic() + 30
    while window.worker is not None and time.monotonic() < deadline:
        QApplication.instance().processEvents()
        time.sleep(.01)  # Let Python loader/import work run in the Qt worker.
    assert window.worker is None, "Background load/analysis did not finish"


def inputs(tmp_path, *, clocks=True):
    frames, sources = {}, {}
    for index in (1, 2):
        key = f"recording_{index:03d}"
        frame = pd.DataFrame({"time": [0., 1., 2.],
                              **{f"gyroscope_{axis}": [index * 10., index * 10. + 1, index * 10. + 2] for axis in "xyz"}})
        if clocks:
            frame["time_dt"] = pd.Timestamp(f"2026-10-0{6 + index}T13:00:00+02:00") + pd.to_timedelta(frame.time, unit="s")
        frames[key], sources[key] = frame, str(tmp_path / f"sensor-{index}.parquet")
    return sources, frames


def output():
    frame = pd.DataFrame({"time": [0., 1., 0., 1.], "power": [1., 2., 3., 4.],
                          "pred_event": [1., 0., 1., 0.],
                          "file_key": ["recording_001"] * 2 + ["recording_002"] * 2})
    return {"quantifications": {"tremor": frame}, "aggregations": {"tremor": {"median": 2.5}},
            "metadata": {"desktop_recordings": {"recordings": ["recording_001", "recording_002"],
                         "sections": {key: key for key in ("recording_001", "recording_002")}}}, "errors": []}


def load(window, sources, frames):
    window.loaded_recordings((sources, frames, {key: inspect_recording(frame, "relative_s") for key, frame in frames.items()}))
    window.provenance = {"source": next(iter(sources.values())), "sources": sources,
                         "settings": {"pipelines": ["tremor"], "skip_preparation": True}}


def test_multiple_file_dialog_loads_inspects_and_runs_all_selected_recordings(window, tmp_path, monkeypatch):
    sources, frames = inputs(tmp_path)
    for key, path in sources.items():
        frames[key].to_parquet(path)
        frames[key] = pd.read_parquet(path)  # Parquet restores an equivalent fixed-offset tz type.
    monkeypatch.setattr(desktop.QFileDialog, "getOpenFileNames", lambda *args: (list(sources.values()), ""))
    window.open_file()
    wait_for_worker(window)
    assert window.input_recording.count() == 2 and not window.input_recording.isHidden()
    assert len(window.recordings) == 2
    window.input_recording.setCurrentIndex(1)
    pd.testing.assert_frame_equal(window.input_table.model().frame, frames["recording_002"])
    assert "2 recordings" in window.analysis_input.text()
    assert "6 samples" in window.analysis_input_detail.text()
    captured = []
    def analyze(recordings, **settings):
        captured.append((deepcopy(recordings), settings))
        return output()
    monkeypatch.setattr(desktop, "analyze", analyze)
    window.set_modules(["tremor"])
    window.prepared.setChecked(True)
    window.run_analysis()
    assert not window.input_recording.isEnabled()
    wait_for_worker(window)
    assert captured[0][0].keys() == frames.keys()
    for key in frames:
        pd.testing.assert_frame_equal(captured[0][0][key], frames[key])
    assert window.runs[0]["sources"] == sources
    assert window.run_table.model().frame.Input.iloc[0] == "2 recordings"
    assert all(path in window.run_summary.text() for path in sources.values())
    saved, issues = window.history.load()
    assert not issues and saved[0]["sources"] == sources


def test_batch_clock_filters_sensor_context_and_json_reopening(window, tmp_path, monkeypatch):
    sources, frames = inputs(tmp_path)
    load(window, sources, frames)
    results = output()
    original = deepcopy(results)
    window.analyzed(results)
    name = "quantifications/tremor"
    np.testing.assert_array_equal(window._timings[name]["Timeline time (s)"], [0., 1., 86400., 86401.])
    assert window.display_clock["origin"] == "2026-10-07T13:00:00+02:00"
    window.time_from.setText("86400")
    window.apply_filters()
    pd.testing.assert_frame_equal(window.result_table.model().frame, results["quantifications"]["tremor"].iloc[2:])
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for key, item in window._series_items.items():
        item.setCheckState(0, Qt.Checked if key == (name, "pred_event") else Qt.Unchecked)
    window.result_series.blockSignals(False)
    window.plot()
    axis = window.figure.axes[0]
    anchor = dates.date2num(pd.Timestamp("2026-10-08T13:00:00+02:00"))
    np.testing.assert_allclose(axis.collections[0].get_paths()[0].vertices[:, 0].min(), anchor)
    window.graph_clicked(SimpleNamespace(inaxes=axis, xdata=anchor + .5 / 86400))
    assert window.active_frame.file_key.iloc[window.result_table.currentIndex().row()] == "recording_002"
    window.inspect_sensor_context()
    pd.testing.assert_frame_equal(window.sensor_table.model().frame, frames["recording_002"])
    assert Path(sources["recording_002"]).name in window.sensor_note.text()
    np.testing.assert_array_equal(window.sensor_times, [86400., 86401., 86402.])
    path = tmp_path / "combined.json"
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.export()
    provenance, restored = load_result_export(path)
    assert provenance["sources"] == sources
    pd.testing.assert_frame_equal(restored["quantifications"]["tremor"], original["quantifications"]["tremor"])
    record = new_run(next(iter(sources.values())), provenance["settings"])
    window.runs = [record]
    window.restore_run((record["id"], provenance, restored))
    assert window.result_source_frame is None
    np.testing.assert_array_equal(window._timings[name]["Timeline time (s)"], [0., 1., 86400., 86401.])
    assert window.display_clock["origin"] == provenance["display_clock"]["origin"]


@pytest.mark.parametrize("clocks", [False, "mixed", "incompatible"])
def test_unknown_or_incomparable_clocks_use_explicit_file_order_without_fabricated_dates(tmp_path, clocks):
    _, frames = inputs(tmp_path, clocks=bool(clocks))
    if clocks == "mixed":
        frames["recording_002"] = frames["recording_002"].drop(columns="time_dt")
    elif clocks == "incompatible":
        frames["recording_002"]["time_dt"] = frames["recording_002"].time_dt.dt.tz_localize(None)
    common, modules, offsets, clock, bases = align_recordings(frames, {"pipelines": ["tremor"], "skip_preparation": True}, output())
    assert clock is None and bases == {"recording_001": 0., "recording_002": 3.}
    assert offsets["tremor"] == bases
    np.testing.assert_array_equal(common["recording_002"], [0., 1., 2.])


def test_export_protects_every_loaded_source_even_when_another_file_is_selected(window, tmp_path, monkeypatch):
    sources, frames = inputs(tmp_path)
    for key, path in sources.items():
        frames[key].to_parquet(path)
    load(window, sources, frames)
    window.input_recording.setCurrentIndex(1)
    window.analyzed(output())
    protected = Path(sources["recording_001"])
    original = protected.read_bytes()
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(protected), ""))
    window.export()
    assert protected.read_bytes() == original
    assert "overwrite" in window.notice.text().lower()


def test_multiple_clocks_preserve_named_timezone_and_actual_dst_spacing(tmp_path):
    _, frames = inputs(tmp_path)
    for key, day in (("recording_001", 24), ("recording_002", 25)):
        start = pd.Timestamp(f"2026-10-{day}T13:00:00", tz="Europe/Amsterdam")
        frames[key]["time_dt"] = start + pd.to_timedelta(frames[key].time, unit="s")
    _, _, offsets, clock, _ = align_recordings(frames, {"pipelines": ["tremor"], "skip_preparation": True}, output())
    assert clock["timezone"] == "Europe/Amsterdam"
    assert offsets["tremor"]["recording_002"] == 25 * 3600


def test_each_file_prepares_and_splits_independently_with_unique_section_keys(tmp_path, monkeypatch):
    time = np.arange(8, dtype=float) * 10
    frame = pd.DataFrame({"time": time, **{f"gyroscope_{axis}": np.ones(8) for axis in "xyz"}})
    frame.loc[3, "gyroscope_x"] = np.nan
    frames = {"first": frame.copy(), "second": frame.copy()}
    captured = []
    def run(**settings):
        captured.append(settings["dfs"])
        return {"errors": [], "quantifications": {}, "metadata": {}}
    monkeypatch.setattr(core, "run_paradigma", run)
    results = core.analyze(frames, pipelines=["tremor"], time_input_unit="relative_ms", drop_missing_samples=True)
    assert list(captured[0]) == ["first__segment_1", "first__segment_2", "second__segment_1", "second__segment_2"]
    for key, prepared in captured[0].items():
        expected = [0., .01, .02] if key.endswith("segment_1") else [.04, .05, .06, .07]
        np.testing.assert_array_equal(prepared.time, expected)
    assert results["metadata"]["desktop_preparation"]["excluded_samples"] == 2
    assert results["metadata"]["desktop_recordings"]["sections"]["second__segment_2"] == "second"
    bad = frame.drop(columns="gyroscope_z")
    with pytest.raises(ValueError, match="second: Missing sensor columns"):
        core.analyze({"first": frame, "second": bad}, pipelines=["tremor"], drop_missing_samples=True)
    with pytest.raises(ValueError, match="safe identifiers"):
        core.analyze({"../escape": frame}, pipelines=["tremor"])


def test_loader_deduplicates_paths_and_identifies_failed_files(tmp_path):
    source = tmp_path / "sample.csv"
    pd.DataFrame({"time": [0., 1.], "green": [1., 2.]}).to_csv(source, index=False)
    sources, frames = load_recordings([source, source])
    assert list(sources) == ["recording_001"] and len(frames) == 1
    with pytest.raises(ValueError, match="missing.csv"):
        load_recordings([source, tmp_path / "missing.csv"])


def test_collection_keeps_source_identifiers_even_for_one_recording(monkeypatch):
    frame = pd.DataFrame({"time": np.arange(10) / 10, **{f"gyroscope_{axis}": np.ones(10) for axis in "xyz"}})
    def run(**settings):
        assert list(settings["dfs"]) == ["only"]
        return {"quantifications": {"tremor": pd.DataFrame({"time": [0.], "power": [2.]})}, "metadata": {}, "errors": []}
    monkeypatch.setattr(core, "run_paradigma", run)
    result = core.analyze({"only": frame}, pipelines=["tremor"])
    assert result["quantifications"]["tremor"].file_key.tolist() == ["only"]
