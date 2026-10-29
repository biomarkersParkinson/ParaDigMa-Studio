"""Analysis settings, help documentation and display-origin configuration."""

from copy import deepcopy

import pandas as pd
import pytest
from conftest import wait_for_previews
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from paradigma_studio.column_mapping import SIGNALS
from paradigma_studio.input_metadata import METADATA_KEY


def test_analyze_time_origin_defaults_reset_and_never_changes_pipeline_arguments(
    window, monkeypatch
):
    from paradigma_studio import app as desktop

    original = pd.DataFrame(
        {
            "time": [0.0, 0.01, 0.02],
            "time_dt": pd.date_range("2026-10-07T12:00:00.123456789Z", periods=3, freq="10ms"),
            **{f"gyroscope_{axis}": [1.0, 2.0, 3.0] for axis in "xyz"},
        }
    )
    original.attrs["desktop_recording_start"] = original.time_dt.iloc[0].isoformat()
    window.loaded(("sensor.csv", original))
    window.set_modules(["tremor"])
    wait_for_previews(window)
    derived_origin = window.clock_input.text()
    assert pd.Timestamp(derived_origin) == original.time_dt.iloc[0]
    window.clock_input.setText("2020-01-01T08:00:00+02:00")
    window.origin_edited()
    captured = []
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: captured.append((frame, settings)),
    )
    monkeypatch.setattr(window, "start_job", lambda function, callback: function(None))
    window.run_analysis()
    assert len(captured) == 1 and "plot_time_origin" not in captured[0][1]
    pd.testing.assert_frame_equal(captured[0][0], original)
    clock = window._run_state.current_run["settings"]["plot_time_origin"]["clock"]
    assert pd.Timestamp(clock["origin"]) == pd.Timestamp("2020-01-01T08:00:00+02:00")
    assert (
        clock["timezone"] == "UTC"
    )  # Preserve the recording zone while accepting an explicit offset.
    window.reset_origin()
    assert window.clock_input.text() == derived_origin
    assert window.origin_setting() == {"mode": "automatic"}


def test_irrelevant_watch_side_is_blank_and_retains_the_users_choice(window):
    window.navigate(1)
    window.show()
    window.side.setCurrentText("right")
    window.set_modules(["tremor", "pulse_rate"])
    assert not window.side.isEnabled()
    hidden_right = window.side.grab().toImage()
    window.side.setCurrentText("left")
    assert window.side.grab().toImage() == hidden_right
    window.side.setCurrentText("right")
    window.set_modules(["gait"])
    assert window.side.isEnabled()
    assert window.side.currentText() == "right"
    assert window.side.grab().toImage() != hidden_right
    # Disabling the form during a job must not hide a relevant parameter.
    window.settings_panel.setEnabled(False)
    shown_right = window.side.grab().toImage()
    window.side.setCurrentText("left")
    assert window.side.grab().toImage() != shown_right


def test_desktop_preparation_defaults_and_official_threshold_resets_remain_available(window):
    from inspect import signature

    from paradigma.orchestrator import run_paradigma
    from paradigma.prepare_data import prepare_raw_data

    from paradigma_studio.analysis_help import DEFAULT_MAX_GAP_SECONDS, DEFAULT_MIN_SECTION_SECONDS

    defaults = signature(prepare_raw_data).parameters
    assert (
        window.max_gap.value() == DEFAULT_MAX_GAP_SECONDS == defaults["max_segment_gap_s"].default
    )
    assert (
        window.min_segment.value()
        == DEFAULT_MIN_SECTION_SECONDS
        == defaults["min_segment_length_s"].default
    )
    assert window.gaps.isChecked() and window.drop_missing.isChecked()
    settings = window._analysis_controller._analysis_settings(["gait"])
    assert settings["split_by_gaps"] and settings["drop_missing_samples"]
    assert (
        window.acc.currentText()
        == signature(run_paradigma).parameters["accelerometer_units"].default
    )
    assert (
        window.gyro.currentText() == signature(run_paradigma).parameters["gyroscope_units"].default
    )
    assert (
        window.time.currentText() == signature(run_paradigma).parameters["time_input_unit"].default
    )
    assert (
        window._analysis_controller._analysis_settings(["gait"])["device_orientation"]
        == signature(run_paradigma).parameters["device_orientation"].default
    )
    assert "skip_preparation" not in settings
    window.navigate(1)
    window.show()
    QApplication.instance().processEvents()
    for split_by_gaps in (False, True):
        window.gaps.setChecked(split_by_gaps)
        window.max_gap.setValue(4.0)
        window.min_segment.setValue(8.0)
        for title in ("Maximum gap", "Minimum section duration"):
            reset = window.section_reset_buttons[title]
            assert reset.isEnabled()
            reset.click()
        assert window.max_gap.value() == DEFAULT_MAX_GAP_SECONDS
        assert window.min_segment.value() == DEFAULT_MIN_SECTION_SECONDS
    assert window.segmentation_controls.isAncestorOf(window.gaps)
    assert window.segmentation_controls.isAncestorOf(window.max_gap)
    assert window.segmentation_controls.isAncestorOf(window.min_segment)

    ys = [
        item.mapTo(window.settings_panel, QPoint(0, 0)).y()
        for item in (
            window.time,
            window.clock_input,
            window.drop_missing,
            window.gaps,
            window.max_gap,
            window.min_segment,
        )
    ]
    assert ys == sorted(ys)
    mapping_start = window.mapping.mapTo(window.settings_panel, QPoint(0, 0))
    gap_start = window.gaps.mapTo(window.settings_panel, QPoint(0, 0))
    assert mapping_start.x() < gap_start.x() and mapping_start.y() < gap_start.y()


