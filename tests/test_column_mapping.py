"""Signal mapping choices, header-only batch checks and saved mapping fidelity."""

import pytest
from PySide6.QtTest import QSignalSpy

from paradigma_studio.column_mapping import SIGNALS, ColumnMapping, required_signals
from paradigma_studio.ui.column_mapping import ColumnMappingEditor


@pytest.fixture
def model():
    value = ColumnMapping()
    value.set_recordings({"one": list(SIGNALS)}, {"one": "sensor.csv"})
    return value


@pytest.fixture
def editor(window):
    return ColumnMappingEditor(window)


@pytest.mark.parametrize(
    "modules,expected",
    [
        ([], {"time"}),
        (["pulse_rate"], {"time", "green"}),
        (["tremor"], {"time", *(f"gyroscope_{axis}" for axis in "xyz")}),
        (["gait"], set(SIGNALS) - {"green"}),
        (["gait", "tremor", "pulse_rate"], set(SIGNALS)),
    ],
)
def test_required_rows_follow_selected_workflows(modules, expected):
    assert required_signals(modules) == expected


def test_standard_names_need_no_renames(model):
    assert model.mapping() == {}
    assert model.choices == {signal: signal for signal in SIGNALS}
    assert model.validate(["gait", "pulse_rate"]).compatible == 1


def test_suggestions_use_unambiguous_names_shared_by_every_file():
    value = ColumnMapping()
    value.set_recordings(
        {"one": ["timestamp", "ax", "PPG"], "two": ["timestamp", "ax", "infrared"]}, {}
    )
    assert value.mapping() == {}
    assert value.suggestions() == {"time": "timestamp", "accelerometer_x": "ax"}
    value.auto_match()
    assert value.mapping() == {"timestamp": "time", "ax": "accelerometer_x"}
    assert value.choices["green"] is None
    value.choose("time", "device_clock")
    value.auto_match()
    assert value.mapping()["device_clock"] == "time"


def test_ambiguous_aliases_are_not_guessed():
    value = ColumnMapping()
    value.set_recordings({"one": ["timestamp", "device_time", "ppg", "PPG"]}, {})
    assert value.suggestions() == {}
    value.auto_match()
    assert value.mapping() == {}


@pytest.mark.parametrize(
    "saved",
    [
        {"device_clock": "time", "optical": "green"},
        {"time": "time", "unrelated": "extra_signal"},
        {"time": "original_clock", "device_clock": "time"},
        {"a": "green", "b": "green"},
        {"gyroscope_x": "gyroscope_y", "gyroscope_y": "gyroscope_x"},
    ],
)
def test_saved_mappings_keep_exact_entries_and_missing_sources(model, saved):
    model.set_mapping(saved)
    assert model.mapping() == saved
    model.set_recordings({"another": ["new_time", "new_ppg"]}, {})
    assert model.mapping() == saved
    model.set_recordings({}, {})
    assert model.mapping() == saved


def test_reset_discards_explicit_and_other_saved_mappings(model):
    model.set_mapping({"timestamp": "time", "temperature": "temperature_c"})
    model.reset()
    assert model.mapping() == {}
    assert model.extra == {}
    assert model.choices == {signal: signal for signal in SIGNALS}


def test_batch_compatibility_names_missing_signals_and_affected_files():
    value = ColumnMapping()
    value.set_recordings(
        {"one": ["timestamp", "ppg"], "two": ["timestamp", "red"]},
        {"one": "first.csv", "two": "second.csv"},
    )
    value.set_mapping({"timestamp": "time", "ppg": "green"})
    validation = value.validate(["pulse_rate"])
    assert validation.recordings == 2 and validation.compatible == 1
    assert validation.details == ("second.csv: Missing Green PPG",)
    assert value.validate([]).compatible == 2


def test_reused_source_is_reported_without_silently_replacing_another_choice(model):
    model.choose("time", "device_clock")
    model.choose("green", "device_clock")
    assert model.choices["time"] == model.choices["green"] == "device_clock"
    assert model.validate(["pulse_rate"]).compatible == 0
    with pytest.raises(ValueError, match="multiple signals: device_clock"):
        model.mapping()
    model.choose("green", "optical")
    assert model.mapping() == {"device_clock": "time", "optical": "green"}


