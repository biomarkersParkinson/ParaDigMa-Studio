"""Sensor drill-down shares Data's multi-channel workspace without page scrolling."""

import warnings

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_previews
from matplotlib import dates
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from paradigma_studio.app import MainWindow


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
    widget._result_state.provenance = {
        "source": "subject.csv",
        "settings": {"skip_preparation": True},
    }
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
    source = window._input_state.frame.copy(deep=True)
    context = window._sensor_state.sensor_frame.copy(deep=True)
    channels = ["accelerometer_x", "gyroscope_y", "gyroscope_z"]
    window.set_sensor_channels(channels)
    accelerometer, gyroscope = window.sensor_figure.axes
    assert [line.get_label() for line in signal_lines(accelerometer)] == channels[:1]
    assert [line.get_label() for line in signal_lines(gyroscope)] == channels[1:]
    lines = [line for ax in window.sensor_figure.axes for line in signal_lines(ax)]
    assert len({line.get_color() for line in lines}) == len(channels)
    assert [text.get_text() for text in gyroscope.get_legend().get_texts()] == channels[1:]
    for line in lines:
        np.testing.assert_array_equal(line.get_xdata(), window._sensor_state.sensor_times)
        np.testing.assert_array_equal(line.get_ydata(), context[line.get_label()])
        assert line.get_color() == window._data_state._channel_colors[line.get_label()]
    assert window.selected_input_channels() == ["accelerometer_x"]
    window.sensor_tabs.setCurrentIndex(1)
    pd.testing.assert_frame_equal(window.sensor_table.model().frame, context)
    pd.testing.assert_frame_equal(window._input_state.frame, source)


