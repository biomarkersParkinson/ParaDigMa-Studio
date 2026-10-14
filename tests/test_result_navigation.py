"""Results time scrolling and time-only zoom leave raw graph navigation intact."""

import numpy as np
import pandas as pd
import pytest
from matplotlib.backend_bases import MouseEvent
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider


def result_graphs(window, *, view=0, calendar=False):
    if calendar:
        window.provenance = {
            "display_clock": {"origin": "2026-10-24T00:00:00+02:00", "timezone": "Europe/Amsterdam"}
        }
    times = np.arange(0, 3 * 86400, 60)
    frame = pd.DataFrame(
        {"time": times, "pulse_rate": 65 + np.sin(times / 10000), "other": 70 + times / 86400}
    )
    window.analyzed({"quantifications": {"pulse_rate": frame}})
    window._series_items[("quantifications/pulse_rate", "other")].setCheckState(0, Qt.Checked)
    window.result_graph_view.setCurrentIndex(view)
    window.navigate(2)
    window.result_tabs.setCurrentIndex(1)
    QApplication.instance().processEvents()
    window.canvas.draw()
    return frame


@pytest.mark.parametrize("view", [0, 1, 2, 3], ids=["detailed", "30-minute", "day", "profile"])
@pytest.mark.parametrize("calendar", [False, True], ids=["elapsed", "calendar"])
def test_scrollbar_preserves_duration_shared_axes_tables_and_manual_y_limits(
    window, view, calendar
):
    frame = result_graphs(window, view=view, calendar=calendar)
    original = frame.copy(deep=True)
    axes, bar = window.figure.axes, window.result_time_scroll
    full = axes[0].get_xlim()
    assert not bar.isEnabled() and bar.maximum() == 0
    span = (full[1] - full[0]) / 4
    axes[1].set_ylim(40, 90)
    axes[0].set_xlim(full[0] + span, full[0] + 2 * span)
    assert bar.isEnabled() and 0 < bar.pageStep() < bar.STEPS
    for position, left in ((bar.maximum(), full[1] - span), (0, full[0])):
        bar.setValue(position)
        for ax in axes:
            assert ax.get_xlim() == pytest.approx((left, left + span))
        assert window.time_axis.axes.get_xlim() == pytest.approx((left, left + span))
        assert axes[1].get_ylim() == (40, 90)
    pd.testing.assert_frame_equal(window.tables["quantifications/pulse_rate"], original)


@pytest.mark.parametrize("manual_y", [False, True])
@pytest.mark.parametrize("horizontal", [False, True], ids=["rectangle", "horizontal-drag"])
def test_result_zoom_selects_only_time_even_for_a_horizontal_drag(window, manual_y, horizontal):
    result_graphs(window)
    axes, toolbar, canvas = window.figure.axes[0], window.plot_toolbar, window.canvas
    full = axes.get_xlim()
    if manual_y:
        axes.set_ylim(40, 90)
    window.figure.axes[1].set_ylim(10, 100)
    initial_y = axes.get_ylim()
    canvas.draw()
    first = axes.transAxes.transform((0.2, 0.3))
    last = axes.transAxes.transform((0.6, 0.3 if horizontal else 0.7))
    expected = axes.transData.inverted().transform([first, last])[:, 0]
    toolbar.zoom()
    press = MouseEvent("button_press_event", canvas, *first, button=1)
    release = MouseEvent("button_release_event", canvas, *last, button=1, key="y")
    toolbar.press_zoom(press)
    toolbar.release_zoom(release)
    assert release.key == "y"  # Other callbacks receive the original event.
    np.testing.assert_allclose(axes.get_xlim(), expected, rtol=0, atol=(full[1] - full[0]) / 500)
    assert axes.get_autoscaley_on() == (not manual_y)
    if manual_y:
        assert axes.get_ylim() == initial_y
    assert window.figure.axes[1].get_ylim() == (10, 100)
    assert window.result_time_scroll.isEnabled()


def test_zoom_preview_spans_full_graph_height_and_vertical_only_drags_do_not_zoom(
    window, monkeypatch
):
    result_graphs(window)
    axes, toolbar, canvas = window.figure.axes[0], window.plot_toolbar, window.canvas
    full = axes.get_xlim()
    first = axes.transAxes.transform((0.3, 0.2))
    last = axes.transAxes.transform((0.3, 0.8))
    boxes = []
    monkeypatch.setattr(toolbar, "draw_rubberband", lambda event, *bounds: boxes.append(bounds))
    toolbar.zoom()
    toolbar.press_zoom(MouseEvent("button_press_event", canvas, *first, button=1))
    toolbar.drag_zoom(MouseEvent("motion_notify_event", canvas, *last, buttons={1}))
    assert boxes[-1][1::2] == pytest.approx(axes.bbox.intervaly)
    toolbar.release_zoom(MouseEvent("button_release_event", canvas, *last, button=1))
    assert axes.get_xlim() == full


