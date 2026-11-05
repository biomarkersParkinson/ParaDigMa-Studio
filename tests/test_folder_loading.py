"""Recursive recording discovery and responsive, trusted batch loading."""

import shutil
import threading
import time
from pathlib import Path

import pandas as pd
import pytest
from conftest import wait_for_job, wait_for_previews
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from paradigma_studio import app as desktop, core, recordings
from paradigma_studio.recordings import find_recording_files, find_sensor_files
from paradigma_studio.ui.recording_browser import RecordingBrowser


def samples():
    return pd.DataFrame(
        {
            "time": [0.0, 0.01, 0.02],
            **{f"gyroscope_{axis}": [1.0, 2.0, 3.0] for axis in "xyz"},
        }
    )


def test_discovery_recurses_sorts_and_selects_only_recording_inputs(tmp_path):
    names = [
        "z.CWA",
        "a.csv",
        "b/recording.PARQUET",
        "b/optical.avro",
        "b/IMU_meta.json",
        "b/data.pkl",
        "b/nested/data.pickle",
    ]
    ignored = [
        "results.json",
        "table.csv.metadata.json",
        "b/build-info.json",
        "b/IMU_time.bin",
        "b/IMU_values.bin",
        "b/readme.txt",
        "b/nested/archive.zip",
    ]
    for name in [*names, *ignored]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"placeholder")
    expected = sorted(names, key=lambda name: (name.casefold(), name))
    assert [
        path.relative_to(tmp_path).as_posix() for path in find_sensor_files(tmp_path)
    ] == expected


def test_discovery_does_not_follow_directory_links_or_repeat_file_aliases(tmp_path):
    source = tmp_path / "a.csv"
    source.touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    try:
        (nested / "loop").symlink_to(tmp_path, target_is_directory=True)
        (tmp_path / "alias.csv").symlink_to(source)
    except OSError:
        pytest.skip("Creating symbolic links is unavailable on this platform.")
    assert find_sensor_files(tmp_path) == [source]


@pytest.mark.parametrize("contents", [None, "empty", "results.json"])
def test_discovery_reports_missing_or_empty_recording_folders(tmp_path, contents):
    folder = tmp_path / "input"
    if contents is not None:
        folder.mkdir()
    if contents == "results.json":
        (folder / contents).write_text("{}")
    with pytest.raises(ValueError, match="folder"):
        find_sensor_files(folder)


def test_discovery_reports_unreadable_subfolders_instead_of_loading_a_partial_tree(
    tmp_path, monkeypatch
):
    def unreadable(root, *, onerror, followlinks):
        assert root == tmp_path and not followlinks
        onerror(PermissionError("Cannot read the nested recording folder"))
        return iter(())

    monkeypatch.setattr(recordings.os, "walk", unreadable)
    with pytest.raises(PermissionError, match="nested recording folder"):
        find_sensor_files(tmp_path)


def test_folder_scan_runs_off_thread_and_loads_nested_csv_parquet_and_real_tsdf(
    window, tmp_path, tsdf_writer, monkeypatch, recording_picker
):
    root = tmp_path / "input"
    nested = root / "nested"
    nested.mkdir(parents=True)
    frame = samples()
    frame.to_csv(root / "a.csv", index=False)
    frame.to_parquet(nested / "b.parquet", index=False)
    metadata = tsdf_writer(frame, scale_factors=[2.0, 3.0, 4.0])
    for source in (metadata, *tmp_path.glob("IMU_*.bin")):
        shutil.move(source, nested / source.name)
    (root / "results.json").write_text("{}")
    original = frame.copy(deep=True)
    window.loaded(("previous.csv", original))
    wait_for_previews(window)
    window.side.setCurrentText("right")
    recording_picker([root])
    scan = desktop.find_recording_files
    entered, release = threading.Event(), threading.Event()
    gui_thread, deliveries, beats = threading.get_ident(), [], []

    def slow_scan(folder, *, logger):
        assert threading.get_ident() != gui_thread
        entered.set()
        assert release.wait(10)
        return scan(folder, logger=logger)

    monkeypatch.setattr(desktop, "find_recording_files", slow_scan)
    load = desktop.load_recordings

    def observed_load(paths, **kwargs):
        assert threading.get_ident() != gui_thread
        deliveries.extend(paths)
        return load(paths, **kwargs)

    monkeypatch.setattr(desktop, "load_recordings", observed_load)
    timer = QTimer(window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: beats.append(True))
    try:
        window.open_button.click()
        monkeypatch.setattr(
            RecordingBrowser, "choose", lambda *args: pytest.fail("A busy job opened a browser")
        )
        timer.start()
        deadline = time.monotonic() + 5
        while not (entered.is_set() and len(beats) >= 2) and time.monotonic() < deadline:
            QTest.qWait(10)
            time.sleep(0.01)
        assert entered.is_set() and len(beats) >= 2
        assert not window.open_button.isEnabled()
        assert window._input_state.frame is original and not deliveries
        window._layout.open_action.trigger()
        release.set()
        wait_for_job(window)
        wait_for_previews(window)
        assert deliveries == [root / "a.csv", nested / "b.parquet", nested / "IMU_meta.json"]
        assert list(window._input_state.recordings) == [
            "recording_001",
            "recording_002",
            "recording_003",
        ]
        assert window.input_recording.count() == 3 and window.side.currentText() == "left"
        for key in ("recording_001", "recording_002"):
            pd.testing.assert_frame_equal(window._input_state.recordings[key], frame)
        expected = frame.multiply([1, 2, 3, 4], axis="columns")
        pd.testing.assert_frame_equal(window._input_state.recordings["recording_003"], expected)
        assert window.open_button.isEnabled()
        pd.testing.assert_frame_equal(pd.read_csv(root / "a.csv"), frame)
    finally:
        timer.stop()
        release.set()


