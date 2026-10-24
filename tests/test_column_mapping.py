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


def test_axis_choices_are_independent_and_survive_mapping_and_batch_changes(model):
    model.invert("gyroscope_y", True)
    model.invert("accelerometer_x", True)
    assert model.axis_inversions() == ["accelerometer_x", "gyroscope_y"]
    model.set_mapping({"clock": "time"})
    model.auto_match()
    model.set_recordings({"two": ["clock", "green"]}, {})
    assert model.axis_inversions() == ["accelerometer_x", "gyroscope_y"]
    model.invert("gyroscope_y", False)
    assert model.axis_inversions() == ["accelerometer_x"]
    with pytest.raises(ValueError, match="no axis direction"):
        model.invert("time", True)
    model.reset()
    assert model.axis_inversions() == []


def test_inversion_checkboxes_never_trigger_clock_or_raw_plot_mapping_refreshes(editor):
    from paradigma_studio.axis_mapping import IMU_COLUMNS

    changes = QSignalSpy(editor.changed)
    assert set(editor._inversions) == set(IMU_COLUMNS)
    assert [editor.table.horizontalHeaderItem(i).text() for i in range(3)] == [
        "Signal",
        "Column in your files",
        "Invert axis",
    ]
    editor.set_recordings({"one": list(SIGNALS)}, {})
    assert all(warning.isHidden() for warning in editor._warnings.values())
    for target in IMU_COLUMNS:
        editor._inversions[target].setChecked(True)
    assert editor.axis_inversions() == list(IMU_COLUMNS)
    editor.set_modules(["pulse_rate"])
    editor.auto_match()
    assert changes.count() == 1
    assert editor.axis_inversions() == list(IMU_COLUMNS)
    assert all(source.isEnabled() for source in editor._combos.values())
    assert all(
        checkbox.isEnabled() and checkbox.isChecked() for checkbox in editor._inversions.values()
    )
    editor.reset()
    assert editor.axis_inversions() == []
    assert not any(checkbox.isChecked() for checkbox in editor._inversions.values())
    assert changes.count() == 2


def test_inline_warnings_count_affected_recordings_and_escape_untrusted_headers(editor):
    editor.set_recordings({"one": ["time", "optical"]}, {"one": "<b>sensor.csv</b>"})
    editor.set_modules(["pulse_rate"])
    assert not editor._warnings["green"].isHidden()
    assert editor._warnings["accelerometer_x"].isHidden()
    editor.set_mapping({"<bad>": "green"})
    assert "&lt;bad&gt;" in editor._warnings["green"].toolTip()
    assert "sensor.csv" not in editor._warnings["green"].toolTip()
    assert "Missing in 1 of 1 recordings." in editor._warnings["green"].accessibleDescription()
    editor.set_mapping({"optical": "green"})
    assert all(warning.isHidden() for warning in editor._warnings.values())


@pytest.mark.parametrize("style", ["Fusion", "Windows"])
def test_mapping_controls_fit_their_cells_and_warning_icons_keep_dropdowns_aligned(window, style):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    original_style = app.style().objectName()
    stylesheet = window.styleSheet()
    app.setStyle(style)
    window.navigate(1)
    window.resize(1450, 920)
    editor = window.mapping
    editor.set_recordings({"one": list(SIGNALS)}, {})
    editor.set_modules(["pulse_rate"])
    editor.optional_button.click()
    selector = editor._combos["accelerometer_x"]
    selector.setCurrentIndex(selector.findData("time"))
    changes = QSignalSpy(editor.changed)
    try:
        for font_size, minimum_height in ((13, 0), (18, 0), (13, 0), (13, 44)):
            count = changes.count()
            window.setStyleSheet(stylesheet + f"\nQWidget {{ font-size: {font_size}px; }}")
            editor._combos["time"].setMinimumHeight(minimum_height)
            editor._inversions["accelerometer_x"].setMinimumHeight(minimum_height)
            QTest.qWait(30)
            assert not editor._warnings["time"].isHidden()
            assert editor._warnings["green"].isHidden()
            for row, target in enumerate(SIGNALS):
                index = editor.table.model().index(row, 1)
                cell = editor.table.cellWidget(row, 1)
                selector = editor._combos[target]
                assert cell.rect().contains(selector.geometry()), (style, font_size, target)
                assert selector.height() >= selector.sizeHint().height()
                rectangle = QRect(
                    selector.mapTo(editor.table.viewport(), QPoint()), selector.size()
                )
                assert editor.table.visualRect(index).contains(rectangle)
                assert editor.table.viewport().rect().contains(rectangle)
                if target in editor._inversions:
                    checkbox = editor._inversions[target]
                    assert checkbox.parentWidget().rect().contains(checkbox.geometry())
                badge = editor._file_badges[target]
                if not badge.isHidden():
                    assert badge.parentWidget().rect().contains(badge.geometry())
                    assert badge.width() >= badge.sizeHint().width()
            assert len({selector.width() for selector in editor._combos.values()}) == 1
            assert changes.count() == count  # Geometry changes do not change mapping choices.
    finally:
        app.setStyle(original_style)


