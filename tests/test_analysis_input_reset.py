"""Successful replacement loads start Analyze afresh; inspection keeps batch edits."""

import copy
import time
from dataclasses import replace
from threading import Event

import pandas as pd
import pytest
from conftest import wait_for_previews
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from paradigma_studio.analysis_help import DEFAULT_MAX_GAP_SECONDS, DEFAULT_MIN_SECTION_SECONDS
from paradigma_studio.column_mapping import SIGNALS
from paradigma_studio.input_metadata import METADATA_KEY
from paradigma_studio.inspection import inspect_recordings


def recording(*, start="2026-10-22T08:00:00+00:00", unit="relative_ms"):
    frame = pd.DataFrame(
        {
            "time": [0.0, 10.0, 20.0],
            **{column: [1.0, 2.0, 3.0] for column in SIGNALS if column != "time"},
        }
    )
    frame.attrs["desktop_recording_start"] = start
    frame.attrs[METADATA_KEY] = {
        "format": "tsdf",
        "units": {
            "time": unit,
            **dict.fromkeys((f"accelerometer_{axis}" for axis in "xyz"), "m/s²"),
            **dict.fromkeys((f"gyroscope_{axis}" for axis in "xyz"), "rad/s"),
        },
    }
    return frame


def load_batch(window, frames):
    sources = {key: f"{key}.json" for key in frames}
    window.loaded_recordings((sources, frames, inspect_recordings(frames, "relative_ms")))


@pytest.mark.parametrize("batch", [False, True])
def test_new_inputs_automatically_match_aliases_and_prefill_their_metadata(window, batch):
    window.loaded(("previous.json", recording()))
    edit_all_settings(window)
    aliases = dict(
        zip(SIGNALS, ("timestamp", "ax", "ay", "az", "gx", "gy", "gz", "ppg"), strict=True)
    )
    frame = recording(start="2026-10-23T08:00:00+00:00").rename(columns=aliases)
    frame.attrs[METADATA_KEY]["units"] = {
        aliases[column]: unit for column, unit in frame.attrs[METADATA_KEY]["units"].items()
    }
    if batch:
        load_batch(window, {"one": frame, "two": frame.copy(deep=True)})
    else:
        window.loaded(("new.json", frame))
    wait_for_previews(window)
    assert window.mapping.signal_columns() == aliases
    assert all(not badge.isHidden() for badge in window.mapping._file_badges.values())
    assert window.acc.currentData() == "m/s^2"
    assert window.gyro.currentText() == "rad/s"
    assert window.time.currentText() == "relative_ms"
    assert window.mapping.axis_inversions() == []
    assert pd.Timestamp(window.clock_input.text()) == pd.Timestamp("2026-10-23T08:00:00Z")
    assert all(
        not reset.isHidden() and reset.isEnabled()
        for reset in window._analysis_controller.view.file_default_buttons.values()
    )


def edit_all_settings(window):
    window.set_modules(["tremor", "pulse_rate"])
    window.side.setCurrentText("right")
    window.acc.setCurrentIndex(window.acc.findData("g"))
    window.gyro.setCurrentText("deg/s")
    window.time.setCurrentText("absolute_ms")
    window.mapping._combos["green"].setCurrentIndex(window.mapping._combos["green"].findData(None))
    window.mapping.set_axis_inversions(["accelerometer_x", "gyroscope_y"])
    window.drop_missing.setChecked(False)
    window.gaps.setChecked(False)
    window.max_gap.setValue(7.5)
    window.min_segment.setValue(9.0)
    window.prepared.setChecked(True)
    window.clock_input.setText("2020-01-01T00:00:00Z")
    window.origin_edited()
    window.navigate(1)
    window.resize(960, 650)
    window.mapping.optional_button.click()
    window.mapping.details_button.click()
    window.analysis_help["Time units"][0].click()
    QTest.qWait(30)
    bar = window.analysis_scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert bar.value() > 0


