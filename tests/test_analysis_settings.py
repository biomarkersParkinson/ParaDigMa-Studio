"""Analysis settings, help documentation and display-origin configuration."""

from copy import deepcopy

import pandas as pd
from conftest import wait_for_previews
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget


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
    assert (
        window.prepared.isChecked()
        == signature(run_paradigma).parameters["skip_preparation"].default
    )
    window.navigate(1)
    window.show()
    QApplication.instance().processEvents()
    for prepared in (False, True):
        window.prepared.setChecked(prepared)
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


def test_inline_analysis_help_does_not_change_configuration(window):
    from paradigma_studio.analysis_help import FIELD_HELP

    assert set(window.analysis_help) == set(FIELD_HELP)

    def configuration():
        return (
            window.selected_modules(),
            window.side.currentText(),
            window.acc.currentText(),
            window.gyro.currentText(),
            window.time.currentText(),
            window.mapping.axis_inversions(),
            window.prepared.isChecked(),
            window.gaps.isChecked(),
            window.drop_missing.isChecked(),
            window.max_gap.value(),
            window.min_segment.value(),
            window.mapping.mapping(),
        )

    for child in window.pages.widget(1).findChildren(QWidget):
        if not window.mapping.isAncestorOf(child):
            assert not child.toolTip()
    assert all(checkbox.toolTip() for checkbox in window.mapping._inversions.values())
    before = configuration()
    window.navigate(1)
    window.show()
    for title, (info, description) in window.analysis_help.items():
        assert description.isHidden()
        assert info.accessibleName() == f"Information: {title}"
        info.click()
        assert not description.isHidden()
        assert "ParaDigMa documentation" in description.text()
        assert window.pages.widget(1).isAncestorOf(description)
        info.click()
        assert description.isHidden()
    assert configuration() == before
    assert "toolbox X = minus sensor Y" in window.analysis_help["Signal columns"][1].text()
    assert "Choose the column in your files" in window.analysis_help["Signal columns"][1].text()


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