@pytest.mark.parametrize("activation", ["mouse", "keyboard"])
def test_warning_activation_opens_current_plain_text_message_without_changing_mapping(
    editor, activation
):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    editor.set_recordings({"one": ["time", "optical"]}, {"one": "<b>sensor.csv</b>"})
    editor.set_modules(["pulse_rate"])
    editor.set_mapping({"<missing>": "green"})
    editor.show()
    QApplication.processEvents()
    changes = QSignalSpy(editor.changed)
    messages = []

    def read_dialog():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, QMessageBox):
            messages.append((dialog.windowTitle(), dialog.text(), dialog.textFormat()))
            dialog.accept()

    QTimer.singleShot(0, read_dialog)
    warning = editor._warnings["green"]
    if activation == "mouse":
        QTest.mouseClick(warning, Qt.MouseButton.LeftButton)
    else:
        warning.setFocus()
        QTest.keyClick(warning, Qt.Key.Key_Space)
    assert messages == [
        (
            "Column warning: Green PPG",
            "Missing in 1/1\nSelected column: <missing>\nMissing in 1 of 1 recordings.",
            Qt.TextFormat.PlainText,
        )
    ]
    assert changes.count() == 0
    assert editor.mapping() == {"<missing>": "green"}


def test_column_names_and_default_button_explain_current_choices(editor):
    assert not editor.default_button.isEnabled()
    assert "Open recordings" in editor.default_button.toolTip()
    editor.set_recordings({"one": ["time", "green"]}, {})
    editor.set_modules(["pulse_rate"])
    assert editor._combos["time"].currentText() == "time"
    assert editor._combos["green"].currentText() == "green"
    assert editor.default_button.isEnabled()
    assert "Restore all signal columns" in editor.default_button.toolTip()
    editor.optional_button.click()
    assert editor.default_button.isEnabled()
    assert "Axis inversion choices are kept" in editor.default_button.toolTip()
    editor.set_recordings({"one": ["time", "green", "ax"]}, {})
    assert editor.default_button.isEnabled()
    assert "Replace manual selections" in editor.default_button.toolTip()
    editor.default_button.click()
    assert editor.mapping() == {"ax": "accelerometer_x"}


def test_file_labels_follow_automatic_manual_and_saved_choices_and_one_default_restores_all(editor):
    from PySide6.QtWidgets import QPushButton

    changes = QSignalSpy(editor.changed)
    editor.set_recordings({"one": ["time", "ax", "ppg"], "two": ["time", "ax", "ppg"]}, {})
    assert changes.count() == 0
    automatic = {"time": "time", "accelerometer_x": "ax", "green": "ppg"}
    assert editor.model.choices == {target: automatic.get(target) for target in SIGNALS}
    assert {target for target, badge in editor._file_badges.items() if not badge.isHidden()} == set(
        automatic
    )
    assert "recognized alias" in editor._file_badges["green"].toolTip()
    assert "exact column name" in editor._file_badges["time"].toolTip()
    assert {control.text() for control in editor.findChildren(QPushButton)} == {
        "Default",
        "Show optional signals",
        "Show details",
    }
    editor.set_mapping({"skin": "temperature"}, signal_columns=dict.fromkeys(SIGNALS))
    editor.set_axis_inversions(["accelerometer_x", "gyroscope_z"])
    assert all(badge.isHidden() for badge in editor._file_badges.values())
    count = changes.count()
    editor.default_button.click()
    assert changes.count() == count + 1
    assert editor.model.choices == {target: automatic.get(target) for target in SIGNALS}
    assert editor.mapping() == {"skin": "temperature", "ax": "accelerometer_x", "ppg": "green"}
    assert editor.axis_inversions() == ["accelerometer_x", "gyroscope_z"]
    assert not editor._file_badges["green"].isHidden()
    selector = editor._combos["green"]
    selector.setCurrentIndex(selector.findData(None))
    assert editor._file_badges["green"].isHidden()
    assert not editor._file_badges["time"].isHidden()
    editor.set_modules(["pulse_rate"])
    assert selector.currentData() is None
    editor.default_button.click()
    assert selector.currentData() == "ppg"
    assert not editor._file_badges["green"].isHidden()


