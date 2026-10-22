"""Responsiveness and correctness of background recording previews."""

import time
from threading import Event, get_ident

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_previews
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paradigma_studio import app as desktop, recordings
from paradigma_studio.inspection import inspect_recording, sensor_descriptives, time_descriptives
from paradigma_studio.previews import CachedPreview
from paradigma_studio.results_view import analysis_alignment, recording_clock


def wait_until(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        QApplication.instance().processEvents()
        time.sleep(0.01)
    assert predicate(), "Background preview did not finish"


def test_busy_preview_keeps_event_loop_running_and_only_delivers_latest_request(window):
    preview = CachedPreview(window, delay=5)
    entered, release = Event(), Event()
    executed, received, beats = [], [], []
    gui_thread = get_ident()
    preview.value_ready.connect(lambda value: received.append((value, get_ident())))

    def slow_first():
        executed.append(("first", get_ident()))
        entered.set()
        assert release.wait(10)
        return "first"

    timer = QTimer(window)
    timer.setInterval(10)
    timer.timeout.connect(lambda: beats.append(True))
    timer.start()
    try:
        preview.request("first", slow_first)
        wait_until(entered.is_set)
        count = len(beats)
        QTest.qWait(100)
        assert len(beats) > count  # GUI events run while the calculation is blocked.
        preview.request("superseded", lambda: executed.append(("superseded", get_ident())))
        preview.request("latest", lambda: (executed.append(("latest", get_ident())), "latest")[1])
        release.set()
        wait_until(lambda: not preview.pending)
        assert received == [("latest", gui_thread)]
        assert [key for key, _ in executed] == ["first", "latest"]
        assert all(thread != gui_thread for _, thread in executed)
        preview.request("latest", lambda: pytest.fail("Cached settings must not recalculate"))
        assert received[-1] == ("latest", gui_thread) and not preview.pending
    finally:
        release.set()
        timer.stop()
        preview.shutdown()


def test_loading_new_input_invalidates_cached_and_running_previews(window):
    preview = CachedPreview(window, delay=5)
    entered, release = Event(), Event()
    received = []
    preview.value_ready.connect(received.append)

    def old_input():
        entered.set()
        assert release.wait(10)
        return "old recording"

    try:
        preview.request("same settings", old_input)
        wait_until(entered.is_set)
        preview.clear()
        preview.request("same settings", lambda: "new recording")
        release.set()
        wait_until(lambda: not preview.pending)
        assert received == ["new recording"]
    finally:
        release.set()
        preview.shutdown()


def test_closing_a_window_does_not_wait_for_or_deliver_a_running_preview(window):
    entered, release = Event(), Event()
    received = []
    preview = window._origin_preview
    preview.value_ready.connect(received.append)

    def operation():
        entered.set()
        assert release.wait(10)
        return {"origin": "2026-10-07T00:00:00Z"}

    try:
        preview.request("running", operation)
        wait_until(entered.is_set)
        future = preview._future
        assert window.close()  # Returns while the background scan is still blocked.
        assert not future.done()
        release.set()
        wait_until(future.done)
        QTest.qWait(20)
        assert not received
    finally:
        release.set()
        preview.shutdown()


def test_preview_failure_leaves_controls_usable_and_can_recover(window):
    preview = CachedPreview(window, delay=5)
    failures, values = [], []
    diagnostics = []
    preview.failed.connect(failures.append)
    preview.diagnostic.connect(diagnostics.append)
    preview.value_ready.connect(values.append)

    def invalid():
        raise ValueError("Invalid recording")

    try:
        preview.request("invalid", invalid)
        wait_until(lambda: not preview.pending)
        assert failures == ["ValueError: Invalid recording"] and values == [None]
        assert len(diagnostics) == 1 and "Traceback" in diagnostics[0]
        assert "in invalid" in diagnostics[0] and "ValueError: Invalid recording" in diagnostics[0]
        preview.request("valid", lambda: "Recovered")
        wait_until(lambda: not preview.pending)
        assert values[-1] == "Recovered"
    finally:
        preview.shutdown()


def test_failed_preview_can_retry_the_same_key_without_poisoning_cached_none(window):
    preview = CachedPreview(window, delay=5)
    values, failures = [], []
    preview.value_ready.connect(values.append)
    preview.failed.connect(failures.append)

    def transient_failure():
        raise OSError("Temporary read failure")

    try:
        preview.request("recording", transient_failure)
        wait_until(lambda: not preview.pending)
        assert failures == ["OSError: Temporary read failure"]
        assert not preview.is_requested("recording")
        preview.request("recording", lambda: "Recovered")
        wait_until(lambda: not preview.pending)
        assert values == [None, "Recovered"]
        # None is still a valid successful preview, for example no date origin.
        preview.request("no clock", lambda: None)
        wait_until(lambda: not preview.pending)
        preview.cancel_pending()
        preview.request("no clock", lambda: pytest.fail("Successful None must be cached"))
        assert values[-1] is None and not preview.pending
    finally:
        preview.shutdown()


def test_analyze_options_reuse_clock_and_match_current_alignment_without_mutating_inputs(
    window, monkeypatch
):
    start = pd.Timestamp("2026-10-07T12:00:00.123456789+02:00")
    frame = pd.DataFrame(
        {
            "time": [1000.0, 1001.0, 1002.0],
            "time_dt": start + pd.to_timedelta([0, 1, 2], unit="s"),
            **{f"gyroscope_{axis}": [np.nan, 1.0, 2.0] for axis in "xyz"},
        }
    )
    original = frame.copy(deep=True)
    calls = []
    gui_thread = get_ident()
    clock_preview = desktop.recording_clock

    def observed_clock_preview(*args, **kwargs):
        calls.append(get_ident())
        return clock_preview(*args, **kwargs)

    monkeypatch.setattr(desktop, "recording_clock", observed_clock_preview)
    window.loaded(("sensor.csv", frame))
    window.set_modules(["tremor"])
    wait_for_previews(window)
    count, origin = len(calls), window.clock_input.text()
    for _ in range(5):
        window.gaps.setChecked(not window.gaps.isChecked())
        window.acc.setCurrentIndex((window.acc.currentIndex() + 1) % window.acc.count())
        window.gyro.setCurrentIndex((window.gyro.currentIndex() + 1) % window.gyro.count())
    wait_for_previews(window)
    assert len(calls) == count and window.clock_input.text() == origin
    window.time.setCurrentText("absolute_s")
    window.drop_missing.setChecked(True)
    wait_for_previews(window)
    settings = {
        "time_input_unit": "absolute_s",
        "pipelines": ["tremor"],
        "drop_missing_samples": True,
    }
    expected = recording_clock(frame, settings, analysis_alignment(frame, settings, {})[0])
    assert window.clock_input.text() == expected["origin"]
    assert all(thread != gui_thread for thread in calls)
    window.clock_input.setText("2020-01-01T08:00:00+02:00")
    window.origin_edited()
    window.reset_origin()
    assert window.clock_input.text() == expected["origin"]  # Cached reset is immediate.
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


def test_module_clock_refresh_remains_editable_and_cannot_overwrite_a_user_origin(
    window, monkeypatch
):
    frame = pd.DataFrame(
        {
            "time": [1000.0, 1001.0, 1002.0],
            "time_dt": pd.date_range("2026-10-07T12:00:00Z", periods=3, freq="s"),
            **{f"gyroscope_{axis}": [1.0, 2.0, 3.0] for axis in "xyz"},
            **{f"accelerometer_{axis}": [np.nan, 2.0, 3.0] for axis in "xyz"},
        }
    )
    window.loaded(("sensor.csv", frame))
    window.time.setCurrentText("absolute_s")
    window.set_modules(["tremor"])
    wait_for_previews(window)
    entered, release = Event(), Event()
    original = desktop.recording_clock

    def slow_clock(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(desktop, "recording_clock", slow_clock)
    try:
        window.module_buttons["Gait"].click()
        assert window.clock_input.isEnabled()
        wait_until(entered.is_set)
        assert window.clock_input.isEnabled()
        custom = "2020-01-01T08:00:00+02:00"
        window.clock_input.setText(custom)
        window.origin_edited()
        release.set()
        wait_for_previews(window)
        assert window.clock_input.text() == custom
        assert window.origin_setting()["mode"] == "custom"
    finally:
        release.set()


@pytest.mark.parametrize("batch", [False, True], ids=["single", "multiple-recordings"])
def test_module_clock_preview_reuses_equivalent_requirements_and_skips_full_alignment(
    window, monkeypatch, batch
):
    calls, alignment_calls = [], []
    original = desktop.recording_clock

    def observed_clock(*args, **kwargs):
        calls.append(get_ident())
        return original(*args, **kwargs)

    def unexpected_alignment(*args, **kwargs):
        alignment_calls.append(True)
        raise AssertionError("A module toggle must not align result timelines")

    monkeypatch.setattr(desktop, "recording_clock", observed_clock)
    monkeypatch.setattr(recordings, "recording_clock", observed_clock)
    monkeypatch.setattr(desktop, "analysis_alignment", unexpected_alignment)
    monkeypatch.setattr(desktop, "align_recordings", unexpected_alignment)
    frame = pd.DataFrame(
        {
            "time": [0.0, 1.0, 2.0],
            "time_dt": pd.date_range("2026-10-07T12:00:00Z", periods=3, freq="s"),
            **{
                f"{sensor}_{axis}": 1.0
                for sensor in ("accelerometer", "gyroscope")
                for axis in "xyz"
            },
        }
    )
    if batch:
        frames = {"first": frame, "second": frame.copy(deep=True)}
        descriptions = {
            key: inspect_recording(value, "relative_s") for key, value in frames.items()
        }
        window.loaded_recordings(({key: f"{key}.csv" for key in frames}, frames, descriptions))
    else:
        window.loaded(("sensor.csv", frame))
    wait_for_previews(window)
    assert not alignment_calls
    count, origin = len(calls), window.clock_input.text()
    for modules in (["gait", "tremor"], ["gait"], ["tremor", "gait"]):
        window.set_modules(modules)
        assert window.clock_input.isEnabled() and not window._origin_preview.pending
        assert len(calls) == count and window.clock_input.text() == origin
    window.drop_missing.setChecked(False)
    wait_for_previews(window)
    count = len(calls)
    for modules in (["tremor"], ["pulse_rate"], [], ["gait"]):
        window.set_modules(modules)
        assert window.clock_input.isEnabled() and not window._origin_preview.pending
        assert len(calls) == count and window.clock_input.text() == origin
    window.drop_missing.setChecked(True)
    window.prepared.setChecked(True)
    wait_for_previews(window)
    count = len(calls)
    for modules in (["pulse_rate"], [], ["tremor"]):
        window.set_modules(modules)
        assert window.clock_input.isEnabled() and not window._origin_preview.pending
        assert len(calls) == count and window.clock_input.text() == origin
    assert calls and all(thread != get_ident() for thread in calls)


def test_time_and_sensor_descriptives_update_in_background_and_keep_source_values(
    window, monkeypatch
):
    frame = pd.DataFrame({"device_ticks": [0.0, 10.0, 20.0], "gyroscope_x": [1.0, 2.0, 3.0]})
    original = frame.copy(deep=True)
    gui_thread, threads = get_ident(), []
    for name in ("time_descriptives", "sensor_descriptives"):
        function = getattr(desktop, name)

        def observed(*args, operation=function, **kwargs):
            threads.append(get_ident())
            return operation(*args, **kwargs)

        monkeypatch.setattr(desktop, name, observed)
    window.loaded(("sensor.csv", frame))
    window.data_time_channel.setCurrentIndex(window.data_time_channel.findData("device_ticks"))
    window.data_time_unit.setCurrentText("relative_ms")
    wait_for_previews(window)
    pd.testing.assert_frame_equal(
        window.time_table.model().frame, time_descriptives(frame.device_ticks, "relative_ms")
    )
    pd.testing.assert_frame_equal(
        window.channel_table.model().frame, sensor_descriptives(frame, "device_ticks")
    )
    assert threads and all(thread != gui_thread for thread in threads)
    assert window.time_table.isEnabled() and window.channel_table.isEnabled()
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


def test_restoring_custom_origin_remains_editable_and_is_not_overwritten(window):
    frame = pd.DataFrame(
        {"time": [0.0, 1.0], "time_dt": pd.date_range("2026-10-07", periods=2, freq="s")}
    )
    window.loaded(("sensor.csv", frame))
    clock = {
        "origin": "2020-01-01T08:00:00+02:00",
        "timezone": "Europe/Amsterdam",
        "source": "User supplied",
    }
    window._run_state.selected_run = {
        "settings": {
            "pipelines": ["tremor"],
            "plot_time_origin": {"mode": "custom", "clock": clock},
        }
    }
    window.use_run_parameters()
    wait_for_previews(window)
    assert window.clock_input.isEnabled() and window.clock_input.text() == clock["origin"]
    assert window.origin_setting()["mode"] == "custom"
