"""File-derived Analyze defaults preserve source values and explicit user choices."""

import copy
import json
from importlib.resources import files

import pandas as pd
import pytest
from analysis_helpers import assert_fully_visible
from conftest import wait_for_previews
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from paradigma_studio.column_mapping import SIGNALS
from paradigma_studio.core import load_sensor_file
from paradigma_studio.input_metadata import METADATA_KEY, unit_defaults


@pytest.fixture
def sensor_frame():
    frame = pd.DataFrame(
        {
            "time": [0.0, 10.0, 20.0],
            **{column: [1.0, 2.0, 3.0] for column in SIGNALS if column != "time"},
        }
    )
    frame.attrs[METADATA_KEY] = {
        "format": "tsdf",
        "units": {
            "time": "relative_ms",
            **dict.fromkeys((f"accelerometer_{axis}" for axis in "xyz"), "m/s²"),
            **dict.fromkeys((f"gyroscope_{axis}" for axis in "xyz"), "rad/s"),
            "green": "none",
        },
    }
    frame.attrs["desktop_recording_start"] = "2026-10-22T08:00:00+00:00"
    return frame


def units(frame):
    return frame.attrs[METADATA_KEY]["units"]


def load(window, frame):
    window.loaded(("sensor.json", frame))
    window.set_modules(["gait", "pulse_rate"])


def badge(window, title):
    return window._analysis_controller.view.file_badges[title]


@pytest.mark.parametrize("source_format", ["tsdf", "cwa", "empatica"])
def test_supported_metadata_is_read_without_modifying_frames(sensor_frame, source_format):
    sensor_frame.attrs[METADATA_KEY]["format"] = source_format
    original = sensor_frame.copy(deep=True)
    attrs = copy.deepcopy(sensor_frame.attrs)
    defaults = unit_defaults({"one": sensor_frame}, dict(zip(SIGNALS, SIGNALS, strict=True)))
    assert {title: result.value for title, result in defaults.items()} == {
        "Acceleration units": "m/s^2",
        "Gyroscope units": "rad/s",
        "Time units": "relative_ms",
    }
    assert all("1 recording(s)" in item.detail for item in defaults.values())
    assert all(not item.issue for item in defaults.values())
    pd.testing.assert_frame_equal(sensor_frame, original)
    assert sensor_frame.attrs == attrs


@pytest.mark.parametrize("acceleration_unit", ["g", "m/s2", "m/s^2", " m/s² "])
def test_unit_spellings_are_normalized(sensor_frame, acceleration_unit):
    units(sensor_frame).update(
        dict.fromkeys((f"accelerometer_{axis}" for axis in "xyz"), acceleration_unit)
    )
    result = unit_defaults({"one": sensor_frame}, dict(zip(SIGNALS, SIGNALS, strict=True)))
    assert result["Acceleration units"].value == ("g" if acceleration_unit == "g" else "m/s^2")


@pytest.mark.parametrize(
    "unit",
    ["relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"],
)
def test_time_metadata_preserves_representation(sensor_frame, unit):
    units(sensor_frame)["time"] = unit
    result = unit_defaults({"one": sensor_frame}, {"time": "time"})
    assert result["Time units"].value == unit


@pytest.mark.parametrize("unit", ["s", "ms", "seconds", "unknown"])
def test_time_dimension_alone_does_not_establish_time_representation(sensor_frame, unit):
    units(sensor_frame)["time"] = unit
    result = unit_defaults({"one": sensor_frame}, {"time": "time"})
    assert result["Time units"].value is None
    assert "not supported" in result["Time units"].issue