def test_selecting_the_existing_file_column_marks_it_manual_until_default(editor):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    editor.set_recordings({"one": ["time", "ppg"]}, {})
    editor.set_modules(["pulse_rate"])
    editor.show()
    changes = QSignalSpy(editor.changed)
    selector = editor._combos["green"]
    selector.showPopup()
    QTest.keyClick(selector.view(), Qt.Key.Key_Return)
    assert selector.currentData() == "ppg"
    assert changes.count() == 1
    assert editor._file_badges["green"].isHidden()
    assert "Selected manually" in editor.details.text()
    editor.default_button.click()
    assert changes.count() == 2
    assert not editor._file_badges["green"].isHidden()


def test_file_labels_require_unambiguous_headers_shared_by_all_recordings(editor):
    editor.set_recordings(
        {
            "one": ["time", "ppg", "timestamp", "device_time", "ax"],
            "two": ["timestamp", "device_time", "ax"],
        },
        {},
    )
    assert editor.model.choices == {
        target: "ax" if target == "accelerometer_x" else None for target in SIGNALS
    }
    assert {target for target, badge in editor._file_badges.items() if not badge.isHidden()} == {
        "accelerometer_x"
    }
    assert editor.default_button.isEnabled()
    assert "No unambiguous match" in editor.details.text()


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
    assert value.mapping() == {"timestamp": "time", "ax": "accelerometer_x"}
    assert value.matches_automatic()


@pytest.mark.parametrize(
    "manual",
    [
        {"green": "time", "time": "green"},
        {"device_clock": "time", "optical": "green", "ax": "accelerometer_y"},
        {"ppg": "green", "green": "green"},
        {"time": "original_clock", "device_clock": "time"},
    ],
)
def test_auto_match_replaces_manual_assignments_and_preserves_only_unrelated_legacy_entries(manual):
    value = ColumnMapping()
    value.set_recordings({"one": ["time", "green", "ax", "ppg", "skin"]}, {})
    value.set_mapping({**manual, "skin": "temperature_c"})
    value.set_axis_inversions(["accelerometer_y", "gyroscope_z"])
    assert not value.matches_automatic()
    value.auto_match()
    assert value.choices == {
        signal: signal
        if signal in {"time", "green"}
        else "ax"
        if signal == "accelerometer_x"
        else None
        for signal in SIGNALS
    }
    assert value.mapping() == {"skin": "temperature_c", "ax": "accelerometer_x"}
    assert value.axis_inversions() == ["accelerometer_y", "gyroscope_z"]
    assert value.matches_automatic()
    value.auto_match()
    assert value.matches_automatic()
    assert value.mapping() == {"skin": "temperature_c", "ax": "accelerometer_x"}


def test_auto_match_clears_manual_choices_without_guessing_ambiguous_or_file_specific_names(editor):
    editor.set_recordings(
        {
            "one": ["timestamp", "device_time", "ppg", "optical"],
            "two": ["timestamp", "device_time", "optical"],
        },
        {},
    )
    editor.set_mapping({"timestamp": "time", "optical": "green"})
    assert editor.default_button.isEnabled()
    editor.default_button.click()
    assert editor.model.choices == dict.fromkeys(SIGNALS)
    assert editor.mapping() == {}
    assert editor.default_button.isEnabled()
    assert not editor._warnings["time"].isHidden()
    assert not editor._warnings["accelerometer_x"].isHidden()


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


def test_legacy_null_mapping_restores_standard_matching(model):
    model.set_mapping({"device_time": "time"})
    model.set_mapping(None)
    assert model.mapping() == {}
    assert model.choices == {signal: signal for signal in SIGNALS}


