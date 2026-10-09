"""Sensor drill-down shares Data's multi-channel workspace without page scrolling."""

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from conftest import wait_for_previews
from paradigma_desktop.app import MainWindow


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = MainWindow(tmp_path)
    time = np.arange(1001) / 100
    frame = pd.DataFrame(
        {
            "time": time,
            **{
                f"{sensor}_{axis}": np.sin(time * (i + 1)) + i
                for i, (sensor, axis) in enumerate(
                    (sensor, axis) for sensor in ("accelerometer", "gyroscope") for axis in "xyz"
                )
            },
        }
    )
    widget.loaded(("subject.csv", frame))
    widget.provenance = {"source": "subject.csv", "settings": {"skip_preparation": True}}
    widget.analyzed(
        {
            "quantifications": {
                "tremor": pd.DataFrame(
                    {"time": [2.0, 4.0, 8.0], "tremor_power": [10.0, 20.0, 30.0]}
                )
            }
        }
    )
    widget.result_table.setCurrentIndex(widget.result_table.model().index(0, 0))
    widget.inspect_sensor_context()
    yield widget
    wait_for_previews(widget)
    widget.close()
    app.processEvents()


def test_context_overlays_selected_channels_with_data_colors_and_original_values(window):
    source = window.frame.copy(deep=True)
    context = window.sensor_frame.copy(deep=True)
    channels = ["accelerometer_x", "gyroscope_y", "gyroscope_z"]
    window.set_sensor_channels(channels)
    axes = window.sensor_figure.axes[0]
    assert len(window.sensor_figure.axes) == 1
    assert [line.get_label() for line in axes.lines] == channels
    assert len({line.get_color() for line in axes.lines}) == len(channels)
    assert [text.get_text() for text in axes.get_legend().get_texts()] == channels
    for line in axes.lines:
        np.testing.assert_array_equal(line.get_xdata(), window.sensor_times)
        np.testing.assert_array_equal(line.get_ydata(), context[line.get_label()])
        assert line.get_color() == window._channel_colors[line.get_label()]
    assert window.selected_input_channels() == ["accelerometer_x"]
    pd.testing.assert_frame_equal(window.sensor_table.model().frame, context)
    pd.testing.assert_frame_equal(window.frame, source)


def test_context_checkboxes_and_bulk_actions_preserve_selection_across_drilldowns(window):
    window.set_sensor_channels(["gyroscope_x", "gyroscope_z"])
    window.sensor_channels.item(0).setCheckState(Qt.Checked)
    assert window.selected_sensor_channels() == ["accelerometer_x", "gyroscope_x", "gyroscope_z"]
    window.result_table.setCurrentIndex(window.result_table.model().index(1, 0))
    window.inspect_sensor_context()
    assert window.selected_sensor_channels() == ["accelerometer_x", "gyroscope_x", "gyroscope_z"]
    actions = {
        button.text(): button
        for button in window.sensor_channels.parentWidget().findChildren(QPushButton)
    }
    actions["Select all"].click()
    assert len(window.sensor_figure.axes[0].lines) == 6
    actions["Clear"].click()
    assert not window.sensor_figure.axes[0].lines
    assert window.sensor_figure.axes[0].texts[0].get_text() == "Select sensor channels"
    window.inspect_sensor_context()
    assert window.selected_sensor_channels() == []


def test_context_excludes_mapped_time_and_complex_channels_and_keeps_calendar_alignment(window):
    frame = window.sensor_frame.copy()
    frame["source_clock"] = frame.pop("time")
    frame["complex_signal"] = 1j
    window.sensor_frame = frame
    window.provenance["settings"]["column_mapping"] = {"source_clock": "time"}
    window.display_clock = {"origin": "2026-10-09T13:00:00+02:00", "timezone": "Europe/Amsterdam"}
    window.populate_sensor_channels()
    available = [
        window.sensor_channels.item(i).data(Qt.UserRole)
        for i in range(window.sensor_channels.count())
    ]
    assert "source_clock" not in available and "complex_signal" not in available
    window.set_sensor_channels(["gyroscope_x", "gyroscope_y"])
    expected = dates.date2num(
        pd.Timestamp(window.display_clock["origin"])
        + pd.to_timedelta(window.sensor_times, unit="s")
    )
    for line in window.sensor_figure.axes[0].lines:
        np.testing.assert_allclose(dates.date2num(line.get_xdata()), expected)
    assert window.sensor_figure.axes[0].get_xlabel() == "Recording date/time"


@pytest.mark.parametrize("size", [(960, 650), (1450, 920)])
@pytest.mark.parametrize("font_size", [13, 18])
def test_full_context_graph_and_left_channel_list_fit_without_page_scrolling(
    window, size, font_size
):
    if font_size != 13:
        window.setStyleSheet(window.styleSheet() + f"\nQWidget {{ font-size: {font_size}px; }}")
    window.navigate(2)
    window.resize(*size)
    window.show()
    window.set_sensor_channels(["accelerometer_x", "gyroscope_x", "gyroscope_z"])
    QTest.qWait(40)
    scroll = window._result_view_scrolls[window.sensor_tab_index]
    assert scroll.verticalScrollBar().maximum() == 0
    assert scroll.horizontalScrollBar().maximum() == 0
    assert window.sensor_canvas.visibleRegion().boundingRect().contains(window.sensor_canvas.rect())
    assert window.sensor_canvas.height() >= 100
    left = window.sensor_channels.mapTo(window.sensor_tabs, QPoint(0, 0)).x()
    right = window.sensor_canvas.mapTo(window.sensor_tabs, QPoint(0, 0)).x()
    assert left + window.sensor_channels.width() <= right
    # An enlarged graph still fits after switching between samples and signals.
    window.sensor_tabs.setCurrentIndex(1)
    window.sensor_tabs.setCurrentIndex(0)
    QTest.qWait(20)
    assert scroll.verticalScrollBar().maximum() == 0
    assert window.sensor_canvas.visibleRegion().boundingRect().contains(window.sensor_canvas.rect())