def test_channel_view_tracking_does_not_keep_a_cleared_context_alive(window):
    import gc
    from weakref import ref

    navigator = ref(window._sensor_state._sensor_navigator)
    window._workspace_controller.clear_results()
    gc.collect()
    assert navigator() is None


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
    frame = window._sensor_state.sensor_frame.copy()
    frame["source_clock"] = frame.pop("time")
    frame["complex_signal"] = 1j
    window._sensor_state.sensor_frame = frame
    window._result_state.provenance["settings"]["column_mapping"] = {"source_clock": "time"}
    window._result_state.display_clock = {
        "origin": "2026-10-09T13:00:00+02:00",
        "timezone": "Europe/Amsterdam",
    }
    window.populate_sensor_channels()
    available = [
        window.sensor_channels.item(i).data(Qt.UserRole)
        for i in range(window.sensor_channels.count())
    ]
    assert "source_clock" not in available and "complex_signal" not in available
    window.set_sensor_channels(["gyroscope_x", "gyroscope_y"])
    expected = dates.date2num(
        pd.Timestamp(window._result_state.display_clock["origin"])
        + pd.to_timedelta(window._sensor_state.sensor_times, unit="s")
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
        for control in window.results_header.findChildren(QPushButton):
            control.setMinimumWidth(native_button_width)
            control.setMinimumHeight(44)
    window.navigate(2)
    window.resize(*size)
    window.show()
    window.set_sensor_channels(["accelerometer_x", "gyroscope_x", "gyroscope_z"])
    QTest.qWait(40)
    scroll = window._layout._result_view_scrolls[window.sensor_tab_index]
    assert scroll.verticalScrollBar().maximum() == 0
    assert scroll.horizontalScrollBar().maximum() == 0
    assert window.sensor_canvas.visibleRegion().boundingRect().contains(window.sensor_canvas.rect())
    assert window.sensor_canvas.height() >= 100
    for control in window.results_header.findChildren(QPushButton):
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


def open_long_context(window, *, gap=False, gait=False):
    time = np.arange(8001) / 100
    frame = pd.DataFrame({"time": time, "gyroscope_x": np.sin(time), "gyroscope_z": np.cos(time)})
    if gap:
        frame = frame.loc[(frame.time < 40) | (frame.time > 60)].copy()
    window.loaded(("subject.csv", frame))
    window._result_state.provenance = {
        "source": "subject.csv",
        "settings": {"skip_preparation": True},
    }
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


def view_sensor(window, start, end):
    window.sensor_figure.axes[0].set_xlim(start, end)
    QApplication.instance().processEvents()


@pytest.mark.parametrize("gait", [False, True])
def test_hidden_sensor_table_defers_pans_and_home_until_opened(window, monkeypatch, gait):
    frame = open_long_context(window, gait=gait)
    initial = window._sensor_state.sensor_frame.copy(deep=True)
    assert window.sensor_table.model() is None
    updates = []
    set_model = window.sensor_table.setModel

    def record_model(model):
        updates.append(model)
        set_model(model)

    monkeypatch.setattr(window.sensor_table, "setModel", record_model)
    for start in (40, 60, 0):
        view_sensor(window, start, start + 20)
        expected = frame.loc[frame.time.between(start, start + 20)]
        pd.testing.assert_frame_equal(window._sensor_state.sensor_frame, expected)
        for line in signal_lines(window.sensor_figure.axes[0]):
            np.testing.assert_array_equal(line.get_ydata(), expected[line.get_label()])
    assert not updates
    window.sensor_tabs.setCurrentIndex(1)
    assert len(updates) == 1
    pd.testing.assert_frame_equal(window.sensor_table.model().frame, expected)

    # Revisiting an unchanged table preserves both its model and row selection.
    window.sensor_table.setCurrentIndex(window.sensor_table.model().index(2, 0))
    window.sensor_tabs.setCurrentIndex(0)
    window.sensor_tabs.setCurrentIndex(1)
    assert len(updates) == 1
    assert window.sensor_table.currentIndex().row() == 2

    window.sensor_tabs.setCurrentIndex(0)
    window.sensor_toolbar.home()
    pd.testing.assert_frame_equal(window._sensor_state.sensor_frame, initial)
    assert len(updates) == 1
    window.sensor_tabs.setCurrentIndex(1)
    assert len(updates) == 2
    pd.testing.assert_frame_equal(window.sensor_table.model().frame, initial)


def test_selected_sensor_table_updates_for_new_inspection_and_after_clear(window):
    frame = open_long_context(window, gap=True)
    window.sensor_tabs.setCurrentIndex(1)
    initial_model = window.sensor_table.model()
    window.hide_sensor_context()
    window._result_state.active_frame.loc[0, "time"] = 70.0
    window.inspect_sensor_context()
    assert window.sensor_tabs.currentWidget() is window.sensor_table
    assert window.sensor_table.model() is not initial_model
    pd.testing.assert_frame_equal(
        window.sensor_table.model().frame, frame.loc[frame.time.between(60, 80)]
    )

    # An empty window must replace the previous samples, including while visible.
    view_sensor(window, 40, 60)
    pd.testing.assert_frame_equal(
        window.sensor_table.model().frame, frame.loc[frame.time.between(40, 60)]
    )
    window.clear_results()
    window.sensor_tabs.setCurrentIndex(0)
    window.sensor_tabs.setCurrentIndex(1)
    assert window.sensor_table.model() is None
    frame = open_long_context(window)
    pd.testing.assert_frame_equal(
        window.sensor_table.model().frame, frame.loc[frame.time.between(20, 40)]
    )


def test_context_navigation_keeps_channels_original_samples_and_recording_boundaries(window):
    frame = open_long_context(window)
    original = frame.copy(deep=True)
    axes = tuple(window.sensor_figure.axes)
    pd.testing.assert_frame_equal(
        window._sensor_state.sensor_frame, frame.loc[frame.time.between(20, 40)]
    )
    graph = window.sensor_tabs.widget(0)
    # Navigation and axis-limit controls are checked in test_plot_controls.py.
    navigation = set(window.sensor_toolbar.findChildren(QWidget)) | set(
        window.sensor_toolbar.settings.findChildren(QWidget)
    )
    assert [
        button.text() for button in graph.findChildren(QPushButton) if button not in navigation
    ] == ["Select all", "Clear"]
    assert [label.text() for label in graph.findChildren(QLabel) if label not in navigation] == [
        "Channels"
    ]
    assert not graph.findChildren(QAbstractSpinBox)
    assert not [edit for edit in graph.findChildren(QLineEdit) if edit not in navigation]
    assert window.results_header.findChildren(QPushButton) == [window.sensor_close]
    for start in (40, 60, 40, 20, 0):
        view_sensor(window, start, start + 20)
        pd.testing.assert_frame_equal(
            window._sensor_state.sensor_frame, frame.loc[frame.time.between(start, start + 20)]
        )
        assert tuple(window.sensor_figure.axes) == axes
        assert window.selected_sensor_channels() == ["gyroscope_x", "gyroscope_z"]
        for line in signal_lines(axes[0]):
            np.testing.assert_array_equal(
                line.get_ydata(), window._sensor_state.sensor_frame[line.get_label()]
            )
    view_sensor(window, -20, 0)
    assert axes[0].get_xlim() == pytest.approx((0, 20))
    view_sensor(window, 80, 100)
    assert axes[0].get_xlim() == pytest.approx((60, 80))
    assert window._sensor_state._sensor_context.selected_time == 30
    pd.testing.assert_frame_equal(frame, original)
    window.sensor_close.click()
    assert not window.result_tabs.isTabVisible(window.sensor_tab_index)
    window.clear_results()
    assert (
        window._sensor_state._sensor_context is None
        and window._sensor_state._sensor_navigator is None
    )


def test_context_navigation_crosses_gaps_without_creating_original_samples(window):
    frame = open_long_context(window, gap=True)
    view_sensor(window, 40, 60)
    assert window._sensor_state.sensor_frame.empty
    assert all(len(line.get_xdata()) == 0 for line in signal_lines(window.sensor_figure.axes[0]))
    assert any(
        text.get_gid() == "sensor-no-data" and text.get_visible()
        for text in window.sensor_figure.axes[0].texts
    )
    view_sensor(window, 60, 80)
    pd.testing.assert_frame_equal(
        window._sensor_state.sensor_frame, frame.loc[frame.time.between(60, 80)]
    )
    view_sensor(window, 20, 40)
    pd.testing.assert_frame_equal(
        window._sensor_state.sensor_frame, frame.loc[frame.time.between(20, 40)]
    )


def test_gait_context_begins_at_full_segment_and_can_move_beyond_its_bounds(window):
    frame = open_long_context(window, gait=True)
    pd.testing.assert_frame_equal(
        window._sensor_state.sensor_frame, frame.loc[(frame.time >= 30) & (frame.time < 36)]
    )
    assert (
        window._sensor_state._sensor_context.start,
        window._sensor_state._sensor_context.end,
    ) == (30, 36)
    selected = window._sensor_state._sensor_context.selected_time
    view_sensor(window, 36, 42)
    pd.testing.assert_frame_equal(
        window._sensor_state.sensor_frame, frame.loc[frame.time.between(36, 42)]
    )
    assert window._sensor_state._sensor_context.selected_time == selected
    view_sensor(window, 30, 36)
    pd.testing.assert_frame_equal(
        window._sensor_state.sensor_frame, frame.loc[frame.time.between(30, 36)]
    )


@pytest.mark.parametrize("calendar", [False, True])
def test_real_pan_loads_beyond_initial_context_and_navigation_restores_view(window, calendar):
    from matplotlib.backend_bases import MouseEvent

    frame = open_long_context(window)
    if calendar:
        window._result_state.display_clock = {
            "origin": "2026-10-25T00:00:00Z",
            "timezone": "Europe/Amsterdam",
        }
        window.plot_sensor()
    canvas, toolbar = window.sensor_canvas, window.sensor_toolbar
    canvas.draw()
    axes = window.sensor_figure.axes[0]
    original = axes.get_xlim()
    x, y = axes.transAxes.transform((0.5, 0.5))
    toolbar.press_pan(MouseEvent("button_press_event", canvas, x, y, button=1))
    toolbar.drag_pan(
        MouseEvent("motion_notify_event", canvas, x - axes.bbox.width * 0.8, y, buttons={1})
    )
    QApplication.instance().processEvents()
    assert window._sensor_state.sensor_frame.time.min() > 30
    assert window._sensor_state.sensor_frame.time.max() > 50
    assert window.sensor_figure.axes[0] is axes
    assert window._sensor_state._sensor_context.selected_time == 30
    toolbar.release_pan(MouseEvent("button_release_event", canvas, x, y, button=1))
    for line in signal_lines(axes):
        np.testing.assert_array_equal(
            line.get_ydata(), window._sensor_state.sensor_frame[line.get_label()]
        )
    assert not any(
        line.get_visible() for line in axes.lines if line.get_gid() == "selected-result-time"
    )
    toolbar.back()
    QApplication.instance().processEvents()
    assert axes.get_xlim() == pytest.approx(original)
    assert any(
        line.get_visible() for line in axes.lines if line.get_gid() == "selected-result-time"
    )
    toolbar.forward()
    QApplication.instance().processEvents()
    assert window._sensor_state.sensor_frame.time.min() > 30
    assert window.sensor_table.model() is None
    window.sensor_tabs.setCurrentIndex(1)
    pd.testing.assert_frame_equal(
        window.sensor_table.model().frame, window._sensor_state.sensor_frame
    )
    pd.testing.assert_frame_equal(window._input_state.frame, frame)


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
        signal_lines(axes)[0].get_ydata(), window._sensor_state.sensor_frame.gyroscope_x
    )
    pd.testing.assert_frame_equal(window._input_state.frame, frame)
    view_sensor(window, 40, 60)
    view_sensor(window, 20, 40)
    marker = next(
        line
        for line in window.sensor_figure.axes[0].lines
        if line.get_gid() == "selected-result-time"
    )
    np.testing.assert_array_equal(marker.get_xdata(), result_marker.get_xdata())