def test_batch_compatibility_names_missing_signals_and_counts_affected_recordings():
    value = ColumnMapping()
    value.set_recordings(
        {"one": ["timestamp", "ppg"], "two": ["timestamp", "red"]},
        {"one": "first.csv", "two": "second.csv"},
    )
    value.set_mapping({"timestamp": "time", "ppg": "green"})
    validation = value.validate(["pulse_rate"])
    assert validation.recordings == 2 and validation.compatible == 1
    assert validation.details == ("Missing Green PPG (1 of 2 recordings)",)
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
    assert model.target_conflicts() == {}
    assert model.validate(["gait"]).details == ("Missing Gyroscope Y",)
    model.choose("gyroscope_y", "gyroscope_x")
    assert model.mapping() == {"gyroscope_y": "gyroscope_x", "gyroscope_x": "gyroscope_y"}
    assert model.validate(["gait"]).compatible == 1


def test_target_collisions_retain_saved_mapping_until_the_user_fixes_it(model):
    model.set_recordings({"one": ["time", "green", "ppg"]}, {"one": "sensor.csv"})
    model.set_mapping({"ppg": "green", "green": "green"})
    assert model.target_conflicts() == {"green": ["sensor.csv"]}
    assert model.validate(["pulse_rate"]).details == ("Conflicting column names: green",)
    assert model.mapping() == {"ppg": "green", "green": "green"}
    with pytest.raises(ValueError, match="Multiple saved columns"):
        model.signal_columns()
    model.choose("green", "green")
    assert model.mapping() == {}
    assert model.validate(["pulse_rate"]).compatible == 1


def test_identical_batch_mapping_issues_appear_once_without_recording_names(editor):
    schemas = {f"recording_{index}": ["time", "green"] for index in range(7)}
    editor.set_recordings(schemas, {key: f"{key}.csv" for key in schemas})
    editor.set_modules(["gait"])
    expected = (
        "Missing Accelerometer X, Accelerometer Y, Accelerometer Z, "
        "Gyroscope X, Gyroscope Y, Gyroscope Z"
    )
    assert editor.summary.text().startswith("Compatible with 0 of 7 recordings")
    issues, provenance = editor.details.text().split("\n\nColumn selections:\n")
    assert issues == expected
    assert "Time: time (From file: exact column name)" in provenance
    assert "recording_" not in editor.details.text()
    assert editor.details.isHidden()
    editor.details_button.click()
    assert not editor.details.isHidden()
    assert editor.details_button.text() == "Hide details"
    editor.details_button.click()
    assert editor.details.isHidden()
    assert editor.details_button.text() == "Show details"
    editor.set_modules(["pulse_rate"])
    assert editor.summary.text().startswith("Compatible with 7 of 7 recordings")
    assert "Missing" not in editor.details.text()
    assert "Green PPG: green (From file: exact column name)" in editor.details.text()
    assert not editor.details_button.isHidden()


def test_mixed_batch_mapping_issues_are_grouped_by_affected_count_without_losing_compatibility():
    model = ColumnMapping()
    model.set_recordings(
        {
            "one": ["time", "green", "ppg"],
            "two": ["time", "ppg"],
            "three": ["time"],
            "four": ["temperature"],
        },
        {},
    )
    # The first recording has a name conflict, the third lacks PPG, and the
    # fourth lacks time and PPG. The second is the only compatible recording.
    model.set_mapping({"ppg": "green", "green": "green"})
    validation = model.validate(["pulse_rate"])
    assert validation.recordings == 4 and validation.compatible == 1
    assert validation.details == (
        "Missing Green PPG (2 of 4 recordings)",
        "Missing Time (1 of 4 recordings)",
        "Conflicting column names: green (1 of 4 recordings)",
    )


def test_dropdowns_emit_one_change_and_module_changes_preserve_choices(editor):
    changes = QSignalSpy(editor.changed)
    editor.set_recordings({"one": ["timestamp", "optical"]}, {})
    assert changes.count() == 0
    editor._combos["time"].setCurrentIndex(editor._combos["time"].findData("timestamp"))
    editor._combos["time"].activated.emit(editor._combos["time"].currentIndex())
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