def test_batch_consensus_uses_all_applicable_selected_columns(sensor_frame):
    second = sensor_frame.copy(deep=True)
    units(second).update(dict.fromkeys((f"accelerometer_{axis}" for axis in "xyz"), "m/s2"))
    recordings = {"one": sensor_frame, "two": second, "ppg_only": pd.DataFrame({"green": [1.0]})}
    choices = dict(zip(SIGNALS, SIGNALS, strict=True))
    result = unit_defaults(recordings, choices)
    assert result["Acceleration units"].value == "m/s^2"
    assert "2 recording(s)" in result["Acceleration units"].detail
    units(second)["accelerometer_z"] = "g"
    result = unit_defaults(recordings, choices)
    assert result["Acceleration units"].value is None
    assert "differ" in result["Acceleration units"].issue
    assert result["Gyroscope units"].value == "rad/s"
    second.attrs.clear()
    result = unit_defaults(recordings, choices)
    assert all(item.value is None for item in result.values())
    assert all("not declared consistently" in item.issue for item in result.values())
    assert "ppg_only" not in str(result)


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        [],
        {"format": []},
        {"format": "other", "units": {"time": "absolute_ms"}},
        {"format": "tsdf", "units": []},
    ],
)
def test_missing_or_unrecognized_metadata_never_guesses_from_numbers(sensor_frame, metadata):
    sensor_frame.attrs[METADATA_KEY] = metadata
    result = unit_defaults({"one": sensor_frame}, {"time": "time"})
    assert all(item.value is None and not item.issue for item in result.values())


def test_absent_unassigned_and_unselected_columns_do_not_supply_units(sensor_frame):
    sensor_frame["clock"] = [0.0, 0.01, 0.02]
    units(sensor_frame)["clock"] = "relative_s"
    assert (
        unit_defaults({"one": sensor_frame}, {"time": "clock"})["Time units"].value == "relative_s"
    )
    for source in (None, "missing"):
        result = unit_defaults({"one": sensor_frame}, {"time": source})
        assert result["Time units"].value is None and not result["Time units"].issue


def test_real_tsdf_units_are_preserved_after_scaling_and_prefilled(tsdf_writer, window):
    raw = pd.DataFrame(
        {"time": [0, 10, 20], **{f"gyroscope_{axis}": [100, 200, 300] for axis in "xyz"}}
    )
    path = tsdf_writer(raw, scale_factors=[0.01] * 3, dtype="int16")
    metadata = json.loads(path.read_text())
    for stream in metadata["datasets"]:
        stream["units"] = ["relative_ms"] if stream["channels"] == ["time"] else ["rad/s"] * 3
    path.write_text(json.dumps(metadata))
    frame = load_sensor_file(path)
    window.loaded((str(path), frame))
    window.set_modules(["tremor"])
    assert frame.time.tolist() == [0, 10, 20]
    assert frame.gyroscope_x.tolist() == [1.0, 2.0, 3.0]
    assert units(frame)["gyroscope_x"] == "rad/s"
    assert window.gyro.currentText() == "rad/s"
    assert window.time.currentText() == "relative_ms"
    assert not badge(window, "Gyroscope units").isHidden()
    assert not badge(window, "Time units").isHidden()
    assert badge(window, "Acceleration units").isHidden()
    assert "TSDF channel metadata" in window.analysis_help["Gyroscope units"][1].text()


@pytest.mark.parametrize("name", ["test_data.CWA", "test_data.avro"])
def test_real_device_imports_provide_units_even_when_equal_to_app_defaults(window, name):
    frame = load_sensor_file(files("paradigma_studio") / "data" / name)
    window.loaded((name, frame))
    window.set_modules(["pulse_rate"])
    assert window.acc.currentData() == "g"
    assert window.time.currentText() == "relative_s"
    assert not badge(window, "Acceleration units").isHidden()
    assert not badge(window, "Time units").isHidden()
    assert badge(window, "Gyroscope units").isHidden() == ("gyroscope_x" not in frame)
    assert window.mapping.axis_inversions() == []


@pytest.mark.parametrize("suffix", ["csv", "parquet", "pickle"])
def test_plain_tabular_formats_keep_defaults_without_claiming_metadata(
    window, sensor_frame, tmp_path, suffix
):
    sensor_frame.attrs.clear()
    path = tmp_path / f"sensor.{suffix}"
    getattr(sensor_frame, f"to_{suffix}")(path, **({"index": False} if suffix != "pickle" else {}))
    frame = load_sensor_file(path, allow_pickle=suffix == "pickle")
    load(window, frame)
    assert window.acc.currentData() == "g"
    assert window.gyro.currentText() == "deg/s"
    assert window.time.currentText() == "relative_s"
    assert all(
        badge(window, title).isHidden()
        for title in ("Acceleration units", "Gyroscope units", "Time units")
    )
    assert all(
        reset.isHidden() for reset in window._analysis_controller.view.file_default_buttons.values()
    )
    assert "App default" in window.analysis_help["Time units"][1].text()


