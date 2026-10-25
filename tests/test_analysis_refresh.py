"""Analyze changes refresh their dependencies after complete settings are installed."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_previews
from PySide6.QtTest import QSignalSpy

from paradigma_studio.axis_mapping import IMU_COLUMNS
from paradigma_studio.column_mapping import SIGNALS
from paradigma_studio.input_metadata import METADATA_KEY
from paradigma_studio.inspection import inspect_recordings


def recording():
    frame = pd.DataFrame(
        {"time": np.arange(400) / 100, **dict.fromkeys(IMU_COLUMNS, 1.0), "green": 2.0}
    )
    frame.attrs["desktop_recording_start"] = "2026-10-24T10:00:00Z"
    frame.attrs[METADATA_KEY] = {
        "format": "tsdf",
        "units": {
            "time": "relative_s",
            **dict.fromkeys(IMU_COLUMNS[:3], "g"),
            **dict.fromkeys(IMU_COLUMNS[3:], "deg/s"),
        },
    }
    return frame


def test_sensor_units_and_gap_edits_do_not_republish_an_unchanged_origin(window):
    window.loaded(("sensor.json", recording()))
    wait_for_previews(window)
    preview = window._origin_preview
    preview.cancel_pending()
    published = QSignalSpy(preview.value_ready)
    origin = window.clock_input.text()
    window.gaps.setChecked(False)
    assert not window.max_gap.isEnabled() and not window.min_segment.isEnabled()
    window.acc.setCurrentIndex(window.acc.findData("m/s^2"))
    window.gyro.setCurrentText("rad/s")
    window._analysis_controller.view.file_default_buttons["Acceleration units"].click()
    window.gaps.setChecked(True)
    assert window.max_gap.isEnabled() and window.min_segment.isEnabled()
    assert window.acc.currentData() == "g" and window.gyro.currentText() == "rad/s"
    assert published.count() == 0 and not preview.pending
    assert window.clock_input.text() == origin


def test_time_unit_default_restores_the_shared_format_and_retries_origin(window):
    window.loaded(("sensor.json", recording()))
    wait_for_previews(window)
    window.time.activated.emit(window.time.currentIndex())
    window.data_time_unit.setCurrentText("absolute_ms")
    window._origin_preview.cancel_pending()
    published = QSignalSpy(window._origin_preview.value_ready)
    window._analysis_controller.view.file_default_buttons["Time units"].click()
    assert published.count() == 1
    assert window.data_time_unit.currentText() == window.time.currentText() == "relative_s"
    assert not window._analysis_controller.view.file_badges["Time units"].isHidden()


@pytest.mark.parametrize("mode", ["automatic", "custom", "elapsed"])
@pytest.mark.parametrize("change_time_unit", [False, True])
def test_saved_settings_are_complete_before_one_preview_and_data_notification(
    window, monkeypatch, mode, change_time_unit
):
    frame = recording()
    frame["device_clock"] = frame.time * 1000 if change_time_unit else frame.time
    frame["optical"] = frame.green
    window.loaded(("sensor.json", frame))
    wait_for_previews(window)
    # Restore the mapping with either the same shared format or a different one.
    time_unit = "relative_ms" if change_time_unit else "relative_s"
    choices = {**dict.fromkeys(SIGNALS), "time": "device_clock", "green": "optical"}
    saved = {
        "pipelines": ["pulse_rate"],
        "watch_side": "right",
        "accelerometer_units": "m/s^2",
        "gyroscope_units": "rad/s",
        "time_input_unit": time_unit,
        "signal_columns": choices,
        "column_mapping": {"device_clock": "time", "optical": "green"},
        "axis_inversions": ["gyroscope_y"],
        "split_by_gaps": False,
        "drop_missing_samples": False,
        "max_gap_seconds": 3.5,
        "min_segment_seconds": 8.0,
        "plot_time_origin": {"mode": mode},
    }
    if mode == "custom":
        saved["plot_time_origin"]["clock"] = {
            "origin": "2020-01-01T08:00:00+02:00",
            "timezone": "Europe/Amsterdam",
            "source": "User supplied",
        }
    original = deepcopy(saved)
    controller = window._analysis_controller
    requests, notifications = [], []
    request = window._origin_preview.request
    sync = controller.callbacks.sync_input

    def assert_final_values():
        assert not controller.file_defaults.applying
        actual = controller._analysis_settings(controller.selected_modules())
        for key, value in saved.items():
            if key != "plot_time_origin":
                assert actual[key] == value
        assert actual["plot_time_origin"]["mode"] == mode

    def observe_request(key, operation):
        assert_final_values()
        requests.append(key)
        request(key, operation)

    def observe_sync(configuration, mapping_changed):
        assert_final_values()
        notifications.append((configuration.unit, mapping_changed))
        sync(configuration, mapping_changed)

    monkeypatch.setattr(window._origin_preview, "request", observe_request)
    controller.callbacks = replace(controller.callbacks, sync_input=observe_sync)
    widget_changes = [
        QSignalSpy(field)
        for field in (
            window.time.currentTextChanged,
            window.mapping.changed,
            window.clock_input.valueEdited,
        )
    ]
    window._run_state.selected_run = {"settings": saved}
    window.use_run_parameters()
    assert len(requests) == (1 if mode == "automatic" else 0)
    assert notifications == [(time_unit, True)]
    assert all(changes.count() == 0 for changes in widget_changes)
    assert window.data_time_unit.currentText() == time_unit
    wait_for_previews(window)
    assert_final_values()
    if mode == "custom":
        assert window.clock_input.text() == saved["plot_time_origin"]["clock"]["origin"]
    elif mode == "elapsed":
        assert window.clock_input.text() == ""
    assert saved == original


@pytest.mark.parametrize("batch", [False, True])
def test_new_input_performs_one_complete_analysis_refresh(window, monkeypatch, batch):
    controller = window._analysis_controller
    refresh = controller.refresh
    calls = []

    def observe_refresh(**kwargs):
        calls.append(kwargs)
        refresh(**kwargs)

    monkeypatch.setattr(controller, "refresh", observe_refresh)
    frame = recording()
    if batch:
        frames = {"one": frame, "two": frame.copy(deep=True)}
        window.loaded_recordings(
            (
                {key: f"{key}.json" for key in frames},
                frames,
                inspect_recordings(frames, "relative_s"),
            )
        )
    else:
        window.loaded(("sensor.json", frame))
    wait_for_previews(window)
    assert calls == [{"mapping_changed": True}]
    assert window.run_button.isEnabled() and window.selected_modules() == ["gait"]


def test_manual_origin_does_not_suppress_mapping_metadata_or_unit_availability(window):
    frame = recording()
    frame["clock_ms"] = frame.time * 1000
    frame.attrs[METADATA_KEY]["units"]["clock_ms"] = "relative_ms"
    window.loaded(("sensor.json", frame))
    wait_for_previews(window)
    entered = "2020-01-01T08:00:00Z"
    window.clock_input.setText(entered)
    window.origin_edited()
    selector = window.mapping._combos["time"]
    selector.setCurrentIndex(selector.findData("clock_ms"))
    for axis in "xyz":
        selector = window.mapping._combos[f"accelerometer_{axis}"]
        selector.setCurrentIndex(selector.findData(None))
    assert window.time.currentText() == window.data_time_unit.currentText() == "relative_ms"
    assert not window._analysis_controller.view.file_badges["Time units"].isHidden()
    assert not window.acc.isEnabled() and window.gyro.isEnabled()
    assert window.clock_input.text() == entered and window.origin_setting()["mode"] == "custom"