def test_not_included_clears_a_mistaken_ppg_assignment_and_restores_the_source_signal(editor):
    columns = list(SIGNALS.keys() - {"green"})
    editor.set_recordings({"one": columns, "two": columns}, {})
    editor.set_modules(["gait", "pulse_rate"])
    selector = editor._combos["green"]
    changes = QSignalSpy(editor.changed)
    assert selector.currentText() == "Not included"
    selector.setCurrentIndex(selector.findData("accelerometer_x"))
    assert editor.mapping() == {"accelerometer_x": "green"}
    assert editor.model.choices["accelerometer_x"] is None
    selector.setCurrentIndex(selector.findText("Not included"))
    assert selector.currentData() is None
    assert selector.currentText() == "Not included"
    assert editor.mapping() == {}
    assert editor.model.choices["accelerometer_x"] == "accelerometer_x"
    assert editor.model.validate(["gait"]).compatible == 2
    assert editor.model.validate(["pulse_rate"]).compatible == 0
    assert not editor._warnings["green"].isHidden()
    assert editor.default_button.isEnabled()
    assert changes.count() == 2
    editor.set_modules(["gait"])
    assert editor._warnings["green"].isHidden()
    assert editor.model.choices["green"] is None
    editor.set_recordings({"three": list(SIGNALS)}, {})
    assert selector.currentData() is None
    assert selector.currentText() == "Not included"
    assert editor.model.choices["green"] is None
    assert editor.model.validate(["pulse_rate"]).compatible == 0
    assert editor.mapping() == {}
    assert changes.count() == 2


def test_not_included_clears_a_missing_saved_assignment_and_auto_match_can_restore_an_alias(editor):
    editor.set_recordings({"one": ["time", "ppg"]}, {})
    editor.set_modules(["pulse_rate"])
    editor.set_mapping({"missing_optical": "green", "skin": "temperature"})
    selector = editor._combos["green"]
    assert selector.currentIndex() == -1
    changes = QSignalSpy(editor.changed)
    selector.setCurrentIndex(selector.findText("Not included"))
    assert selector.currentText() == "Not included"
    assert editor.mapping() == {"skin": "temperature"}
    assert "missing_optical" not in editor._warnings["green"].accessibleDescription()
    assert editor.default_button.isEnabled()
    assert changes.count() == 1
    editor.default_button.click()
    assert selector.currentData() == "ppg"
    assert editor.mapping() == {"skin": "temperature", "ppg": "green"}
    assert editor._warnings["green"].isHidden()
    assert editor.default_button.isEnabled()
    assert changes.count() == 2


def test_missing_saved_columns_stay_in_settings_without_becoming_dropdown_options(editor):
    editor.set_mapping({"clock": "time", "ppg": "green", "skin": "temperature"})
    editor.set_modules(["pulse_rate"])
    editor.set_recordings(
        {"one": ["clock", "ppg"], "two": ["clock", "other"]},
        {"one": "first.csv", "two": "second.csv"},
    )
    assert editor.mapping() == {"clock": "time", "ppg": "green", "skin": "temperature"}
    assert not editor._warnings["green"].isHidden()
    assert "Missing in 1/2" in editor._warnings["green"].toolTip()
    assert "Missing in 1 of 2 recordings." in editor._warnings["green"].accessibleDescription()
    assert "second.csv" not in editor._warnings["green"].toolTip()
    assert editor.summary.text().startswith("Compatible with 1 of 2")
    editor.details_button.click()
    assert not editor.details.isHidden()
    assert "Missing Green PPG (1 of 2 recordings)" in editor.details.text()
    assert "second.csv" not in editor.details.text()
    assert "skin → temperature" in editor.details.text()
    editor.set_recordings({"third": ["new_time", "new_ppg"]}, {})
    selector = editor._combos["green"]
    assert selector.currentIndex() == -1
    assert selector.placeholderText() == "Select a column…"
    assert selector.findData("ppg") == -1
    assert "Selected column: ppg" in editor._warnings["green"].accessibleDescription()
    assert editor.mapping() == {"clock": "time", "ppg": "green", "skin": "temperature"}
    changes = QSignalSpy(editor.changed)
    selector.setCurrentIndex(selector.findData("new_ppg"))
    assert editor.mapping() == {"clock": "time", "new_ppg": "green", "skin": "temperature"}
    assert editor._warnings["green"].isHidden()
    assert changes.count() == 1


def test_dropdowns_offer_real_columns_and_an_explicit_not_included_option(editor):
    assert all(
        source.count() == 1 and source.itemText(0) == "Not included" and source.itemData(0) is None
        for source in editor._combos.values()
    )
    editor.set_recordings({"one": ["time", "green"], "two": ["time", "optical"]}, {})
    editor.set_mapping({"missing_clock": "time", "missing_ppg": "green"})
    for source in editor._combos.values():
        expected = {
            "time",
            "green",
            "optical",
        }
        expected.add(None)
        assert source.itemText(0) == "Not included" and source.itemData(0) is None
        assert {source.itemData(index) for index in range(source.count())} == expected
        assert all(
            source.itemText(index) == source.itemData(index)
            for index in range(source.count())
            if source.itemData(index) is not None
        )
    assert editor._combos["time"].currentIndex() == -1
    assert editor._combos["green"].currentIndex() == -1
    assert editor.mapping() == {"missing_clock": "time", "missing_ppg": "green"}
    editor.set_recordings({}, {})
    assert all(
        source.count() == 1 and source.itemText(0) == "Not included" and source.itemData(0) is None
        for source in editor._combos.values()
    )
    assert editor.mapping() == {"missing_clock": "time", "missing_ppg": "green"}


