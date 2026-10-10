"""Sensor drill-down shares Data's multi-channel workspace without page scrolling."""

import numpy as np
import pandas as pd
import pytest
import warnings
from matplotlib import dates
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from conftest import wait_for_previews
from paradigma_desktop.app import MainWindow


def signal_lines(axes):
    """Original signals, excluding the separately checked time-selection overlay."""
    return [line for line in axes.lines if line.get_gid() is None]


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


def test_context_groups_modalities_with_data_colors_and_original_values(window):
    source = window.frame.copy(deep=True)
    context = window.sensor_frame.copy(deep=True)
    channels = ["accelerometer_x", "gyroscope_y", "gyroscope_z"]
    window.set_sensor_channels(channels)
    accelerometer, gyroscope = window.sensor_figure.axes
    assert [line.get_label() for line in signal_lines(accelerometer)] == channels[:1]
    assert [line.get_label() for line in signal_lines(gyroscope)] == channels[1:]
    lines = [line for ax in window.sensor_figure.axes for line in signal_lines(ax)]
    assert len({line.get_color() for line in lines}) == len(channels)
    assert [text.get_text() for text in gyroscope.get_legend().get_texts()] == channels[1:]
    for line in lines:
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
    assert len(window.sensor_figure.axes) == 2
    assert [len(signal_lines(ax)) for ax in window.sensor_figure.axes] == [3, 3]
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
    for line in signal_lines(window.sensor_figure.axes[0]):
        np.testing.assert_allclose(dates.date2num(line.get_xdata()), expected)
    assert window.sensor_figure.axes[0].get_xlabel() == "Recording date/time"


@pytest.mark.parametrize("size", [(960, 650), (1450, 920)])
@pytest.mark.parametrize("font_size", [13, 18])
@pytest.mark.parametrize("native_button_width", [0, 200])
def test_full_context_graph_and_left_channel_list_fit_without_page_scrolling(
    window, size, font_size, native_button_width
):
    if font_size != 13:
        window.setStyleSheet(window.styleSheet() + f"\nQWidget {{ font-size: {font_size}px; }}")
    if native_button_width:
        # Wide native Windows actions left a narrow note that consumed nearly
        # the whole page, shrinking the canvas to a few dozen pixels.
        for control in window.sensor_panel.findChildren(QPushButton):
            control.setMinimumWidth(native_button_width)
            control.setMinimumHeight(44)
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
    assert window.sensor_note.height() >= window.sensor_note.heightForWidth(
        window.sensor_note.width()
    )
    for control in window.sensor_panel.findChildren(QPushButton):
        assert control.visibleRegion().boundingRect().contains(control.rect())
    with warnings.catch_warnings(record=True) as caught:
        window.sensor_canvas.draw()
    assert not [warning for warning in caught if "constrained_layout" in str(warning.message)]
    left = window.sensor_channels.mapTo(window.sensor_tabs, QPoint(0, 0)).x()
    right = window.sensor_canvas.mapTo(window.sensor_tabs, QPoint(0, 0)).x()
    assert left + window.sensor_channels.width() <= right
    # An enlarged graph still fits after switching between samples and signals.
    window.sensor_tabs.setCurrentIndex(1)
    window.sensor_tabs.setCurrentIndex(0)
    QTest.qWait(20)
    assert scroll.verticalScrollBar().maximum() == 0
    assert window.sensor_canvas.visibleRegion().boundingRect().contains(window.sensor_canvas.rect())
    # Resizing must both wrap and unwrap the note/actions without cached native
    # size hints shrinking the plot or leaving the caption clipped.
    other_size = (1450, 920) if size == (960, 650) else (960, 650)
    for resized in (other_size, size):
        window.resize(*resized)
        QTest.qWait(30)
        assert scroll.verticalScrollBar().maximum() == 0
        assert scroll.horizontalScrollBar().maximum() == 0
        assert window.sensor_canvas.height() >= 100
        assert (
            window.sensor_canvas.visibleRegion()
            .boundingRect()
            .contains(window.sensor_canvas.rect())
        )
        assert window.sensor_note.height() >= window.sensor_note.heightForWidth(
            window.sensor_note.width()
        )


def open_long_context(window, *, gap=False, gait=False):
    time = np.arange(8001) / 100
    frame = pd.DataFrame({"time": time, "gyroscope_x": np.sin(time), "gyroscope_z": np.cos(time)})
    if gap:
        frame = frame.loc[(frame.time < 40) | (frame.time > 60)].copy()
    window.loaded(("subject.csv", frame))
    window.provenance = {"source": "subject.csv", "settings": {"skip_preparation": True}}
    result = {"quantifications": {"tremor": pd.DataFrame({"time": [30.0], "tremor_power": [2.0]})}}
    if gait:
        result = {
            "quantifications": {
                "gait": {
                    "unfiltered": pd.DataFrame(
                        {"gait_segment_nr": [1, 1], "range_of_motion": [10.0, 20.0]}
                    )
                }
            },
            "metadata": {
                "gait": {
                    "unfiltered": {
                        "per_segment": {1: {"start_s": 30.0, "end_s": 36.0, "duration_s": 6.0}}
                    }
                }
            },
        }
    window.analyzed(result)
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    window.inspect_sensor_context()
    window.set_sensor_channels(["gyroscope_x", "gyroscope_z"])
    return frame


