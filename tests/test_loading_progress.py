"""Loading milestones keep atomic imports, exact statistics and responsive quiet UI."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_job, wait_for_previews
from gui_helpers import wait_until
from PySide6.QtCore import QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paradigma_studio import app as desktop, inspection, recordings
from paradigma_studio.inspection import inspect_recording, inspect_recordings
from paradigma_studio.recordings import load_recordings


def samples(rows=100):
    return pd.DataFrame({"time": np.arange(rows) / 100, "gyroscope_x": np.arange(rows) / 10})


@pytest.mark.parametrize("count", [1, 3])
def test_read_progress_counts_completed_unique_files_and_preserves_data(tmp_path, count):
    frame = samples()
    paths = [tmp_path / f"{index}.csv" for index in range(count)]
    for path in paths:
        frame.to_csv(path, index=False)
    progress = []
    sources, frames = load_recordings([*paths, paths[0]], progress=progress.append)
    assert progress == ([1000] if count == 1 else [0, 333, 666, 1000])
    assert list(sources.values()) == list(map(str, paths))
    for restored in frames.values():
        pd.testing.assert_frame_equal(restored, pd.read_csv(paths[0]), check_exact=True)


def test_failed_read_never_reports_complete(tmp_path):
    path = tmp_path / "valid.csv"
    samples().to_csv(path, index=False)
    progress = []
    with pytest.raises(ValueError, match="missing.csv"):
        load_recordings([path, tmp_path / "missing.csv"], progress=progress.append)
    assert progress == [0, 500]


def test_parallel_statistics_report_completed_work_while_first_recording_is_blocked(monkeypatch):
    frames = {"large": samples(1000), "small": samples(100)}
    monkeypatch.setattr(inspection, "inspection_worker_count", lambda _: 2)
    release, entered, small_finished = Event(), Event(), Event()
    progress = []

    def describe(frame, unit, *, progress=None):
        if len(frame) == 1000:
            entered.set()
            assert release.wait(5)
        result = inspect_recording(frame, unit, progress=progress)
        if len(frame) == 100:
            small_finished.set()
        return result

    with ThreadPoolExecutor(max_workers=1) as caller:
        future = caller.submit(
            inspect_recordings, frames, "relative_s", describe=describe, progress=progress.append
        )
        try:
            assert entered.wait(5) and small_finished.wait(5)
            # The large first input cannot conceal another worker's progress,
            # and the small input must not consume half of the statistics share.
            assert not future.done() and 0 < progress[-1] < 100
        finally:
            release.set()
        actual = future.result(timeout=5)
    assert list(actual) == list(frames)
    assert progress == sorted(set(progress)) and progress[-1] == 1000
    for key, frame in frames.items():
        reference = inspect_recording(frame, "relative_s")
        for name in ("sensors", "time"):
            pd.testing.assert_frame_equal(actual[key][name], reference[name], check_exact=True)


def test_single_recording_reports_between_channels_without_repeating_statistics(monkeypatch):
    frame = samples()
    for index in range(5):
        frame[f"sensor_{index}"] = np.sin(frame.time * (index + 1))
    original = frame.copy(deep=True)
    reference = inspect_recording(frame, "relative_s")
    quantile = np.quantile
    calls, progress = [], []

    def observe(*args, **kwargs):
        calls.append(progress[-1])
        return quantile(*args, **kwargs)

    monkeypatch.setattr(np, "quantile", observe)
    actual = inspect_recording(frame, "relative_s", progress=progress.append)
    assert len(calls) == 7  # Six signal summaries and one time summary.
    assert len(set(calls)) > 2 and max(calls) < 1000
    assert progress == sorted(set(progress)) and progress[-1] == 1000
    for name in ("sensors", "time"):
        pd.testing.assert_frame_equal(actual[name], reference[name], check_exact=True)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


@pytest.fixture
def gated_load(window, tmp_path, monkeypatch, recording_picker, count):
    previous = samples(20)
    window.loaded(("previous.csv", previous))
    wait_for_previews(window)
    paths = [tmp_path / f"{index}.csv" for index in range(count)]
    for index, path in enumerate(paths):
        samples(100 + index).to_csv(path, index=False)
    read_entered = [Event() for _ in paths]
    read_release = [Event() for _ in paths]
    stats_entered, stats_release = Event(), Event()
    reader, describe = recordings.load_sensor_file, desktop.inspect_recording
    beats, changes, installed = [], [], []

    def held_read(path, *, allow_pickle):
        index = paths.index(Path(path))
        read_entered[index].set()
        assert read_release[index].wait(10)
        return reader(path, allow_pickle=allow_pickle)

    def held_description(frame, unit, *, progress=None):
        stats_entered.set()
        assert stats_release.wait(10)
        return describe(frame, unit, progress=progress)

    def changed(value):
        assert QThread.currentThread() is QApplication.instance().thread()
        changes.append(value)
        if value == 1000:
            installed.append(window._input_state.source != "previous.csv")

    monkeypatch.setattr(recordings, "load_sensor_file", held_read)
    monkeypatch.setattr(desktop, "inspect_recording", held_description)
    window.progress.valueChanged.connect(changed)
    timer = QTimer(window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: beats.append(True))
    recording_picker(paths)
    timer.start()
    try:
        yield SimpleNamespace(
            previous=previous,
            read_entered=read_entered,
            read_release=read_release,
            stats_entered=stats_entered,
            stats_release=stats_release,
            beats=beats,
            changes=changes,
            installed=installed,
        )
    finally:
        timer.stop()
        for release in read_release:
            release.set()
        stats_release.set()


@pytest.mark.parametrize("count", [1, 2])
def test_real_load_switches_from_busy_to_measured_and_finishes_after_installation(
    window, gated_load, count
):
    loading = gated_load
    window.open_file()
    wait_until(loading.read_entered[0].is_set, timeout=5000)
    old_worker = window._job_state.worker
    if count == 1:
        assert window.progress.minimum() == window.progress.maximum() == 0
    else:
        wait_until(lambda: window.progress.maximum() == 1000)
        assert window.progress.value() == 0
    wait_until(lambda: len(loading.beats) >= 2)
    assert window._input_state.frame is loading.previous
    assert not window.stop_button.isEnabled()
    geometry = window.progress.geometry()
    assert not window.progress.isTextVisible() and window.progress.height() == 4
    loading.read_release[0].set()
    if count == 2:
        wait_until(loading.read_entered[1].is_set)
        wait_until(lambda: window.progress.value() == 325)
        assert window._input_state.frame is loading.previous
        loading.read_release[1].set()
    wait_until(loading.stats_entered.is_set)
    wait_until(lambda: window.progress.value() == 650)
    assert window.progress.geometry() == geometry
    assert window._input_state.frame is loading.previous and not loading.installed
    assert window.status.text() == "Loading recordings…"
    loading.stats_release.set()
    wait_for_job(window)
    assert loading.installed == [True] and loading.changes[-1] == 1000
    assert loading.changes == sorted(loading.changes)
    assert window.progress.isHidden()
    assert window.open_button.isEnabled() and window._layout.open_folder_button.isEnabled()
    assert window._job_state._analysis_stop is None
    # An update from the completed load cannot activate an unrelated job's bar.
    next_release = Event()
    window.start_job(lambda logger: next_release.wait(5), lambda _: None)
    try:
        window._job_controller.job_progress(old_worker, 950)
        QTest.qWait(230)
        assert window.progress.maximum() == 0
    finally:
        next_release.set()
        wait_for_job(window)


def test_inspection_failure_keeps_previous_input_and_never_fills_the_bar(
    window, tmp_path, monkeypatch, recording_picker
):
    previous = samples(20)
    window.loaded(("previous.csv", previous))
    wait_for_previews(window)
    window.side.setCurrentText("right")
    settings = window._analysis_controller._analysis_settings(["tremor"])
    path = tmp_path / "new.csv"
    samples().to_csv(path, index=False)

    def fail(frame, unit, *, progress=None):
        progress(500)
        raise ValueError("Initial statistics failed")

    monkeypatch.setattr(desktop, "inspect_recording", fail)
    recording_picker([path])
    window.open_file()
    wait_for_job(window)
    assert window._input_state.frame is previous and window._input_state.source == "previous.csv"
    assert window._analysis_controller._analysis_settings(["tremor"]) == settings
    assert window.progress.isHidden() and window.progress.value() < 1000
    assert "Initial statistics failed" in window.notice.text()