@pytest.mark.parametrize("origin_mode", ["automatic", "custom"])
def test_analysis_help_windows_do_not_change_configuration(window, origin_mode):
    frame = pd.DataFrame(
        {column: [0.0, 10.0, 20.0] for column in (*SIGNALS, "device_clock", "optical")}
    )
    frame.attrs["desktop_recording_start"] = "2026-10-25T08:00:00Z"
    frame.attrs[METADATA_KEY] = {"format": "tsdf", "units": {"time": "relative_ms"}}
    window.loaded(("sensor.json", frame))
    window.set_modules(["gait", "tremor", "pulse_rate"])
    window.mapping.set_mapping({"device_clock": "time", "optical": "green"})
    window.mapping.set_axis_inversions(["accelerometer_x", "gyroscope_y"])
    window.side.setCurrentText("right")
    window.acc.setCurrentIndex(window.acc.findData("m/s^2"))
    window.gyro.setCurrentText("rad/s")
    window.time.setCurrentText("difference_ms")
    window.gaps.setChecked(False)
    window.drop_missing.setChecked(False)
    window.max_gap.setValue(7.5)
    window.min_segment.setValue(9.0)
    if origin_mode == "custom":
        window.clock_input.setText("2020-01-01T08:00:00+02:00")
        window.origin_edited()
    wait_for_previews(window)

    def configuration():
        return (
            window._analysis_controller._analysis_settings(window.selected_modules()),
            window.clock_input.text(),
        )

    before = deepcopy(configuration())
    assert before[0]["plot_time_origin"]["mode"] == origin_mode
    expected_origin = (
        "2020-01-01T08:00:00+02:00" if origin_mode == "custom" else "2026-10-25T08:00:00Z"
    )
    assert pd.Timestamp(before[1]) == pd.Timestamp(expected_origin)
    assert before[0]["signal_columns"]["time"] == "device_clock"
    assert before[0]["signal_columns"]["green"] == "optical"
    window.navigate(1)
    for title, (info, _description) in window.analysis_help.items():
        info.click()
        QApplication.processEvents()
        assert configuration() == before, (title, "open")
        window._analysis_controller.view.analysis_help_dialogs[title].close()
        QApplication.processEvents()
        assert configuration() == before, (title, "close")


def test_analyze_calendar_default_preserves_source_precision_and_results(window):
    start = pd.Timestamp("2026-10-07T12:00:00.123456789+02:00")
    raw = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0], "time_dt": start + pd.to_timedelta([0.0, 1.0, 2.0], unit="s")}
    )
    raw.attrs["desktop_recording_start"] = start.isoformat()
    window.loaded(("sensor.csv", raw))
    wait_for_previews(window)
    assert window.clock_input.text() == start.isoformat()
    assert window.clock_input.calendar.calendarPopup()
    window._result_state.provenance = {"settings": {"skip_preparation": True}}
    result = {
        "quantifications": {
            name: pd.DataFrame({"time": [0.0, 1.0, 2.0], "metric": [4.0, 5.0, 6.0]})
            for name in ("tremor", "pulse_rate")
        }
    }
    window.analyzed(result)
    original = deepcopy(window._result_state.display_clock)
    window.clock_input.calendar.setDateTime(window.clock_input.calendar.dateTime().addMSecs(1500))
    assert window.origin_setting()["mode"] == "custom"
    assert window._result_state.display_clock == original
    assert all(
        positions.tolist() == [0, 1, 2]
        for _, positions in window._result_state._detail_selections.values()
    )
    window.origin_reset.click()
    assert window.clock_input.text() == start.isoformat()