def test_manual_units_and_not_included_apply_within_input_and_can_be_restored(window, sensor_frame):
    load(window, sensor_frame)
    window.acc.setCurrentIndex(window.acc.findData("g"))
    selector = window.mapping._combos["green"]
    selector.setCurrentIndex(selector.findData(None))
    window.set_modules(["pulse_rate"])
    assert window.acc.currentData() == "g"
    assert badge(window, "Acceleration units").isHidden()
    assert window.mapping.signal_columns()["green"] is None
    description = window.analysis_help["Acceleration units"][1]
    assert "Selected manually" in description.text()
    window._analysis_controller.view.file_default_buttons["Acceleration units"].click()
    assert window.acc.currentData() == "m/s^2"
    assert not badge(window, "Acceleration units").isHidden()
    assert window.mapping.signal_columns()["green"] is None
    window.acc.setCurrentIndex(window.acc.findData("g"))
    window.loaded(("second.json", sensor_frame.copy(deep=True)))
    assert window.acc.currentData() == "m/s^2"
    assert not badge(window, "Acceleration units").isHidden()
    assert window.mapping.signal_columns()["green"] == "green"


def test_selecting_the_existing_value_is_still_an_explicit_choice(window, sensor_frame):
    load(window, sensor_frame)
    window.navigate(1)
    window.acc.setFocus()
    window.acc.showPopup()
    QTest.keyClick(window.acc.view(), Qt.Key.Key_Return)
    assert badge(window, "Acceleration units").isHidden()
    window.set_modules(["tremor"])
    assert window.acc.currentData() == "m/s^2"
    assert badge(window, "Acceleration units").isHidden()
    second = sensor_frame.copy(deep=True)
    units(second).update(dict.fromkeys((f"accelerometer_{axis}" for axis in "xyz"), "g"))
    window.loaded(("next.json", second))
    assert window.acc.currentData() == "g"
    assert not badge(window, "Acceleration units").isHidden()


def test_mapping_changes_use_selected_column_units_and_remove_stale_tags(window, sensor_frame):
    sensor_frame["clock"] = [0.0, 0.01, 0.02]
    units(sensor_frame)["clock"] = "relative_s"
    load(window, sensor_frame)
    selector = window.mapping._combos["time"]
    selector.setCurrentIndex(selector.findData("clock"))
    assert window.time.currentText() == "relative_s"
    assert "declare relative_s" in window.analysis_help["Time units"][1].text()
    selector.setCurrentIndex(selector.findData(None))
    assert badge(window, "Time units").isHidden()
    assert "No supported unit metadata" in window.analysis_help["Time units"][1].text()


@pytest.mark.parametrize(
    "sensors", [(), ("accelerometer",), ("gyroscope",), ("accelerometer", "gyroscope")]
)
def test_sensor_unit_fields_follow_available_mappings(window, sensor_frame, sensors):
    assert not window.acc.isEnabled() and not window.gyro.isEnabled()
    columns = ["time", "green", *(f"{sensor}_{axis}" for sensor in sensors for axis in "xyz")]
    load(window, sensor_frame[columns])
    window.set_modules(["pulse_rate"])
    for split_by_gaps in (False, True, False):
        window.gaps.setChecked(split_by_gaps)
        for title, sensor, control in (
            ("Acceleration units", "accelerometer", window.acc),
            ("Gyroscope units", "gyroscope", window.gyro),
        ):
            expected = sensor in sensors
            assert control.isEnabled() == expected
            assert (
                window._analysis_controller.view.file_default_buttons[title].isEnabled() == expected
            )
        assert window.time.isEnabled()


