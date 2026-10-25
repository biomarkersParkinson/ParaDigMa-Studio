"""Multiple same-subject recordings, pooled outputs and source-safe exploration."""

import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_previews
from matplotlib import dates
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from run_fixtures import make_run

from paradigma_studio import app as desktop, core
from paradigma_studio.app import MainWindow
from paradigma_studio.history import load_result_export
from paradigma_studio.inspection import inspect_recording, time_descriptives
from paradigma_studio.recordings import align_recordings, load_recordings


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
    while window._job_state.worker is not None and time.monotonic() < deadline:
        QApplication.instance().processEvents()
        time.sleep(0.01)  # Let Python loader/import work run in the Qt worker.
    assert window._job_state.worker is None, "Background load/analysis did not finish"


def inputs(tmp_path, *, clocks=True):
    frames, sources = {}, {}
    for index in (1, 2):
        key = f"recording_{index:03d}"
        frame = pd.DataFrame(
            {
                "time": [0.0, 1.0, 2.0],
                **{
                    f"gyroscope_{axis}": [index * 10.0, index * 10.0 + 1, index * 10.0 + 2]
                    for axis in "xyz"
                },
            }
        )
        if clocks:
            frame["time_dt"] = pd.Timestamp(
                f"2026-10-0{6 + index}T13:00:00+02:00"
            ) + pd.to_timedelta(frame.time, unit="s")
            frame.attrs["desktop_recording_start"] = frame.time_dt.iloc[0].isoformat()
        frames[key], sources[key] = frame, str(tmp_path / f"sensor-{index}.parquet")
    return sources, frames


def output():
    frame = pd.DataFrame(
        {
            "time": [0.0, 1.0, 0.0, 1.0],
            "power": [1.0, 2.0, 3.0, 4.0],
            "pred_event": [1.0, 0.0, 1.0, 0.0],
            "file_key": ["recording_001"] * 2 + ["recording_002"] * 2,
        }
    )
    return {
        "quantifications": {"tremor": frame},
        "aggregations": {"tremor": {"median": 2.5}},
        "metadata": {
            "desktop_recordings": {
                "recordings": ["recording_001", "recording_002"],
                "sections": {key: key for key in ("recording_001", "recording_002")},
            }
        },
        "errors": [],
    }


def load(window, sources, frames):
    window.loaded_recordings(
        (
            sources,
            frames,
            {key: inspect_recording(frame, "relative_s") for key, frame in frames.items()},
        )
    )
    wait_for_previews(window)
    window._result_state.provenance = {
        "source": next(iter(sources.values())),
        "sources": sources,
        "settings": {"pipelines": ["tremor"], "skip_preparation": True},
    }


def test_multiple_file_dialog_loads_inspects_and_runs_all_selected_recordings(
    window, tmp_path, monkeypatch
):
    sources, frames = inputs(tmp_path)
    for key, path in sources.items():
        frames[key].to_parquet(path)
        frames[key] = pd.read_parquet(path)  # Parquet restores an equivalent fixed-offset tz type.
    monkeypatch.setattr(
        desktop.QFileDialog, "getOpenFileNames", lambda *args: (list(sources.values()), "")
    )
    window.open_file()
    wait_for_worker(window)
    assert window.input_recording.count() == 2 and not window.input_recording.isHidden()
    assert len(window._input_state.recordings) == 2
    window.input_recording.setCurrentIndex(1)
    pd.testing.assert_frame_equal(window.input_table.model().frame, frames["recording_002"])
    assert "2 recordings" in window.analysis_input.text()
    assert "6 samples" in window.analysis_input_detail.text()
    captured = []

    def analyze(recordings, **settings):
        captured.append((deepcopy(recordings), settings))
        return output()

    monkeypatch.setattr(desktop, "analyze", analyze)
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: desktop.analyze(frame, logger=logger, **settings),
    )
    window.set_modules(["tremor"])
    window.run_analysis()
    assert not window.input_recording.isEnabled()
    wait_for_worker(window)
    assert captured[0][0].keys() == frames.keys()
    for key in frames:
        pd.testing.assert_frame_equal(captured[0][0][key], frames[key])
    assert window._run_state.runs[0]["sources"] == sources
    assert window.run_table.model().frame.Input.iloc[0] == "2 recordings"
    assert [
        window.run_detail_tabs.tabText(index) for index in range(window.run_detail_tabs.count())
    ] == [
        "Recordings",
        "Parameters",
        "Warnings",
        "Errors",
        "Processing log",
        "Saved run",
        "Exports",
    ]
    assert window.run_recordings.toPlainText().splitlines() == list(sources.values())
    assert all(path not in window.run_summary.text() for path in sources.values())
    saved, issues = window.history.load()
    assert not issues and saved[0]["sources"] == sources