def test_default_restores_file_matches_and_clears_inline_conflicts(editor):
    editor.set_recordings({"one": ["time", "ppg", "green", "ax"]}, {})
    editor.default_button.click()
    assert editor.mapping() == {"ax": "accelerometer_x"}
    editor.set_mapping({"ppg": "green", "green": "green"})
    assert not editor._warnings["green"].isHidden()
    assert "Name conflict" in editor._warnings["green"].toolTip()
    assert "Multiple columns become this signal in 1 of 1 recordings." in (
        editor._warnings["green"].accessibleDescription()
    )
    assert editor.summary.text().startswith("Compatible with 0 of 1")
    editor.default_button.click()
    assert editor.mapping() == {"ax": "accelerometer_x"}
    assert editor._combos["green"].currentData() == "green"
    editor._combos["time"].setCurrentIndex(editor._combos["time"].findData("ppg"))
    editor._combos["green"].setCurrentIndex(editor._combos["green"].findData("ppg"))
    for target in ("time", "green"):
        assert not editor._warnings[target].isHidden()
        assert "Assigned twice" in editor._warnings[target].toolTip()


def test_auto_match_includes_optional_signals_and_reports_headers_as_plain_text(editor):
    editor.set_recordings({"one": ["timestamp", "ppg", "ax"]}, {"one": "<b>sensor.csv</b>"})
    editor.set_modules(["pulse_rate"])
    editor.default_button.click()
    automatic = {"timestamp": "time", "ppg": "green", "ax": "accelerometer_x"}
    assert editor.mapping() == automatic
    assert editor.default_button.isEnabled()
    editor.optional_button.click()
    assert editor.default_button.isEnabled()
    selector = editor._combos["time"]
    selector.setCurrentIndex(selector.findData("ppg"))
    assert editor.default_button.isEnabled()
    changes = QSignalSpy(editor.changed)
    editor.default_button.click()
    assert editor.mapping() == automatic
    assert changes.count() == 1
    assert editor.default_button.isEnabled()
    editor.set_modules(["gait"])
    issues, provenance = editor.details.text().split("\n\nColumn selections:\n")
    assert issues == (
        "Missing Accelerometer Y, Accelerometer Z, Gyroscope X, Gyroscope Y, Gyroscope Z"
    )
    assert "From file: recognized alias" in provenance
    from PySide6.QtCore import Qt

    assert editor.details.textFormat() == Qt.TextFormat.PlainText