@pytest.mark.parametrize(
    "sensor,title,field_name,other_name,manual_value,file_value",
    [
        ("accelerometer", "Acceleration units", "acc", "gyro", "g", "m/s^2"),
        ("gyroscope", "Gyroscope units", "gyro", "acc", "deg/s", "rad/s"),
    ],
)
def test_unassigning_and_remapping_axes_updates_units_without_losing_manual_choice(
    window, sensor_frame, sensor, title, field_name, other_name, manual_value, file_value
):
    load(window, sensor_frame)
    control = getattr(window, field_name)
    control.setCurrentIndex(
        control.findData(manual_value) if field_name == "acc" else control.findText(manual_value)
    )
    reset = window._analysis_controller.view.file_default_buttons[title]
    for axis in "xyz":
        selector = window.mapping._combos[f"{sensor}_{axis}"]
        selector.setCurrentIndex(selector.findData(None))
        assert control.isEnabled() == (axis != "z")
        assert getattr(window, other_name).isEnabled()
    assert not reset.isEnabled()
    assert badge(window, title).isHidden()
    window.set_modules(["pulse_rate"])
    assert not control.isEnabled()
    selector = window.mapping._combos[f"{sensor}_x"]
    selector.setCurrentIndex(selector.findData(f"{sensor}_y"))
    assert control.isEnabled() and reset.isEnabled()
    assert (control.currentData() if field_name == "acc" else control.currentText()) == manual_value
    reset.click()
    assert (control.currentData() if field_name == "acc" else control.currentText()) == file_value
    assert not badge(window, title).isHidden()
    window.mapping.default_button.click()
    assert window.acc.isEnabled() and window.gyro.isEnabled()


def test_unavailable_saved_sources_do_not_enable_sensor_unit_fields(window, sensor_frame):
    load(window, sensor_frame[["time", "green"]])
    window.mapping.set_mapping(
        {
            f"missing_{sensor}_{axis}": f"{sensor}_{axis}"
            for sensor in ("accelerometer", "gyroscope")
            for axis in "xyz"
        }
    )
    assert not window.acc.isEnabled() and not window.gyro.isEnabled()


def test_conflicting_batch_metadata_is_summarized_once_without_source_names(window, sensor_frame):
    second = sensor_frame.copy(deep=True)
    units(second)["time"] = "relative_s"
    recordings = {"first": sensor_frame, "second": second}
    sources = {"first": "private-first.json", "second": "private-second.json"}
    from paradigma_studio.inspection import inspect_recordings

    window.loaded_recordings((sources, recordings, inspect_recordings(recordings, "relative_ms")))
    window.set_modules(["pulse_rate"])
    notice = window._analysis_controller.view.metadata_notice
    assert not notice.isHidden()
    assert notice.text().count("Time units differ") == 1
    assert all(name not in notice.text() for name in sources.values())
    assert badge(window, "Time units").isHidden()
    assert not badge(window, "Acceleration units").isHidden()


def test_saved_parameters_remain_explicit_within_input_and_reset_on_new_load(window, sensor_frame):
    load(window, sensor_frame)
    window._run_state.selected_run = {
        "settings": {
            "pipelines": ["tremor"],
            "accelerometer_units": "g",
            "gyroscope_units": "deg/s",
            "time_input_unit": "relative_s",
        }
    }
    window.use_run_parameters()
    window.set_modules(["pulse_rate"])
    assert window.time.currentText() == "relative_s"
    assert badge(window, "Time units").isHidden()
    assert "Restored from saved run" in window.analysis_help["Time units"][1].text()
    second = sensor_frame.copy(deep=True)
    units(second)["time"] = "absolute_s"
    window.loaded(("next.json", second))
    assert window.time.currentText() == "absolute_s"
    assert not badge(window, "Time units").isHidden()
    assert "Restored from saved run" not in window.analysis_help["Time units"][1].text()


def test_manual_origin_applies_within_input_and_new_load_restores_automatic_origin(
    window, sensor_frame
):
    load(window, sensor_frame)
    wait_for_previews(window)
    assert not badge(window, "Time origin").isHidden()
    assert "Recording metadata" in window.analysis_help["Time origin"][1].text()
    window.clock_input.setText("2020-01-01T00:00:00+00:00")
    window.origin_edited()
    window.set_modules(["tremor"])
    wait_for_previews(window)
    assert pd.Timestamp(window.clock_input.text()) == pd.Timestamp("2020-01-01T00:00:00Z")
    assert badge(window, "Time origin").isHidden()
    window.origin_reset.click()
    wait_for_previews(window)
    assert pd.Timestamp(window.clock_input.text()) == pd.Timestamp("2026-10-22T08:00:00Z")
    window.clock_input.setText("2020-01-01T00:00:00Z")
    window.origin_edited()
    second = sensor_frame.copy(deep=True)
    second.attrs["desktop_recording_start"] = "2026-10-23T08:00:00+00:00"
    window.loaded(("next.json", second))
    wait_for_previews(window)
    assert pd.Timestamp(window.clock_input.text()) == pd.Timestamp("2026-10-23T08:00:00Z")
    assert not badge(window, "Time origin").isHidden()
    assert window.origin_setting() == {"mode": "automatic"}