@pytest.mark.parametrize("count", [1, 2], ids=["single", "multiple-recordings"])
def test_open_recordings_resets_shared_time_after_initial_descriptives(
    window, tmp_path, monkeypatch, count
):
    frame = pd.DataFrame({"time": [0, 10, 20, 10], "gyroscope_x": [1.0, 2.0, 3.0, 4.0]})
    paths = [tmp_path / f"sensor-{index}.csv" for index in range(count)]
    for path in paths:
        frame.to_csv(path, index=False)
    monkeypatch.setattr(
        desktop.QFileDialog, "getOpenFileNames", lambda *args: ([str(path) for path in paths], "")
    )
    window.data_time_unit.setCurrentText("difference_ms")
    window.open_file()
    wait_for_worker(window)
    wait_for_previews(window)
    assert window.data_time_unit.currentText() == "relative_s"
    assert window.time.currentText() == "relative_s"
    assert set(window._input_state.sources.values()) == {str(path) for path in paths}
    pd.testing.assert_frame_equal(
        window.time_table.model().frame, time_descriptives(frame.time, "relative_s")
    )
    for description in window._data_state._input_descriptions.values():
        assert description["time_unit"] == "difference_ms"
        pd.testing.assert_frame_equal(
            description["time"], time_descriptives(frame.time, "difference_ms")
        )
    window.set_input_channels(["gyroscope_x"])
    window.data_tabs.setCurrentIndex(1)
    np.testing.assert_allclose(
        window.data_figure.axes[0].lines[0].get_xdata(), frame.time.to_numpy()
    )
    for path in paths:
        pd.testing.assert_frame_equal(pd.read_csv(path), frame, check_exact=True)


def test_inspection_switch_reuses_descriptions_and_preserves_batch_clock_view_and_channels(
    window, tmp_path, monkeypatch
):
    sources, frames = inputs(tmp_path)
    original = deepcopy(frames)
    load(window, sources, frames)
    clock = window.clock_input.text()
    window.set_input_channels(["gyroscope_y", "gyroscope_z"])
    plots = []
    plot = window.plot_input
    monkeypatch.setattr(
        window, "plot_input", lambda *args: (plots.append(window._input_state.source), plot(*args))
    )

    def unexpected(*args, **kwargs):
        pytest.fail(
            "Inspecting an already loaded recording must not recompute batch alignment or descriptives."
        )

    for name in ("align_recordings", "analysis_alignment", "inspect_recording"):
        monkeypatch.setattr(desktop, name, unexpected)
    window.input_recording.setCurrentIndex(1)
    assert plots == [] and window.data_tabs.currentIndex() == 0
    assert window.clock_input.text() == clock
    assert window.selected_input_channels() == ["gyroscope_y", "gyroscope_z"]
    pd.testing.assert_frame_equal(window.input_table.model().frame, frames["recording_002"])
    window.data_tabs.setCurrentIndex(1)
    assert plots == [sources["recording_002"]]
    window.input_recording.setCurrentIndex(0)
    assert window.data_tabs.currentIndex() == 1 and len(plots) == 2
    for line in window.data_figure.axes[0].lines:
        np.testing.assert_array_equal(line.get_ydata(), frames["recording_001"][line.get_label()])
    assert window._input_state.recordings is frames and window.clock_input.text() == clock
    for key in frames:
        pd.testing.assert_frame_equal(frames[key], original[key])