def test_saved_result_mapping_round_trip_restores_every_choice_and_legacy_entry(window, tmp_path):
    from paradigma_studio.history import load_result_export, new_run
    from paradigma_studio.serialization import export_results

    saved = {"clock": "time", "ppg": "green", "auxiliary": "temperature_c"}
    path = tmp_path / "saved.json"
    export_results(
        path,
        {"errors": []},
        {
            "settings": {
                "pipelines": ["pulse_rate"],
                "column_mapping": saved,
                "axis_inversions": ["accelerometer_x", "gyroscope_z"],
                "device_orientation": ["x", "y", "z"],
            }
        },
    )
    original_bytes = path.read_bytes()
    provenance, _results = load_result_export(path)
    record = new_run("sensor.csv", provenance["settings"])
    window._run_state.selected_run = record
    window.use_run_parameters()
    assert window.mapping.mapping() == saved
    assert window.mapping.model.choices["time"] == "clock"
    assert window.mapping.model.choices["green"] == "ppg"
    assert window.mapping._combos["time"].currentIndex() == -1
    assert window.mapping._combos["green"].currentIndex() == -1
    assert window.mapping.axis_inversions() == ["accelerometer_x", "gyroscope_z"]
    assert "auxiliary → temperature_c" in window.mapping.details.text()
    assert window._analysis_controller._analysis_settings(["pulse_rate"])["column_mapping"] == saved
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("aliased", [False, True])
def test_restoring_legacy_signed_run_preserves_official_sensor_values(
    window, tmp_path, prepared, aliased
):
    import numpy as np
    import pandas as pd
    from paradigma.prepare_data import correct_watch_orientation

    from paradigma_studio import core
    from paradigma_studio.axis_mapping import IMU_COLUMNS
    from paradigma_studio.history import load_result_export, new_run
    from paradigma_studio.serialization import export_results

    source = pd.DataFrame(
        {
            "time": np.arange(200) / 100,
            **{
                channel: np.arange(200, dtype=float) + index
                for index, channel in enumerate(IMU_COLUMNS)
            },
        }
    )
    names = {column: f"sensor_{column}" for column in source if aliased}
    source = source.rename(columns=names)
    mapping = {renamed: column for column, renamed in names.items()}
    legacy_settings = {
        "pipelines": ["gait"],
        "column_mapping": mapping,
        "device_orientation": ["-y", "z", "-x"],
        "skip_preparation": prepared,
    }
    path = tmp_path / "legacy.json"
    export_results(path, {"errors": []}, {"settings": legacy_settings})
    before = path.read_bytes()
    window.loaded(("sensor.csv", source))
    provenance, _ = load_result_export(path)
    window._run_state.selected_run = new_run("sensor.csv", provenance["settings"])
    window.use_run_parameters()
    settings = window._analysis_controller._analysis_settings(["gait"])
    assert settings["device_orientation"] == ["x", "y", "z"]
    assert settings["axis_inversions"] == (
        [] if prepared else ["accelerometer_x", "accelerometer_z", "gyroscope_x", "gyroscope_z"]
    )
    actual, exclusion, count = core._prepare_recording(
        source, ["gait"], settings["column_mapping"], None, False, settings
    )
    expected = source.rename(columns=mapping)
    if not prepared:
        expected = correct_watch_orientation(expected, ["-y", "z", "-x"])
    pd.testing.assert_frame_equal(actual, expected, check_like=True, check_exact=True)
    assert exclusion is None and count == len(source)
    assert path.read_bytes() == before


def test_batch_schema_installation_never_reads_or_counts_samples(window):
    class HeadersOnly:
        columns = ["time", "green"]

        def __getitem__(self, key):
            raise AssertionError("Mapping must not access samples")

        def __len__(self):
            raise AssertionError("Mapping must not count samples")

    inputs = window._input_state
    inputs.recordings = {f"recording_{index}": HeadersOnly() for index in range(7)}
    inputs.sources = {key: f"{key}.bin" for key in inputs.recordings}
    window._data_controller._supply_mapping_schemas()
    window.mapping.set_modules(["pulse_rate"])
    assert window.mapping.mapping() == {}
    assert window.mapping.summary.text().startswith("Compatible with 7 of 7")
    inputs.recordings = {}


def test_batch_choices_survive_inspection_and_module_changes_but_reset_for_new_load(
    window, monkeypatch
):
    import pandas as pd
    from conftest import wait_for_previews

    from paradigma_studio.inspection import inspect_recording

    frames = {
        f"recording_{index:03}": pd.DataFrame({"clock": [0.0, 1.0], "optical": [2.0, 3.0]})
        for index in (1, 2)
    }
    originals = {key: frame.copy(deep=True) for key, frame in frames.items()}
    sources = {key: f"{key}.csv" for key in frames}
    descriptions = {key: inspect_recording(frame, "relative_s") for key, frame in frames.items()}
    window.loaded_recordings((sources, frames, descriptions))
    window.set_modules(["pulse_rate"])
    for target, column in (("time", "clock"), ("green", "optical")):
        selector = window.mapping._combos[target]
        selector.setCurrentIndex(selector.findData(column))
    selected = {"clock": "time", "optical": "green"}
    assert window.mapping.mapping() == selected
    assert window.mapping.summary.text().startswith("Compatible with 2 of 2")
    with monkeypatch.context() as patch:

        def unexpected(*args):
            raise AssertionError("Inspecting a recording must reuse the installed batch schemas")

        patch.setattr(window.mapping, "set_recordings", unexpected)
        window.input_recording.setCurrentIndex(1)
        window.set_modules(["gait"])
        window.set_modules(["pulse_rate"])
        assert window.mapping.mapping() == selected
    for key, frame in frames.items():
        pd.testing.assert_frame_equal(frame, originals[key], check_exact=True)
    window.loaded(("other.csv", pd.DataFrame({"time": [0.0, 1.0], "green": [1.0, 2.0]})))
    wait_for_previews(window)
    assert window.mapping.mapping() == {}
    assert window.mapping._combos["time"].currentData() == "time"
    assert window.mapping._combos["time"].findData("clock") == -1
    assert window.mapping._warnings["time"].isHidden()
    assert window.selected_modules() == ["gait"]
    window.set_modules(["pulse_rate"])
    assert window.mapping.summary.text().startswith("Compatible with 1 of 1")


