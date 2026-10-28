"""Original-sample graphs share time selection, scrolling and visible Y scaling."""

import gc
import weakref

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from matplotlib.backend_bases import MouseEvent
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paradigma_studio.exploration import SensorContext


def open_graph(window, context, calendar=False):
    seconds = np.arange(101, dtype=float)
    gyro = np.full(len(seconds), 500.0)
    gyro[30:41] = np.linspace(-2, 3, 11)
    other = np.full(len(seconds), 900.0)
    other[30:41] = np.linspace(10, 20, 11)
    origin = pd.Timestamp("2026-10-25T00:00:00+02:00")
    times = origin + pd.to_timedelta(seconds, unit="s") if calendar and not context else seconds
    frame = pd.DataFrame(
        {
            "time": times,
            "gyroscope_x": gyro,
            "gyroscope_y": other,
            "accelerometer_x": 1000 + seconds,
        }
    )
    window.loaded(("source.parquet", frame))
    if context:
        if calendar:
            window._result_state.display_clock = {
                "origin": origin.isoformat(),
                "timezone": "Europe/Amsterdam",
            }
        window._sensor_state._sensor_context = SensorContext(frame, seconds, seconds, 20, 50, 35)
        window._sensor_controller.show_sensor_context()
        choose, figure, canvas, toolbar = (
            window.set_sensor_channels,
            window.sensor_figure,
            window.sensor_canvas,
            window.sensor_toolbar,
        )
        window.result_tabs.setTabVisible(window.sensor_tab_index, True)
        window.result_tabs.setCurrentIndex(window.sensor_tab_index)
        window.navigate(2)
    else:
        choose, figure, canvas, toolbar = (
            window.set_input_channels,
            window.data_figure,
            window.data_canvas,
            window.data_toolbar,
        )
        window.data_tabs.setCurrentIndex(1)
    choose(["gyroscope_x", "accelerometer_x"])
    canvas.draw()
    coordinates = (
        dates.date2num(origin + pd.to_timedelta(seconds, unit="s")) if calendar else seconds
    )
    return frame, figure, canvas, toolbar, choose, coordinates


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
@pytest.mark.parametrize("calendar", [False, True], ids=["seconds", "dates"])
@pytest.mark.parametrize("gutter", [False, True], ids=["graph", "between-graphs"])
def test_interval_selection_changes_shared_time_and_keeps_manual_y(
    window, context, calendar, gutter
):
    frame, figure, canvas, toolbar, _choose, xs = open_graph(window, context, calendar)
    original = frame.copy(deep=True)
    first, second = figure.axes
    first.set_ylim(-4, 6)
    start = first.transData.transform((xs[30], 0))
    end = second.transData.transform((xs[40], 1040))
    if gutter:
        start[1] = (first.bbox.y0 + second.bbox.y1) / 2
    press = MouseEvent("button_press_event", canvas, *start, button=1)
    release = MouseEvent("button_release_event", canvas, *end, button=1, key="y")
    assert toolbar.mode.name == "ZOOM" and "pan" not in toolbar._actions
    toolbar.press_zoom(press)
    toolbar.drag_zoom(MouseEvent("motion_notify_event", canvas, *end, buttons={1}))
    toolbar.release_zoom(release)
    assert release.key == "y"
    tolerance = (xs[-1] - xs[0]) / 400
    for ax in figure.axes:
        np.testing.assert_allclose(ax.get_xlim(), xs[[30, 40]], rtol=0, atol=tolerance)
    assert first.get_ylim() == (-4, 6) and not first.get_autoscaley_on()
    assert second.get_autoscaley_on()
    assert 1020 < second.get_ylim()[0] < 1032
    assert 1038 < second.get_ylim()[1] < 1050
    assert not toolbar.time_scroll.isHidden()
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
@pytest.mark.parametrize("pixel_ratio", [1, 2])
def test_interval_preview_shades_raw_graphs_and_gaps_without_redrawing_data(
    window, context, pixel_ratio, monkeypatch
):
    _frame, figure, canvas, toolbar, _choose, _xs = open_graph(window, context)
    canvas._set_device_pixel_ratio(pixel_ratio)
    QApplication.instance().processEvents()
    canvas.draw()
    original = canvas.grab().toImage()
    buffer = np.asarray(canvas.buffer_rgba()).copy()
    limits = [(ax.get_xlim(), ax.get_ylim()) for ax in figure.axes]
    data_bounds = [ax.dataLim.bounds for ax in figure.axes]
    draws = []
    draw = canvas.draw

    def capture_draw():
        draws.append(True)
        return draw()

    monkeypatch.setattr(canvas, "draw", capture_draw)
    upper, lower = figure.axes
    gap = (upper.bbox.y0 + lower.bbox.y1) / 2
    x0, x1 = upper.transAxes.transform([(0.2, 0.5), (0.65, 0.5)])[:, 0]
    toolbar.press_zoom(MouseEvent("button_press_event", canvas, x0, gap, button=1))
    toolbar.drag_zoom(MouseEvent("motion_notify_event", canvas, x1, gap, buttons={1}))
    actual = canvas.grab().toImage()
    scale = actual.devicePixelRatio() / pixel_ratio
    column = round((x0 + x1) / 2 * scale)
    for y in (upper.bbox.y0 + upper.bbox.height / 2, gap, lower.bbox.y0 + lower.bbox.height / 2):
        row = round((figure.bbox.height - y) * scale)
        expected = np.array(original.pixelColor(column, row).getRgb()[:3]) * 0.8 + (
            np.array([71, 125, 163]) * 0.2
        )
        np.testing.assert_allclose(actual.pixelColor(column, row).getRgb()[:3], expected, atol=2)
        outside = round(upper.transAxes.transform((0.8, 0.5))[0] * scale)
        assert actual.pixelColor(outside, row) == original.pixelColor(outside, row)
    assert not draws, "Previewing the interval must only repaint the cached Qt image"
    np.testing.assert_array_equal(canvas.buffer_rgba(), buffer)
    assert [(ax.get_xlim(), ax.get_ylim()) for ax in figure.axes] == limits
    assert [ax.dataLim.bounds for ax in figure.axes] == data_bounds
    toolbar.stop_navigation()
    assert canvas.zoom_rectangle is None
    cancelled = canvas.grab().toImage()
    row = round((figure.bbox.height - gap) * scale)
    assert cancelled.pixelColor(column, row) == original.pixelColor(column, row)


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
@pytest.mark.parametrize("calendar", [False, True], ids=["seconds", "dates"])
def test_visible_samples_set_automatic_y_and_new_channels_keep_time(window, context, calendar):
    _frame, figure, _canvas, toolbar, choose, xs = open_graph(window, context, calendar)
    toolbar.push_current()
    figure.axes[0].set_xlim(*xs[[30, 40]])
    toolbar.push_current()
    gyro, acc = figure.axes
    assert gyro.get_autoscaley_on()
    assert -4 < gyro.get_ylim()[0] < -2 and 3 < gyro.get_ylim()[1] < 5
    assert 1020 < acc.get_ylim()[0] < 1030 and 1040 < acc.get_ylim()[1] < 1050
    acc.set_ylim(1000, 1010)
    choose(["gyroscope_x", "gyroscope_y", "accelerometer_x"])
    gyro, acc = figure.axes
    assert gyro.get_xlim() == tuple(xs[[30, 40]])
    assert -6 < gyro.get_ylim()[0] < -2 and 20 < gyro.get_ylim()[1] < 25
    assert acc.get_ylim() == (1000, 1010) and not acc.get_autoscaley_on()
    toolbar.settings_action.setChecked(True)
    toolbar.active_axes = acc
    toolbar.settings.read_axes()
    toolbar.settings.bounds["y"][0].click()
    assert acc.get_autoscaley_on()
    assert 1040 < acc.get_ylim()[1] < 1050


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
@pytest.mark.parametrize("calendar", [False, True], ids=["seconds", "dates"])
def test_scrollbar_keeps_window_width_loads_samples_and_records_one_drag(window, context, calendar):
    frame, figure, _canvas, toolbar, _choose, xs = open_graph(window, context, calendar)
    home = figure.axes[0].get_xlim()
    toolbar.push_current()
    figure.axes[0].set_xlim(*xs[[30, 40]])
    toolbar.push_current()
    zoomed, y_limits = figure.axes[0].get_xlim(), figure.axes[0].get_ylim()
    bar = toolbar.time_scroll
    bar.setSliderDown(True)
    for fraction in (0.3, 0.6, 0.8):
        bar.setValue(round(bar.maximum() * fraction))
        assert figure.axes[0].get_ylim() == y_limits
    bar.setSliderDown(False)
    moved = figure.axes[0].get_xlim()
    assert moved[1] - moved[0] == pytest.approx(zoomed[1] - zoomed[0])
    assert moved[0] > xs[60]
    assert figure.axes[0].get_ylim()[0] < 500 < figure.axes[0].get_ylim()[1]
    if context:
        assert window._sensor_state.sensor_frame.time.min() > 60
        for line in figure.axes[0].lines:
            if line.get_gid() is None:
                np.testing.assert_array_equal(
                    line.get_ydata(), window._sensor_state.sensor_frame[line.get_label()]
                )
    toolbar.back()
    assert figure.axes[0].get_xlim() == zoomed
    toolbar.back()
    np.testing.assert_allclose(figure.axes[0].get_xlim(), home, rtol=0, atol=1e-10)
    toolbar.forward()
    toolbar.forward()
    assert figure.axes[0].get_xlim() == moved
    toolbar.home()
    np.testing.assert_allclose(figure.axes[0].get_xlim(), home, rtol=0, atol=1e-10)
    pd.testing.assert_frame_equal(window._input_state.frame, frame)


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
@pytest.mark.parametrize("trackpad", [False, True], ids=["shift-wheel", "trackpad"])
def test_horizontal_gestures_scroll_time_and_vertical_wheels_keep_time(window, context, trackpad):
    _frame, figure, canvas, toolbar, _choose, _xs = open_graph(window, context)
    toolbar._actions["zoom_in"].trigger()
    initial = figure.axes[0].get_xlim()
    event = QWheelEvent(
        QPointF(30, 30),
        QPointF(canvas.mapToGlobal(QPoint(30, 30))),
        QPoint(-45, 0) if trackpad else QPoint(),
        QPoint() if trackpad else QPoint(0, -120),
        Qt.NoButton,
        Qt.NoModifier if trackpad else Qt.ShiftModifier,
        Qt.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(canvas, event)
    assert event.isAccepted() and toolbar.scrolling_time
    toolbar.time_scroll.finish_gesture()
    shifted = figure.axes[0].get_xlim()
    assert shifted[0] > initial[0]
    assert shifted[1] - shifted[0] == pytest.approx(initial[1] - initial[0])
    toolbar.back()
    assert figure.axes[0].get_xlim() == initial
    vertical = QWheelEvent(
        QPointF(30, 30),
        QPointF(),
        QPoint(),
        QPoint(0, -120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(canvas, vertical)
    assert figure.axes[0].get_xlim() == initial


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
def test_compact_toolbar_scrollbar_and_axis_limits_remain_reachable(window, context):
    _frame, _figure, canvas, toolbar, _choose, _xs = open_graph(window, context)
    toolbar._actions["zoom_in"].trigger()
    window.resize(960, 650)
    toolbar.settings_action.setChecked(True)
    QTest.qWait(40)
    for control in (toolbar, toolbar.time_scroll, toolbar.settings.close_button, canvas):
        assert control.visibleRegion().boundingRect().contains(control.rect())
    assert canvas.height() >= 100


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
def test_automatic_time_limits_restore_the_source_range_and_history(window, context):
    _frame, figure, _canvas, toolbar, _choose, xs = open_graph(window, context)
    assert figure.axes[0].get_autoscalex_on() == (not context)
    full = tuple(toolbar.time_scroll._full_limits)
    toolbar.push_current()
    figure.axes[0].set_xlim(*xs[[30, 40]])
    toolbar.push_current()
    toolbar.settings_action.setChecked(True)
    toolbar.settings.bounds["x"][0].click()
    assert figure.axes[0].get_xlim() == full
    assert figure.axes[0].get_autoscalex_on()
    assert toolbar.time_scroll.isHidden()
    toolbar.back()
    assert figure.axes[0].get_xlim() == (30, 40)


def test_empty_context_intervals_keep_finite_bounds_and_later_load_new_samples(window):
    frame = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0, 50.0, 51.0, 52.0], "gyroscope_x": [1, 2, 3, 10, 20, 30]}
    )
    times = frame.time.to_numpy()
    window.loaded(("gaps.csv", frame))
    window._sensor_state._sensor_context = SensorContext(frame, times, times, 0, 2, 1)
    window._sensor_controller.show_sensor_context()
    window.set_sensor_channels(["gyroscope_x"])
    ax, toolbar = window.sensor_figure.axes[0], window.sensor_toolbar
    original_y = ax.get_ylim()
    ax.set_xlim(20, 22)
    toolbar.push_current()
    assert window._sensor_state.sensor_frame.empty
    assert ax.get_ylim() == original_y
    ax.set_xlim(50, 52)
    toolbar.push_current()
    assert window._sensor_state.sensor_frame.time.tolist() == [50, 51, 52]
    assert np.isfinite(ax.get_ylim()).all() and ax.get_ylim()[1] > 30


def test_loading_new_data_cancels_an_active_scroll_and_releases_old_axes(window):
    _frame, figure, _canvas, toolbar, _choose, _xs = open_graph(window, False)
    toolbar._actions["zoom_in"].trigger()
    toolbar.time_scroll.setSliderDown(True)
    toolbar.time_scroll.setValue(toolbar.time_scroll.maximum())
    previous = weakref.ref(figure.axes[0])
    replacement = pd.DataFrame({"time": [200.0, 201.0, 202.0], "gyroscope_x": [3.0, 4.0, 5.0]})
    window.loaded(("replacement.csv", replacement))
    QTest.qWait(220)
    assert not toolbar.scrolling_time and not toolbar.time_scroll.isSliderDown()
    assert not toolbar.time_scroll._wheel_timer.isActive()
    assert toolbar.time_scroll.isHidden()
    assert figure.axes[0].get_xlim()[0] > 190
    assert toolbar._nav_stack() is None
    gc.collect()
    assert previous() is None