def test_detected_units_are_passed_to_analysis_and_original_samples_stay_unchanged(
    window, sensor_frame, monkeypatch
):
    from paradigma_studio import app as desktop

    original = sensor_frame.copy(deep=True)
    attrs = copy.deepcopy(sensor_frame.attrs)
    load(window, sensor_frame)
    captured = []
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: captured.append((frame, settings)),
    )
    monkeypatch.setattr(window, "start_job", lambda function, callback: function(None))
    window.run_analysis()
    assert len(captured) == 1
    frame, settings = captured[0]
    assert settings["accelerometer_units"] == "m/s^2"
    assert settings["gyroscope_units"] == "rad/s"
    assert settings["time_input_unit"] == "relative_ms"
    assert "desktop_input_metadata" not in settings
    pd.testing.assert_frame_equal(frame, original)
    assert frame.attrs == attrs


@pytest.mark.parametrize("style", ["Fusion", "Windows"])
@pytest.mark.parametrize("minimum_height", [0, 44])
def test_file_tags_and_controls_fit_and_remain_reachable_at_native_sizes(
    window, sensor_frame, style, minimum_height
):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    original_style = app.style().objectName()
    app.setStyle(style)
    try:
        load(window, sensor_frame)
        for field in (window.acc, window.gyro, window.time):
            field.setMinimumHeight(minimum_height)
        wait_for_previews(window)
        window.navigate(1)
        for width, height in ((1450, 1050), (1200, 1050), (960, 650)):
            window.resize(width, height)
            QTest.qWait(30)
            assert window.analysis_scroll.horizontalScrollBar().maximum() == 0
            fields = (window.acc, window.gyro, window.time, window.clock_input)
            for field in (
                *fields,
                *window._analysis_controller.view.file_badges.values(),
                *window._analysis_controller.view.file_default_buttons.values(),
            ):
                window.analysis_scroll.ensureWidgetVisible(field)
                app.processEvents()
                assert_fully_visible(field)
            for title, source_badge in window._analysis_controller.view.file_badges.items():
                name = next(
                    label
                    for label in window.settings_panel.findChildren(QLabel)
                    if label.text() == title
                )
                name_position = name.mapTo(window, QPoint())
                badge_position = source_badge.mapTo(window, QPoint())
                assert badge_position.x() == name_position.x(), title
                assert badge_position.y() >= name_position.y() + name.height(), title
            assert_fully_visible(window.run_button)
    finally:
        app.setStyle(original_style)


def test_column_details_distinguish_matching_manual_and_explicit_selections(window, sensor_frame):
    load(window, sensor_frame)
    assert "Time: time (From file: exact column name)" in window.mapping.details.text()
    selector = window.mapping._combos["green"]
    selector.setCurrentIndex(selector.findData(None))
    assert "Green PPG: Not included (Selected manually)" in window.mapping.details.text()
    window.mapping.default_button.click()
    assert "Green PPG: green (From file: exact column name)" in window.mapping.details.text()
    window.mapping.set_mapping({}, signal_columns=dict.fromkeys(SIGNALS))
    assert "Time: Not included (Explicit mapping)" in window.mapping.details.text()
    window.mapping.reset()
    window.mapping.auto_match()
    window.mapping.set_recordings({"other": ["timestamp", "green"]}, {})
    assert "Time: Not included (Not assigned)" in window.mapping.details.text()


def test_default_buttons_restore_locally_and_documentation_links_stay_enabled(window, sensor_frame):
    load(window, sensor_frame)
    description = window.analysis_help["Time units"][1]
    assert description.openExternalLinks()
    assert 'href="https://' in description.text()
    window.time.setCurrentText("relative_s")
    window._analysis_controller.view.file_default_buttons["Time units"].click()
    assert window.time.currentText() == "relative_ms"
    assert description.openExternalLinks()
    assert "use-file-value" not in description.text()