@pytest.mark.parametrize("load_mode", ["single", "one_file_batch", "batch"])
def test_successful_new_load_resets_every_analyze_setting_and_uses_new_metadata(
    window, monkeypatch, load_mode
):
    original = recording()
    original_attrs = copy.deepcopy(original.attrs)
    window.loaded(("old.json", original))
    edit_all_settings(window)
    second = recording(start="2026-10-23T08:00:00+00:00", unit="relative_s")
    second_attrs = copy.deepcopy(second.attrs)
    resets = []
    reset = window._analysis_controller.reset_for_input

    def observe_reset():
        resets.append(window._input_state.frame)
        reset()

    monkeypatch.setattr(window._analysis_controller, "reset_for_input", observe_reset)
    if load_mode == "single":
        window.loaded(("new.json", second))
    else:
        frames = {"first": second}
        if load_mode == "batch":
            frames["second"] = recording(start="2026-10-24T08:00:00+00:00", unit="relative_s")
        load_batch(window, frames)
    wait_for_previews(window)
    assert len(resets) == 1 and resets[0] is second
    assert window.selected_modules() == ["gait"]
    assert window.side.currentText() == "left"
    assert window.acc.currentData() == "m/s^2"
    assert window.gyro.currentText() == "rad/s"
    assert window.time.currentText() == "relative_s"
    assert not window.prepared.isChecked()
    assert window.gaps.isChecked() and window.drop_missing.isChecked()
    assert window.max_gap.value() == DEFAULT_MAX_GAP_SECONDS
    assert window.min_segment.value() == DEFAULT_MIN_SECTION_SECONDS
    assert all(control.isEnabled() for control in (window.acc, window.gyro, window.time))
    assert window.max_gap.isEnabled() and window.min_segment.isEnabled()
    assert window.mapping.signal_columns() == dict(zip(SIGNALS, SIGNALS, strict=True))
    assert window.mapping.mapping() == {} and window.mapping.axis_inversions() == []
    assert all(checkbox.isEnabled() for checkbox in window.mapping._inversions.values())
    assert window.mapping.optional_button.text() == "Show optional signals"
    assert window.mapping.details.isHidden() and not window.mapping.details_button.isChecked()
    assert window.mapping.details_button.text() == "Show details"
    assert not any(info.isChecked() for info, _description in window.analysis_help.values())
    assert window.analysis_help_panel.isHidden()
    assert window.analysis_scroll.verticalScrollBar().value() == 0
    assert window.origin_setting() == {"mode": "automatic"}
    assert pd.Timestamp(window.clock_input.text()) == pd.Timestamp("2026-10-23T08:00:00Z")
    assert all(
        not badge.isHidden() for badge in window._analysis_controller.view.file_badges.values()
    )
    assert original.attrs == original_attrs and second.attrs == second_attrs
    pd.testing.assert_frame_equal(original, recording())


@pytest.mark.parametrize("load_mode", ["single", "one_file_batch", "batch"])
@pytest.mark.parametrize("parameter_source", ["manual", "saved_run"])
def test_new_file_without_metadata_removes_all_previous_settings(
    window, load_mode, parameter_source
):
    window.loaded(("old.json", recording()))
    edit_all_settings(window)
    if parameter_source == "saved_run":
        window._run_state.selected_run = {
            "settings": window._analysis_controller._analysis_settings(window.selected_modules())
        }
        window.use_run_parameters()
    plain = pd.DataFrame({column: [0.0, 1.0, 2.0] for column in SIGNALS})
    if load_mode == "single":
        window.loaded(("new.csv", plain))
    else:
        frames = {"first": plain}
        if load_mode == "batch":
            frames["second"] = plain.copy(deep=True)
        load_batch(window, frames)
    wait_for_previews(window)
    assert window._analysis_controller._analysis_settings(window.selected_modules()) == {
        "pipelines": ["gait"],
        "watch_side": "left",
        "accelerometer_units": "g",
        "gyroscope_units": "deg/s",
        "time_input_unit": "relative_s",
        "device_orientation": ["x", "y", "z"],
        "axis_inversions": [],
        "signal_columns": dict(zip(SIGNALS, SIGNALS, strict=True)),
        "skip_preparation": False,
        "split_by_gaps": True,
        "max_gap_seconds": DEFAULT_MAX_GAP_SECONDS,
        "min_segment_seconds": DEFAULT_MIN_SECTION_SECONDS,
        "column_mapping": {},
        "drop_missing_samples": True,
        "plot_time_origin": {"mode": "automatic"},
    }
    assert window.clock_input.text() == ""
    assert window.clock_input.calendar.text() == "Not set"
    assert not window.clock_input.use.isChecked()
    assert window.mapping.axis_inversions() == []
    assert not window._analysis_controller.file_defaults.manual
    assert all(badge.isHidden() for badge in window._analysis_controller.view.file_badges.values())
    assert all(
        button.isHidden()
        for button in window._analysis_controller.view.file_default_buttons.values()
    )
    assert window._analysis_controller.view.metadata_notice.isHidden()
    assert "No supported unit metadata" in window.analysis_help["Time units"][1].text()
    assert all(
        "Selected manually" not in description.text()
        and "Restored from saved run" not in description.text()
        for _info, description in window.analysis_help.values()
    )
    assert window.mapping.signal_columns()["green"] == "green"