def test_context_can_begin_in_a_gap_and_reselect_channels_before_panning_to_data(window):
    frame = open_long_context(window, gap=True)
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    window._result_state.active_frame.loc[0, "time"] = 50.0
    window.inspect_sensor_context()
    assert window._sensor_state.sensor_frame.empty
    assert window.sensor_figure.axes[0].get_xlim() == pytest.approx((40, 60))
    window.set_sensor_channels(["gyroscope_z"])
    assert window.sensor_figure.axes[0].get_xlim() == pytest.approx((40, 60))
    view_sensor(window, 60, 80)
    np.testing.assert_array_equal(
        signal_lines(window.sensor_figure.axes[0])[0].get_ydata(),
        frame.loc[frame.time.between(60, 80), "gyroscope_z"],
    )


def test_sensor_index_preserves_unsorted_duplicate_samples_and_ignores_invalid_times():
    from paradigma_studio.exploration import SensorContext
    from paradigma_studio.sensor_navigation import SensorNavigator

    times = np.array([-1.0, np.nan, 4.0, 2.0, 2.0, np.inf, 9.0])
    original = times.copy()
    context = SensorContext(pd.DataFrame({"time": times}), times, times, 1.0, 5.0, 2.0)
    navigator = SensorNavigator(context, None)
    np.testing.assert_array_equal(navigator.positions((2.0, 4.0)), [2, 3, 4])
    assert navigator.bounded_limits((-5.0, -3.0)) == (-1.0, 1.0)
    assert navigator.bounded_limits((12.0, 14.0)) == (7.0, 9.0)
    np.testing.assert_array_equal(times, original)


