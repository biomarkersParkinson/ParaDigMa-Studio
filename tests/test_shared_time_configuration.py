"""Time choices and file provenance agree across Data, Analyze and diagnostics."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_previews
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from paradigma_studio.exploration import source_timeline
from paradigma_studio.input_metadata import METADATA_KEY


def recording(unit="relative_ms"):
    frame = pd.DataFrame(
        {
            "timestamp": np.arange(400) * 10.0,
            "other_clock": np.arange(400) / 50,
            "epoch": pd.Timestamp("2026-10-25T08:00:00Z").timestamp() * 1000 + np.arange(400) * 10,
            "gyroscope_x": np.ones(400),
        }
    )
    frame.attrs[METADATA_KEY] = {
        "format": "tsdf",
        "units": {"timestamp": unit, "other_clock": "relative_s", "epoch": "absolute_ms"},
    }
    return frame


def badges(window, field):
    view = window._data_controller.view
    if field == "column":
        return view.data_time_channel_badge, window.mapping._file_badges["time"]
    return view.data_time_unit_badge, window._analysis_controller.view.file_badges["Time units"]


def sampling_rate(window):
    wait_for_previews(window)
    return (
        window.time_table.model()
        .frame.set_index("Statistic")
        .loc["Estimated sampling rate (Hz)", "Value"]
    )


@pytest.mark.parametrize(
    "unit",
    ["relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"],
)
def test_file_time_defaults_and_sources_are_shared(window, unit):
    window.loaded(("sensor.json", recording(unit)))
    assert (
        window.data_time_channel.currentData()
        == window.mapping.model.choices["time"]
        == "timestamp"
    )
    assert window.data_time_unit.currentText() == window.time.currentText() == unit
    for field in ("column", "unit"):
        data_badge, analysis_badge = badges(window, field)
        assert not data_badge.isHidden() and not analysis_badge.isHidden()
        assert data_badge.toolTip() == analysis_badge.toolTip()


def test_data_edits_update_analysis_diagnostics_and_the_selected_clock(window):
    frame = recording()
    original = frame.copy(deep=True)
    attrs = deepcopy(frame.attrs)
    window.loaded(("sensor.json", frame))
    assert sampling_rate(window) == pytest.approx(100)
    window.data_time_channel.setCurrentIndex(window.data_time_channel.findData("epoch"))
    assert window.mapping.model.choices["time"] == "epoch"
    assert window.time.currentText() == window.data_time_unit.currentText() == "absolute_ms"
    assert sampling_rate(window) == pytest.approx(100, rel=1e-5)
    assert all(badge.isHidden() for badge in badges(window, "column"))
    assert all(not badge.isHidden() for badge in badges(window, "unit"))
    assert pd.Timestamp(window.clock_input.text()) == pd.Timestamp("2026-10-25T08:00:00Z")
    settings = window._analysis_controller._analysis_settings(["tremor"])
    np.testing.assert_allclose(source_timeline(frame, settings), np.arange(400) / 100, atol=1e-6)
    window.data_time_unit.setCurrentText("absolute_s")
    assert window.time.currentText() == "absolute_s"
    assert sampling_rate(window) == pytest.approx(0.1)
    assert all(badge.isHidden() for badge in badges(window, "unit"))
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert frame.attrs == attrs


def test_changes_on_each_page_refresh_once_without_feedback_signals(window):
    window.loaded(("sensor.json", recording()))
    wait_for_previews(window)
    data_units = QSignalSpy(window.data_time_unit.currentTextChanged)
    analysis_units = QSignalSpy(window.time.currentTextChanged)
    data_columns = QSignalSpy(window.data_time_channel.currentIndexChanged)
    mappings = QSignalSpy(window.mapping.changed)
    window.data_time_unit.setCurrentText("relative_s")
    assert data_units.count() == analysis_units.count() == 1
    window.time.setCurrentText("difference_ms")
    assert data_units.count() == 1 and analysis_units.count() == 2
    assert window.data_time_unit.currentText() == "difference_ms"
    window.data_time_channel.setCurrentIndex(window.data_time_channel.findData("other_clock"))
    assert data_columns.count() == mappings.count() == 1
    selector = window.mapping._combos["time"]
    selector.setCurrentIndex(selector.findData("timestamp"))
    assert data_columns.count() == 1 and mappings.count() == 2
    assert window.data_time_channel.currentData() == "timestamp"


@pytest.mark.parametrize("page", ["data", "analyze"])
@pytest.mark.parametrize("field", ["column", "unit"])
def test_confirming_file_values_and_restoring_defaults_updates_both_labels(window, page, field):
    window.loaded(("sensor.json", recording()))
    if field == "column":
        control = window.data_time_channel if page == "data" else window.mapping._combos["time"]
        reset = window.mapping.default_button
    else:
        control = window.data_time_unit if page == "data" else window.time
        reset = window._analysis_controller.view.file_default_buttons["Time units"]
    before = control.currentData() or control.currentText()
    control.activated.emit(control.currentIndex())
    assert all(badge.isHidden() for badge in badges(window, field))
    reset.click()
    assert (control.currentData() or control.currentText()) == before
    assert all(not badge.isHidden() for badge in badges(window, field))


def test_batch_inspection_keeps_the_shared_column_even_when_it_is_missing(window):
    frames = {"first": recording(), "second": recording().drop(columns="epoch")}
    from paradigma_studio.inspection import inspect_recordings

    descriptions = inspect_recordings(frames, "relative_s")
    window.loaded_recordings(({key: f"{key}.json" for key in frames}, frames, descriptions))
    window.data_time_channel.setCurrentIndex(window.data_time_channel.findData("epoch"))
    window.input_recording.setCurrentIndex(1)
    wait_for_previews(window)
    assert window.data_time_channel.currentData() == window.mapping.model.choices["time"] == "epoch"
    assert window.data_time_unit.currentText() == window.time.currentText() == "absolute_ms"
    assert window.time_table.model() is None
    window.input_recording.setCurrentIndex(0)
    assert sampling_rate(window) == pytest.approx(100, rel=1e-5)
    window.data_time_channel.setCurrentIndex(window.data_time_channel.findData(None))
    assert window.mapping.model.choices["time"] is None
    assert window.mapping._combos["time"].currentData() is None
    assert window.time_table.model() is None


def test_loading_new_files_resets_edits_and_provenance_on_both_pages(window):
    window.loaded(("first.json", recording()))
    window.data_time_channel.setCurrentIndex(window.data_time_channel.findData("other_clock"))
    window.data_time_unit.setCurrentText("difference_s")
    window.loaded(
        ("next.csv", pd.DataFrame({"unknown_clock": [0.0, 1.0], "gyroscope_x": [1.0, 2.0]}))
    )
    assert window.data_time_channel.currentData() is window.mapping.model.choices["time"] is None
    assert window.data_time_unit.currentText() == window.time.currentText() == "relative_s"
    assert all(badge.isHidden() for field in ("column", "unit") for badge in badges(window, field))
    window.loaded(("last.json", recording()))
    assert window.data_time_channel.currentData() == "timestamp"
    assert window.data_time_unit.currentText() == window.time.currentText() == "relative_ms"
    assert all(
        not badge.isHidden() for field in ("column", "unit") for badge in badges(window, field)
    )


@pytest.mark.parametrize("size", [(1450, 1000), (960, 650)])
def test_time_fields_and_file_labels_stay_readable_and_reachable(window, size):
    window.loaded(("sensor.json", recording()))
    window.resize(*size)
    window.show()
    QTest.qWait(30)
    scroll = window._layout._data_page.data_overview_scroll
    assert scroll.horizontalScrollBar().maximum() == 0
    if size == (960, 650):
        assert scroll.verticalScrollBar().maximum() > 0
    for control in (
        window.data_time_channel,
        window.data_time_unit,
        *badges(window, "column")[:1],
        *badges(window, "unit")[:1],
    ):
        scroll.ensureWidgetVisible(control)
        QApplication.processEvents()
        assert control.visibleRegion().boundingRect().contains(control.rect()), (
            control.accessibleName()
        )
        assert control.parentWidget().rect().contains(control.geometry())


@pytest.mark.parametrize("field", ["column", "unit"])
def test_scrolling_over_shared_fields_scrolls_overview_without_editing_either_page(window, field):
    from test_analysis_scrolling import send_wheel

    window.loaded(("sensor.json", recording()))
    window.resize(960, 650)
    window.show()
    QTest.qWait(30)
    control = window.data_time_channel if field == "column" else window.data_time_unit
    scroll = window._layout._data_page.data_overview_scroll
    bar = scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    previous = bar.value()
    settings = window._analysis_controller._analysis_settings(["tremor"])
    send_wheel(control, upward=True)
    assert bar.value() < previous
    assert window._analysis_controller._analysis_settings(["tremor"]) == settings
    assert window.data_time_unit.currentText() == window.time.currentText()
    assert window.data_time_channel.currentData() == window.mapping.model.choices["time"]
    assert all(not badge.isHidden() for badge in badges(window, field))