@pytest.mark.parametrize("new_has_origin", [False, True])
def test_pending_clock_from_previous_input_cannot_replace_the_new_origin(window, new_has_origin):
    old, new = recording(), recording(start="2026-10-23T08:00:00Z")
    if not new_has_origin:
        new.attrs.pop("desktop_recording_start")
    entered, release = Event(), Event()
    seen = []
    controller = window._analysis_controller

    def clock(frame, _settings):
        seen.append(frame)
        if frame is old:
            entered.set()
            assert release.wait(10)
        if "desktop_recording_start" not in frame.attrs:
            return None
        return {
            "origin": frame.attrs["desktop_recording_start"],
            "timezone": "UTC",
            "source": "Recording metadata",
        }

    controller.services = replace(controller.services, recording_clock=clock)
    try:
        window.loaded(("old.json", old))
        deadline = time.monotonic() + 5
        while not entered.is_set() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        assert entered.is_set()
        window.clock_input.setText("2020-01-01T00:00:00Z")
        window.origin_edited()
        window.loaded(("new.json", new))
        release.set()
        wait_for_previews(window)
        assert len(seen) == 2 and seen[0] is old and seen[1] is new
        if new_has_origin:
            assert pd.Timestamp(window.clock_input.text()) == pd.Timestamp("2026-10-23T08:00:00Z")
        else:
            assert window.clock_input.text() == ""
            assert window.clock_input.calendar.text() == "Not set"
            assert window._analysis_controller.view.file_badges["Time origin"].isHidden()
        assert window.origin_setting() == {"mode": "automatic"}
    finally:
        release.set()


def test_switching_loaded_batch_recordings_keeps_manual_and_saved_settings(window):
    frames = {"first": recording(), "second": recording(start="2026-10-23T08:00:00Z")}
    load_batch(window, frames)
    edit_all_settings(window)
    before = window._analysis_controller._analysis_settings(window.selected_modules())
    window.input_recording.setCurrentIndex(1)
    wait_for_previews(window)
    after = window._analysis_controller._analysis_settings(window.selected_modules())
    assert after == before
    assert window.mapping.details_button.isChecked()
    assert window.analysis_help["Time units"][0].isChecked()
    window._run_state.selected_run = {
        "settings": {
            "pipelines": ["tremor"],
            "accelerometer_units": "g",
            "gyroscope_units": "deg/s",
            "time_input_unit": "relative_s",
        }
    }
    window.use_run_parameters()
    window.input_recording.setCurrentIndex(0)
    wait_for_previews(window)
    assert window.selected_modules() == ["tremor"]
    assert window.time.currentText() == "relative_s"
    assert "Restored from saved run" in window.analysis_help["Time units"][1].text()


@pytest.mark.parametrize("outcome", ["cancelled", "failed"])
def test_cancelled_or_failed_file_load_keeps_the_existing_analyze_settings(
    window, monkeypatch, outcome
):
    frame = recording()
    window.loaded(("old.json", frame))
    edit_all_settings(window)
    before = window._analysis_controller._analysis_settings(window.selected_modules())
    controller = window._data_controller
    paths = [] if outcome == "cancelled" else ["missing.csv"]
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (paths, ""))

    def fail_load(*args, **kwargs):
        raise OSError("Could not read the new file")

    controller.services = replace(controller.services, load_recordings=fail_load)
    controller.callbacks = replace(
        controller.callbacks, start_job=lambda operation, _done: operation(None)
    )
    if outcome == "failed":
        with pytest.raises(OSError, match="Could not read"):
            controller.open_file()
    else:
        controller.open_file()
    after = window._analysis_controller._analysis_settings(window.selected_modules())
    assert after == before
    assert window._input_state.frame is frame and window._input_state.source == "old.json"
    assert window.mapping.details_button.isChecked()