@pytest.mark.parametrize("accepted", [False, True])
def test_discovered_pickles_require_gui_confirmation_before_any_file_is_loaded(
    window, tmp_path, monkeypatch, recording_picker, accepted
):
    root = tmp_path / "input"
    root.mkdir()
    frame = samples()
    frame.to_csv(root / "a.csv", index=False)
    frame.to_pickle(root / "b.pkl")
    window.loaded(("previous.csv", frame))
    window.side.setCurrentText("right")
    recording_picker([root])
    gui_thread, confirmations, reads = threading.get_ident(), [], []

    def confirm(parent, title, message, buttons, default):
        assert threading.get_ident() == gui_thread
        assert window._job_state.worker is None
        assert window.open_button.isEnabled()
        assert default == QMessageBox.No and buttons == QMessageBox.Yes | QMessageBox.No
        assert not reads
        confirmations.append(message)
        return QMessageBox.Yes if accepted else QMessageBox.No

    monkeypatch.setattr(QMessageBox, "warning", confirm)
    loader = core.load_sensor_file

    def observed_load(path, *, allow_pickle):
        assert accepted and confirmations and allow_pickle
        reads.append(Path(path))
        return loader(path, allow_pickle=allow_pickle)

    monkeypatch.setattr(recordings, "load_sensor_file", observed_load)
    window._layout.open_action.trigger()
    wait_for_job(window)
    assert len(confirmations) == 1
    assert reads == ([root / "a.csv", root / "b.pkl"] if accepted else [])
    assert window.side.currentText() == ("left" if accepted else "right")
    if not accepted:
        assert window._input_state.frame is frame and not window._input_state.recordings
        assert window.status.text() == "Loading cancelled."


@pytest.mark.parametrize("case", ["cancel", "empty", "invalid-recording"])
def test_cancelled_or_failed_folder_load_keeps_the_previous_input_and_settings(
    window, tmp_path, recording_picker, case
):
    root = tmp_path / "input"
    root.mkdir()
    frame = samples()
    window.loaded(("previous.csv", frame))
    window.side.setCurrentText("right")
    before = window._analysis_controller._analysis_settings(["gait"])
    if case == "invalid-recording":
        frame.to_csv(root / "a.csv", index=False)
        (root / "z.csv").write_text("time,gyroscope_x\n")
    recording_picker([] if case == "cancel" else [root])
    window.open_button.click()
    wait_for_job(window)
    assert window._input_state.frame is frame and window._input_state.source == "previous.csv"
    assert window._analysis_controller._analysis_settings(["gait"]) == before
    assert window.open_button.isEnabled()
    if case != "cancel":
        assert window.status.text() == "Operation failed. See the processing log."


@pytest.mark.parametrize("style,font_size", [("Fusion", 13), ("Windows", 18)])
def test_recording_button_remains_visible_at_compact_native_sizes(window, style, font_size):
    app = QApplication.instance()
    original_style = app.style().objectName()
    app.setStyle(style)
    try:
        window.setStyleSheet(window.styleSheet() + f"\nQWidget {{ font-size: {font_size}px; }}")
        window.resize(960, 650)
        window.show()
        for batch in (False, True):
            if batch:
                frames = {f"recording_{index:03d}": samples() for index in (1, 2)}
                sources = {key: f"{key}.csv" for key in frames}
                descriptions = {
                    key: desktop.inspect_recording(frame, "relative_s")
                    for key, frame in frames.items()
                }
                window.loaded_recordings((sources, frames, descriptions))
            app.processEvents()
            assert (
                window.open_button.visibleRegion()
                .boundingRect()
                .contains(window.open_button.rect())
            )
            assert window.size().toTuple() == (960, 650)
    finally:
        app.setStyle(original_style)


def test_mixed_selections_expand_multiple_folders_once_and_ignore_empty_ones(tmp_path):
    first, second, empty = [tmp_path / name for name in ("a", "b", "empty")]
    nested = first / "nested"
    for folder in (first, second, empty, nested):
        folder.mkdir(exist_ok=True)
    paths = [
        first / "one.csv",
        nested / "two.CWA",
        second / "three.parquet",
        tmp_path / "four.avro",
    ]
    for path in paths:
        path.touch()
    assert find_recording_files([second, first, nested, empty, *paths, first]) == sorted(paths)


def test_failed_discovery_does_not_return_a_partial_mixed_selection(tmp_path):
    good = tmp_path / "good.csv"
    good.touch()
    with pytest.raises(ValueError, match="unavailable"):
        find_recording_files([good, tmp_path / "missing"])