def test_renaming_an_existing_standard_source_updates_its_implicit_assignment(model):
    model.choose("gyroscope_x", "gyroscope_y")
    assert model.choices["gyroscope_y"] is None
    assert model.target_conflicts() == {"gyroscope_x": ["sensor.csv"]}
    model.choose("gyroscope_y", "gyroscope_x")
    assert model.mapping() == {"gyroscope_y": "gyroscope_x", "gyroscope_x": "gyroscope_y"}
    assert model.validate(["gait"]).compatible == 1


def test_target_collisions_retain_saved_mapping_until_the_user_fixes_it(model):
    model.set_recordings({"one": ["time", "green", "ppg"]}, {"one": "sensor.csv"})
    model.set_mapping({"ppg": "green"})
    assert model.target_conflicts() == {"green": ["sensor.csv"]}
    assert model.validate(["pulse_rate"]).details == (
        "sensor.csv: Conflicting column names: green",
    )
    assert model.mapping() == {"ppg": "green"}
    model.choose("green", "green")
    assert model.mapping() == {}
    assert model.validate(["pulse_rate"]).compatible == 1


def test_dropdowns_emit_one_change_and_module_changes_preserve_choices(editor):
    changes = QSignalSpy(editor.changed)
    editor.set_recordings({"one": ["timestamp", "optical"]}, {})
    assert changes.count() == 0
    editor._combos["time"].setCurrentIndex(editor._combos["time"].findData("timestamp"))
    assert changes.count() == 1
    editor._combos["green"].setCurrentIndex(editor._combos["green"].findData("optical"))
    assert changes.count() == 2
    for modules in (["pulse_rate"], ["gait"], ["gait", "pulse_rate"], ["pulse_rate"]):
        editor.set_modules(modules)
        visible = {
            signal for row, signal in enumerate(SIGNALS) if not editor.table.isRowHidden(row)
        }
        assert visible == required_signals(modules)
        assert editor.mapping() == {"timestamp": "time", "optical": "green"}
    assert changes.count() == 2
    assert editor.summary.text().startswith("Compatible with 1 of 1")
    editor.optional_button.click()
    assert all(not editor.table.isRowHidden(row) for row in range(len(SIGNALS)))
    assert changes.count() == 2


def test_missing_saved_columns_remain_selectable_and_batch_details_are_visible(editor):
    editor.set_mapping({"clock": "time", "ppg": "green", "skin": "temperature"})
    editor.set_modules(["pulse_rate"])
    editor.set_recordings(
        {"one": ["clock", "ppg"], "two": ["clock", "other"]},
        {"one": "first.csv", "two": "second.csv"},
    )
    assert editor.mapping() == {"clock": "time", "ppg": "green", "skin": "temperature"}
    assert editor._statuses["green"].text() == "Missing in 1/2"
    assert "second.csv" in editor._statuses["green"].toolTip()
    assert editor.summary.text().startswith("Compatible with 1 of 2")
    editor.details_button.click()
    assert not editor.details.isHidden()
    assert "second.csv: Missing Green PPG" in editor.details.text()
    assert "skin → temperature" in editor.details.text()
    editor.set_recordings({"third": ["new_time", "new_ppg"]}, {})
    assert editor._combos["green"].currentText() == "ppg (not available)"


def test_auto_match_reset_and_inline_conflicts(editor):
    editor.set_recordings({"one": ["time", "ppg", "green", "ax"]}, {})
    editor.auto_button.click()
    assert editor.mapping() == {"ax": "accelerometer_x"}
    editor.set_mapping({"ppg": "green"})
    assert editor._statuses["green"].text() == "Name conflict"
    assert editor.summary.text().startswith("Compatible with 0 of 1")
    editor.reset_button.click()
    assert editor.mapping() == {}
    assert editor._combos["green"].currentData() == "green"
    editor._combos["time"].setCurrentIndex(editor._combos["time"].findData("ppg"))
    editor._combos["green"].setCurrentIndex(editor._combos["green"].findData("ppg"))
    assert editor._statuses["time"].text() == "Assigned twice"
    assert editor._statuses["green"].text() == "Assigned twice"