def test_scroll_history_home_keyboard_and_series_changes_follow_the_same_time_range(window):
    result_graphs(window)
    axes, toolbar, bar = window.figure.axes[0], window.plot_toolbar, window.result_time_scroll
    full = axes.get_xlim()
    toolbar.push_current()
    span = (full[1] - full[0]) / 4
    axes.set_xlim(full[0], full[0] + span)
    toolbar.push_current()
    zoomed = axes.get_xlim()
    bar.setFocus()
    QTest.keyClick(bar, Qt.Key_Right)
    shifted = axes.get_xlim()
    assert shifted[0] > zoomed[0]
    toolbar.back()
    assert axes.get_xlim() == zoomed and bar.value() == 0
    toolbar.forward()
    assert axes.get_xlim() == shifted and bar.value() > 0
    item = window._series_items[("quantifications/pulse_rate", "other")]
    item.setCheckState(0, Qt.Unchecked)
    item.setCheckState(0, Qt.Checked)
    assert axes.get_xlim() == shifted and bar.isEnabled()
    toolbar.home()
    assert axes.get_xlim() == full and not bar.isEnabled()
    window.clear_results()
    assert not bar.isEnabled() and bar.maximum() == 0


def test_scrollbar_is_pinned_below_the_time_axis_and_manual_outside_limits_are_preserved(window):
    result_graphs(window)
    bar, axes = window.result_time_scroll, window.figure.axes[0]
    assert window.graph_view.isAncestorOf(bar)
    assert not window.graph_scroll.isAncestorOf(bar)
    assert bar.visibleRegion().contains(bar.rect())
    full = axes.get_xlim()
    axes.set_xlim(full[0] - 100, full[0] + 100)
    assert axes.get_xlim() == (full[0] - 100, full[0] + 100)
    bar.setValue(bar.maximum())
    assert axes.get_xlim() == pytest.approx((full[1] - 200, full[1]))


def test_mouse_scroll_drag_moves_time_and_records_one_history_step(window):
    result_graphs(window)
    axes, toolbar, bar = window.figure.axes[0], window.plot_toolbar, window.result_time_scroll
    full = axes.get_xlim()
    toolbar.push_current()
    axes.set_xlim(full[0], full[0] + (full[1] - full[0]) / 4)
    toolbar.push_current()
    zoomed = axes.get_xlim()
    option = QStyleOptionSlider()
    bar.initStyleOption(option)
    handle = bar.style().subControlRect(QStyle.CC_ScrollBar, option, QStyle.SC_ScrollBarSlider, bar)
    start, end = handle.center(), handle.center() + QPoint(80, 0)
    QTest.mousePress(bar, Qt.LeftButton, pos=start)
    assert toolbar.scrolling_time and window.canvas.panning
    QTest.mouseMove(bar, end, delay=20)
    QTest.mouseRelease(bar, Qt.LeftButton, pos=end)
    shifted = axes.get_xlim()
    assert shifted[0] > zoomed[0]
    assert not toolbar.scrolling_time and not window.canvas.panning
    toolbar.back()
    assert axes.get_xlim() == zoomed
    toolbar.back()
    assert axes.get_xlim() == full
    toolbar.forward()
    toolbar.forward()
    assert axes.get_xlim() == shifted


def test_clearing_results_cancels_active_zoom_and_releases_its_graphs(window):
    result_graphs(window)
    axes, toolbar, canvas = window.figure.axes[0], window.plot_toolbar, window.canvas
    toolbar.zoom()
    toolbar.press_zoom(
        MouseEvent("button_press_event", canvas, *axes.transAxes.transform((0.3, 0.3)), button=1)
    )
    assert toolbar._zoom_info is not None and toolbar._automatic_bar_y
    window.clear_results()
    assert toolbar._zoom_info is None and not toolbar._automatic_bar_y
    assert not window.result_time_scroll.isEnabled()


@pytest.mark.parametrize("sensor_context", [False, True], ids=["data", "sensor-context"])
def test_raw_graph_zoom_keeps_both_axes_and_pan_control(window, sensor_context):
    frame = pd.DataFrame({"time": np.arange(20.0), "gyroscope_x": np.arange(20.0) ** 2})
    window.loaded(("sensor.csv", frame))
    if sensor_context:
        window.sensor_frame = window.frame
        window.sensor_times = window.frame.time.to_numpy()
        window.populate_sensor_channels()
        window.plot_sensor()
        toolbar, canvas = window.sensor_toolbar, window.sensor_canvas
    else:
        window.set_input_channels(["gyroscope_x"])
        toolbar, canvas = window.data_toolbar, window.data_canvas
    canvas.draw()
    axes = canvas.figure.axes[0]
    initial_x, initial_y = axes.get_xlim(), axes.get_ylim()
    assert toolbar._actions["pan"].isChecked()
    first, last = axes.transAxes.transform([(0.2, 0.2), (0.8, 0.8)])
    toolbar.zoom()
    toolbar.press_zoom(MouseEvent("button_press_event", canvas, *first, button=1))
    toolbar.release_zoom(MouseEvent("button_release_event", canvas, *last, button=1))
    assert axes.get_xlim() != initial_x and axes.get_ylim() != initial_y
    toolbar.pan()
    assert toolbar._actions["pan"].isChecked() and not toolbar._actions["zoom"].isChecked()