@pytest.mark.parametrize("calendar", [False, True])
@pytest.mark.parametrize("gait", [False, True])
def test_context_channel_changes_preserve_initial_and_panned_time_limits(window, calendar, gait):
    frame = open_long_context(window, gait=gait)
    frame["accelerometer_x"] = frame.gyroscope_x / 10
    window.inspect_sensor_context()
    if calendar:
        window._result_state.display_clock = {
            "origin": "2026-10-25T00:00:00Z",
            "timezone": "Europe/Amsterdam",
        }
        window.plot_sensor()
    initial = window.sensor_figure.axes[0].get_xlim()
    for limits in (
        initial,
        (
            initial[0] + (10 / 86400 if calendar else 10),
            initial[1] + (10 / 86400 if calendar else 10),
        ),
    ):
        window.sensor_figure.axes[0].set_xlim(*limits)
        sample_view = window._sensor_state.sensor_frame.copy(deep=True)
        for channels in (
            ["gyroscope_x"],
            ["gyroscope_x", "gyroscope_z"],
            ["gyroscope_x", "accelerometer_x"],
            [],
            ["gyroscope_z"],
        ):
            window.set_sensor_channels(channels)
            QApplication.instance().processEvents()
            if channels:
                assert all(ax.get_xlim() == limits for ax in window.sensor_figure.axes)
            pd.testing.assert_frame_equal(window._sensor_state.sensor_frame, sample_view)
        assert window._sensor_state._sensor_navigator.limits == limits