def test_context_navigation_keeps_channels_original_samples_and_recording_boundaries(window):
    frame = open_long_context(window)
    original = frame.copy(deep=True)
    pd.testing.assert_frame_equal(window.sensor_frame, frame.loc[frame.time.between(20, 40)])
    assert window.sensor_earlier.isEnabled() and window.sensor_later.isEnabled()
    window.sensor_later.click()
    pd.testing.assert_frame_equal(window.sensor_frame, frame.loc[frame.time.between(40, 60)])
    assert not any(
        line.get_gid() == "selected-result-time" for line in window.sensor_figure.axes[0].lines
    )
    window.sensor_later.click()
    pd.testing.assert_frame_equal(window.sensor_frame, frame.loc[frame.time.between(60, 80)])
    assert not window.sensor_later.isEnabled()
    for start in (40, 20, 0):
        window.sensor_earlier.click()
        pd.testing.assert_frame_equal(
            window.sensor_frame, frame.loc[frame.time.between(start, start + 20)]
        )
        assert window.selected_sensor_channels() == ["gyroscope_x", "gyroscope_z"]
    assert not window.sensor_earlier.isEnabled()
    assert window._sensor_context.selected_time == 30
    pd.testing.assert_frame_equal(frame, original)
    window.clear_results()
    assert window._sensor_context is None
    assert not window.sensor_earlier.isEnabled() and not window.sensor_later.isEnabled()


def test_context_navigation_crosses_gaps_without_creating_original_samples(window):
    frame = open_long_context(window, gap=True)
    window.sensor_later.click()
    assert window.sensor_frame.empty
    assert window.sensor_earlier.isEnabled() and window.sensor_later.isEnabled()
    window.sensor_later.click()
    pd.testing.assert_frame_equal(window.sensor_frame, frame.loc[frame.time.between(60, 80)])
    window.sensor_earlier.click()
    window.sensor_earlier.click()
    pd.testing.assert_frame_equal(window.sensor_frame, frame.loc[frame.time.between(20, 40)])


def test_gait_context_begins_at_full_segment_and_can_move_beyond_its_bounds(window):
    frame = open_long_context(window, gait=True)
    pd.testing.assert_frame_equal(
        window.sensor_frame, frame.loc[(frame.time >= 30) & (frame.time < 36)]
    )
    assert "using toolbox metadata" in window.sensor_note.text()
    selected = window._sensor_context.selected_time
    window.sensor_later.click()
    pd.testing.assert_frame_equal(
        window.sensor_frame, frame.loc[(frame.time >= 36) & (frame.time < 42)]
    )
    assert window._sensor_context.selected_time == selected
    window.sensor_earlier.click()
    pd.testing.assert_frame_equal(
        window.sensor_frame, frame.loc[(frame.time >= 30) & (frame.time < 36)]
    )


def test_context_time_marker_matches_result_marker_and_triangle_tip_meets_axis(window):
    frame = open_long_context(window)
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    axes = window.sensor_figure.axes[0]
    result_marker = next(
        line for line in window.figure.axes[0].lines if line.get_gid() == "selected-result-time"
    )
    marker = next(line for line in axes.lines if line.get_gid() == "selected-result-time")
    np.testing.assert_array_equal(marker.get_xdata(), result_marker.get_xdata())
    assert marker.get_color() == result_marker.get_color()
    assert marker.get_linewidth() == result_marker.get_linewidth()
    assert marker.get_linestyle() == result_marker.get_linestyle()
    triangle = next(line for line in axes.lines if line.get_gid() == "selected-result-triangle")
    for line in (triangle, window.time_axis.selection_marker):
        path = line._marker.get_path().transformed(line._marker.get_transform())
        assert path.vertices[:, 1].min() == pytest.approx(0.0)
        assert path.vertices[:, 1].max() > 0
        assert line.get_ydata()[0] == 0
    np.testing.assert_array_equal(
        signal_lines(axes)[0].get_ydata(), window.sensor_frame.gyroscope_x
    )
    pd.testing.assert_frame_equal(window.frame, frame)
    window.sensor_later.click()
    window.sensor_earlier.click()
    marker = next(
        line
        for line in window.sensor_figure.axes[0].lines
        if line.get_gid() == "selected-result-time"
    )
    np.testing.assert_array_equal(marker.get_xdata(), result_marker.get_xdata())