def test_reused_dropdown_source_reports_a_failure_before_a_job_starts(window):
    from dataclasses import replace

    import pandas as pd

    window.loaded(("sensor.csv", pd.DataFrame({"clock": [0.0, 1.0], "optical": [1.0, 2.0]})))
    window.set_modules(["pulse_rate"])
    failures = []
    controller = window._analysis_controller
    controller.callbacks = replace(controller.callbacks, failure=failures.append)
    for target in ("time", "green"):
        selector = window.mapping._combos[target]
        selector.setCurrentIndex(selector.findData("clock"))
    window.run_analysis()
    assert failures == ["Columns assigned to multiple signals: clock"]
    assert window._job_state.worker is None
    assert window._run_state.runs == []


@pytest.mark.scientific
@pytest.mark.parametrize("pipeline", ["gait", "tremor", "pulse_rate"])
def test_dropdown_mapping_matches_independent_official_preparation_and_outputs(
    window, tmp_path, pipeline
):
    import numpy as np
    import pandas as pd
    from paradigma.config import PulseRateConfig
    from paradigma.prepare_data import correct_watch_orientation, prepare_time_column
    from test_scientific_equivalence import DATA, compare_workflows, official_preparation

    recorded = pd.read_parquet(
        DATA / ("prepared_ppg.parquet" if pipeline == "pulse_rate" else "prepared_imu.parquet")
    )
    names = {column: f"sensor_{column}" for column in recorded}
    if pipeline != "pulse_rate":
        names["accelerometer_x"], names["accelerometer_y"] = (
            names["accelerometer_y"],
            names["accelerometer_x"],
        )
    frame = recorded.rename(columns=names)
    inversions = (
        ["accelerometer_x", "gyroscope_y"] if pipeline != "pulse_rate" else ["accelerometer_z"]
    )
    for target in inversions:
        if target in names:
            frame[names[target]] *= -1
    reference_frame = frame.copy(deep=True)
    # Existing standard names must not override the visible manual choices.
    # These invalid decoys would fail preparation or change the scientific output.
    frame = frame.assign(**dict.fromkeys(SIGNALS, np.nan))
    expected_mapping = {source: target for target, source in names.items()}
    window.loaded(("sensor.csv", frame))
    window.set_modules([pipeline])
    assert window.mapping.model.choices["time"] == "time"
    for target in SIGNALS.keys() - names.keys():
        selector = window.mapping._combos[target]
        selector.setCurrentIndex(selector.findData(None))
    for target, source in names.items():
        selector = window.mapping._combos[target]
        selector.setCurrentIndex(selector.findData(source))
    window.mapping.set_axis_inversions(inversions)
    settings = window._analysis_controller._analysis_settings([pipeline])
    assert settings["column_mapping"] == expected_mapping
    assert settings["device_orientation"] == ["x", "y", "z"]
    assert settings["axis_inversions"] == inversions
    extra = {
        "watch_side": settings["watch_side"],
        "axis_inversions": inversions,
        "signal_columns": settings["signal_columns"],
    }
    if pipeline == "pulse_rate":
        reference = prepare_time_column(
            reference_frame.rename(columns=expected_mapping), input_unit_type="relative_s"
        )
        extra["pulse_rate_config"] = PulseRateConfig(
            ppg_sampling_frequency=100, min_window_length_s=10
        )
    else:
        reference = official_preparation(reference_frame, column_mapping=expected_mapping)
    for sensor in ("accelerometer", "gyroscope"):
        if all(f"{sensor}_{axis}" in reference for axis in "xyz"):
            axes = [("-" if f"{sensor}_{axis}" in inversions else "") + axis for axis in "xyz"]
            reference = correct_watch_orientation(reference, axes, sensor=sensor)
    actual, expected, _stages = compare_workflows(
        frame, reference, [pipeline], tmp_path, column_mapping=settings["column_mapping"], **extra
    )
    classified = actual["classifications"][pipeline]
    if pipeline == "gait":
        classified = classified["detection"]
    assert not classified.empty
    assert actual["aggregations"] == expected["aggregations"]