def test_context_opening_converts_only_visible_timestamps_and_reuses_source_index(
    window, monkeypatch
):
    import paradigma_studio.sensor_navigation as navigation

    times = np.arange(250_000) / 100
    frame = pd.DataFrame({"time": times, "gyroscope_x": np.sin(times)})
    window._input_state.frame = frame
    window._input_state.recordings = {}
    window._result_state.provenance = {
        "settings": {"skip_preparation": True},
        "display_clock": {"origin": "2026-10-10T00:00:00Z", "timezone": "UTC"},
    }
    window.analyzed(
        {
            "quantifications": {
                "tremor": pd.DataFrame(
                    {
                        "time": [120.0, 180.0],
                        "tremor_power": [1.0, 2.0],
                    }
                )
            }
        }
    )
    calls = []
    convert = navigation.clock_times
    monkeypatch.setattr(
        navigation,
        "clock_times",
        lambda values, clock: (calls.append(len(values)), convert(values, clock))[1],
    )
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    window.inspect_sensor_context()
    index = window._sensor_state._sensor_navigator.index
    assert calls and max(calls) < 3000
    pd.testing.assert_frame_equal(
        window._sensor_state.sensor_frame, frame.loc[frame.time.between(110, 130)]
    )
    window.result_table.setCurrentIndex(window.result_table.model().index(1, 0))
    window.inspect_sensor_context()
    assert window._sensor_state._sensor_navigator.index is index
    assert max(calls) < 3000
    pd.testing.assert_frame_equal(
        window._sensor_state.sensor_frame, frame.loc[frame.time.between(170, 190)]
    )
    window.clear_results()
    assert not window._sensor_state._sensor_time_indices


@pytest.mark.parametrize("origin", ["2026-10-25T00:00:00Z", "1965-01-01T01:02:03.123456Z"])
def test_calendar_sensor_navigation_matches_full_conversion_at_exact_endpoints(origin):
    from paradigma_studio.exploration import SensorContext
    from paradigma_studio.plotting import time_coordinates
    from paradigma_studio.results_view import clock_times
    from paradigma_studio.sensor_navigation import SensorNavigator

    times = np.array(
        [np.nan, -2.0, 0.0, 0.000001, 2.0000001, 2.0000001, 0.123456789, 3600.0, 7200.0]
    )
    clock = {"origin": origin, "timezone": "Europe/Amsterdam"}
    context = SensorContext(pd.DataFrame({"time": times}), times, times, 0.0, 10.0, 2.0)
    navigator = SensorNavigator(context, clock)
    finite = np.flatnonzero(np.isfinite(times))
    coordinates = np.full(len(times), np.nan)
    coordinates[finite] = time_coordinates(clock_times(times[finite], clock))
    for low in coordinates[finite]:
        for high in coordinates[finite]:
            if high >= low:
                np.testing.assert_array_equal(
                    navigator.positions((low, high)),
                    np.flatnonzero((coordinates >= low) & (coordinates <= high)),
                )