def test_batch_clock_aligns_sensor_context_and_survives_json_reopening(
    window, tmp_path, monkeypatch
):
    sources, frames = inputs(tmp_path)
    load(window, sources, frames)
    results = output()
    original = deepcopy(results)
    window.analyzed(results)
    record = make_run(
        next(iter(sources.values())), window._analysis_controller._analysis_settings(["tremor"])
    )
    window._run_state.current_run = record
    name = "quantifications/tremor"
    np.testing.assert_array_equal(
        window._result_state._timings[name]["Timeline time (s)"], [0.0, 1.0, 86400.0, 86401.0]
    )
    assert window._result_state.display_clock["origin"] == "2026-10-07T13:00:00+02:00"
    pd.testing.assert_frame_equal(
        window.result_table.model().frame, results["quantifications"]["tremor"]
    )
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for key, item in window._result_state._series_items.items():
        item.setCheckState(0, Qt.Checked if key == (name, "pred_event") else Qt.Unchecked)
    window.result_series.blockSignals(False)
    window.plot()
    axis = window.figure.axes[0]
    anchor = dates.date2num(pd.Timestamp("2026-10-08T13:00:00+02:00"))
    np.testing.assert_allclose(axis.collections[0].get_paths()[-1].vertices[:, 0].min(), anchor)
    window.graph_clicked(SimpleNamespace(inaxes=axis, xdata=anchor + 0.5 / 86400))
    assert (
        window._result_state.active_frame.file_key.iloc[window.result_table.currentIndex().row()]
        == "recording_002"
    )
    window.inspect_sensor_context()
    window.sensor_tabs.setCurrentIndex(1)
    pd.testing.assert_frame_equal(window.sensor_table.model().frame, frames["recording_002"])
    assert window._sensor_state._sensor_context.source_name == Path(sources["recording_002"]).name
    np.testing.assert_array_equal(window._sensor_state.sensor_times, [86400.0, 86401.0, 86402.0])
    path = tmp_path / "combined.json"
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.export()
    provenance, restored = load_result_export(path)
    assert provenance["sources"] == sources
    pd.testing.assert_frame_equal(
        restored["quantifications"]["tremor"], original["quantifications"]["tremor"]
    )
    window._run_state.runs = [record]
    window.restore_run((record["id"], provenance, restored))
    assert window._result_state.result_source_frame is None
    np.testing.assert_array_equal(
        window._result_state._timings[name]["Timeline time (s)"], [0.0, 1.0, 86400.0, 86401.0]
    )
    assert window._result_state.display_clock["origin"] == provenance["display_clock"]["origin"]


@pytest.mark.parametrize("clocks", [False, "mixed", "incompatible"])
def test_unknown_or_incomparable_clocks_use_explicit_file_order_without_fabricated_dates(
    tmp_path, clocks
):
    _, frames = inputs(tmp_path, clocks=bool(clocks))
    if clocks == "mixed":
        frames["recording_002"] = frames["recording_002"].drop(columns="time_dt")
        frames["recording_002"].attrs.pop("desktop_recording_start")
    elif clocks == "incompatible":
        frames["recording_002"]["time_dt"] = frames["recording_002"].time_dt.dt.tz_localize(None)
        frames["recording_002"].attrs["desktop_recording_start"] = (
            frames["recording_002"].time_dt.iloc[0].isoformat()
        )
    common, modules, offsets, clock, bases = align_recordings(
        frames, {"pipelines": ["tremor"], "skip_preparation": True}, output()
    )
    assert clock is None and bases == {"recording_001": 0.0, "recording_002": 3.0}
    assert offsets["tremor"] == bases
    np.testing.assert_array_equal(common["recording_002"], [0.0, 1.0, 2.0])