@pytest.mark.parametrize("calendar", [False, True])
@pytest.mark.parametrize("gait", [False, True])
@pytest.mark.parametrize("action", ["home", "reset_limits"])
def test_sensor_reset_restores_initial_context_after_channel_changes_and_keeps_history(
    window, calendar, gait, action
):
    open_long_context(window, gait=gait)
    if calendar:
        window._result_state.display_clock = {
            "origin": "2026-10-25T00:00:00Z",
            "timezone": "Europe/Amsterdam",
        }
        window.plot_sensor()
    original = window._sensor_state.sensor_frame.copy(deep=True)
    initial = window.sensor_figure.axes[0].get_xlim()
    width = initial[1] - initial[0]
    changed = initial[0] + width, initial[1] + width
    window.sensor_figure.axes[0].set_xlim(*changed)
    window.set_sensor_channels(["gyroscope_z"])
    panned = window._sensor_state.sensor_frame.copy(deep=True)
    if action == "home":
        window.sensor_toolbar._actions["home"].trigger()
    else:
        window.sensor_toolbar.settings_action.setChecked(True)
        window.sensor_toolbar.settings.reset_button.click()
    QApplication.instance().processEvents()
    assert window.sensor_figure.axes[0].get_xlim() == initial
    pd.testing.assert_frame_equal(window._sensor_state.sensor_frame, original)
    assert any(
        line.get_visible()
        for line in window.sensor_figure.axes[0].lines
        if line.get_gid() == "selected-result-time"
    )
    window.sensor_toolbar.back()
    QApplication.instance().processEvents()
    assert window.sensor_figure.axes[0].get_xlim() == changed
    pd.testing.assert_frame_equal(window._sensor_state.sensor_frame, panned)


def test_context_close_shares_recording_summary_row_and_nested_tabs_have_compact_spacing(window):
    window.navigate(2)
    window.resize(960, 650)
    window.show()
    QApplication.instance().processEvents()
    assert window.sensor_close.isVisible()
    assert window.sensor_close.parentWidget() is window.results_header
    assert (
        abs(
            window.sensor_close.geometry().center().y()
            - window.results_source.geometry().center().y()
        )
        <= 1
    )
    body = window._layout._result_view_layouts[window.sensor_tab_index]
    assert body.spacing() == 6
    assert [
        body.itemAt(i).widget() for i in range(body.count()) if body.itemAt(i).widget().isVisible()
    ] == [window.results_header, window.sensor_tabs]
    for tab in (0, 1, 2):
        window.result_tabs.setCurrentIndex(tab)
        QApplication.instance().processEvents()
        assert window.sensor_close.isHidden()
    window.result_tabs.setCurrentIndex(window.sensor_tab_index)
    QApplication.instance().processEvents()
    assert window.sensor_close.isVisible()
    window.sensor_close.click()
    assert not window.result_tabs.isTabVisible(window.sensor_tab_index)


@pytest.mark.parametrize("gait", [False, True])
@pytest.mark.parametrize("accelerometer_unit, gyroscope_unit", [("g", "deg/s"), ("m/s^2", "rad/s")])
def test_context_uses_saved_analysis_units_for_single_and_multiple_channels(
    window, gait, accelerometer_unit, gyroscope_unit
):
    source = open_long_context(window, gait=gait)
    source["accelerometer_x"] = np.sin(source.time)
    window.inspect_sensor_context()
    window._result_state.provenance.setdefault("settings", {}).update(
        accelerometer_units=accelerometer_unit, gyroscope_units=gyroscope_unit
    )
    # Current form changes must not relabel an earlier run's original samples.
    window.acc.setCurrentText("m/s²" if accelerometer_unit == "g" else "g")
    assert window.acc.currentData() != accelerometer_unit
    window.gyro.setCurrentText("rad/s" if gyroscope_unit == "deg/s" else "deg/s")
    original = window._sensor_state.sensor_frame.copy(deep=True)
    window.set_sensor_channels(["accelerometer_x", "gyroscope_x", "gyroscope_z"])
    labels = [ax.get_ylabel() for ax in window.sensor_figure.axes]
    assert set(labels) == {
        f"accelerometer_x\n({accelerometer_unit})",
        f"Gyroscope\n({gyroscope_unit})",
    }
    for ax in window.sensor_figure.axes:
        for line in signal_lines(ax):
            np.testing.assert_array_equal(line.get_ydata(), original[line.get_label()])
    pd.testing.assert_frame_equal(window._sensor_state.sensor_frame, original)