def test_export_protects_every_loaded_source_even_when_another_file_is_selected(
    window, tmp_path, monkeypatch
):
    sources, frames = inputs(tmp_path)
    for key, path in sources.items():
        frames[key].to_parquet(path)
    load(window, sources, frames)
    window.input_recording.setCurrentIndex(1)
    window.analyzed(output())
    window._run_state.current_run = make_run(
        next(iter(sources.values())), window._analysis_controller._analysis_settings(["tremor"])
    )
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
        frames[key].attrs["desktop_recording_start"] = start
    _, _, offsets, clock, _ = align_recordings(
        frames, {"pipelines": ["tremor"], "skip_preparation": True}, output()
    )
    assert clock["timezone"] == "Europe/Amsterdam"
    assert offsets["tremor"]["recording_002"] == 25 * 3600


def test_each_file_prepares_and_splits_independently_with_unique_section_keys(
    tmp_path, monkeypatch
):
    time = np.arange(8, dtype=float) * 10
    frame = pd.DataFrame({"time": time, **{f"gyroscope_{axis}": np.ones(8) for axis in "xyz"}})
    frame.loc[3, "gyroscope_x"] = np.nan
    frames = {"first": frame.copy(), "second": frame.copy()}
    captured = []

    def run(**settings):
        captured.append(settings["dfs"])
        return {"errors": [], "quantifications": {}, "metadata": {}}

    monkeypatch.setattr(core, "run_paradigma", run)
    results = core.analyze(
        frames, pipelines=["tremor"], time_input_unit="relative_ms", drop_missing_samples=True
    )
    assert list(captured[0]) == [
        "first__segment_1",
        "first__segment_2",
        "second__segment_1",
        "second__segment_2",
    ]
    for key, prepared in captured[0].items():
        expected = [0.0, 0.01, 0.02] if key.endswith("segment_1") else [0.04, 0.05, 0.06, 0.07]
        np.testing.assert_array_equal(prepared.time, expected)
    assert results["metadata"]["desktop_preparation"]["excluded_samples"] == 2
    assert results["metadata"]["desktop_recordings"]["sections"]["second__segment_2"] == "second"
    bad = frame.drop(columns="gyroscope_z")
    with pytest.raises(ValueError, match="second: Missing sensor columns"):
        core.analyze(
            {"first": frame, "second": bad}, pipelines=["tremor"], drop_missing_samples=True
        )
    with pytest.raises(ValueError, match="safe identifiers"):
        core.analyze({"../escape": frame}, pipelines=["tremor"])


def test_loader_deduplicates_paths_and_identifies_failed_files(tmp_path):
    source = tmp_path / "sample.csv"
    pd.DataFrame({"time": [0.0, 1.0], "green": [1.0, 2.0]}).to_csv(source, index=False)
    sources, frames = load_recordings([source, source])
    assert list(sources) == ["recording_001"] and len(frames) == 1
    with pytest.raises(ValueError, match="missing.csv"):
        load_recordings([source, tmp_path / "missing.csv"])


def test_collection_keeps_source_identifiers_even_for_one_recording(monkeypatch):
    frame = pd.DataFrame(
        {"time": np.arange(10) / 10, **{f"gyroscope_{axis}": np.ones(10) for axis in "xyz"}}
    )

    def run(**settings):
        assert list(settings["dfs"]) == ["only"]
        return {
            "quantifications": {"tremor": pd.DataFrame({"time": [0.0], "power": [2.0]})},
            "metadata": {},
            "errors": [],
        }

    monkeypatch.setattr(core, "run_paradigma", run)
    result = core.analyze({"only": frame}, pipelines=["tremor"])
    assert result["quantifications"]["tremor"].file_key.tolist() == ["only"]
