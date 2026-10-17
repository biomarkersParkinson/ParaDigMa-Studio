"""Results time scrolling and time-only zoom leave raw graph navigation intact."""

from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from matplotlib.backend_bases import MouseEvent
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
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
    assert not bar.isEnabled() and bar.maximum() == 0 and bar.isHidden()
    span = (full[1] - full[0]) / 4
    axes[1].set_ylim(40, 90)
    axes[0].set_xlim(full[0] + span, full[0] + 2 * span)
    assert bar.isEnabled() and not bar.isHidden() and 0 < bar.pageStep() < bar.STEPS
    for position, left in ((bar.maximum(), full[1] - span), (0, full[0])):
        bar.setValue(position)
        for ax in axes:
            assert ax.get_xlim() == pytest.approx((left, left + span))
        assert window.time_axis.axes.get_xlim() == pytest.approx((left, left + span))
        assert axes[1].get_ylim() == (40, 90)
    pd.testing.assert_frame_equal(window.tables["quantifications/pulse_rate"], original)


@pytest.mark.parametrize("view", [0, 1, 2, 3], ids=["detailed", "30-minute", "day", "profile"])
@pytest.mark.parametrize("calendar", [False, True], ids=["elapsed", "calendar"])
def test_each_results_view_opens_at_full_range_after_zooming_another_view(window, view, calendar):
    result_graphs(window, view=view, calendar=calendar)
    full = window.figure.axes[0].get_xlim()
    bar = window.result_time_scroll
    for previous_view in range(4):
        if previous_view == view:
            continue
        window.result_graph_view.setCurrentIndex(previous_view)
        bar.zoom(0.5)
        assert bar.isEnabled() and not bar.isHidden()
        window.result_graph_view.setCurrentIndex(view)
        QApplication.instance().processEvents()
        window.canvas.draw()
        for axes in window.figure.axes:
            assert axes.get_xlim() == pytest.approx(full)
        assert window.time_axis.axes.get_xlim() == pytest.approx(full)
        assert not bar.isEnabled() and bar.maximum() == 0 and bar.isHidden()
        assert not window.plot_toolbar._actions["zoom_out"].isEnabled()


@pytest.mark.parametrize("view", [0, 1, 2, 3], ids=["detailed", "30-minute", "day", "profile"])
def test_replacing_results_starts_at_full_range_in_the_current_view(window, view):
    result_graphs(window, view=view, calendar=True)
    full = window.figure.axes[0].get_xlim()
    window.result_time_scroll.zoom(0.5)
    assert window.result_time_scroll.isEnabled()
    result_graphs(window, view=view, calendar=True)
    for axes in window.figure.axes:
        assert axes.get_xlim() == pytest.approx(full)
    assert window.result_time_scroll.isHidden() and window.result_time_scroll.maximum() == 0


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


def test_zoom_preview_shades_every_graph_and_vertical_only_drags_do_not_zoom(window):
    result_graphs(window)
    axes, toolbar, canvas = window.figure.axes[0], window.plot_toolbar, window.canvas
    full = axes.get_xlim()
    first = axes.transAxes.transform((0.3, 0.2))
    last = axes.transAxes.transform((0.3, 0.8))
    original_bounds = [ax.dataLim.bounds for ax in window.figure.axes]
    toolbar.zoom()
    toolbar.press_zoom(MouseEvent("button_press_event", canvas, *first, button=1))
    toolbar.drag_zoom(MouseEvent("motion_notify_event", canvas, *last, buttons={1}))
    canvas.draw()
    region = canvas.zoom_rectangle
    assert region is not None
    assert region.top() == pytest.approx(
        (window.figure.bbox.height - max(ax.bbox.y1 for ax in window.figure.axes))
        / canvas.device_pixel_ratio
    )
    assert region.bottom() == pytest.approx(
        (window.figure.bbox.height - min(ax.bbox.y0 for ax in window.figure.axes))
        / canvas.device_pixel_ratio
    )
    assert [ax.dataLim.bounds for ax in window.figure.axes] == original_bounds
    toolbar.release_zoom(MouseEvent("button_release_event", canvas, *last, button=1))
    assert axes.get_xlim() == full
    assert canvas.zoom_rectangle is None


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
    assert axes.get_xlim() == full and not bar.isEnabled() and bar.isHidden()
    window.clear_results()
    assert not bar.isEnabled() and bar.maximum() == 0


def test_scrollbar_is_pinned_and_manual_time_limits_are_bounded_by_the_recording(window):
    result_graphs(window)
    bar, axes = window.result_time_scroll, window.figure.axes[0]
    assert window.graph_view.isAncestorOf(bar)
    assert not window.graph_scroll.isAncestorOf(bar)
    assert bar.isHidden()
    full = axes.get_xlim()
    axes.set_xlim(full[0] - 100, full[0] + 100)
    window.plot_toolbar.push_current()
    assert axes.get_xlim() == (full[0], full[0] + 200)
    QApplication.instance().processEvents()
    assert bar.isVisible() and bar.visibleRegion().contains(bar.rect())
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


@pytest.mark.parametrize("view", [0, 1, 2, 3], ids=["detailed", "30-minute", "day", "profile"])
def test_zoom_buttons_and_zoom_out_selection_never_exceed_the_full_time_range(window, view):
    result_graphs(window, view=view, calendar=True)
    toolbar, axes, bar = window.plot_toolbar, window.figure.axes[0], window.result_time_scroll
    assert toolbar._actions["zoom"].text() == "Select time interval"
    assert not toolbar._actions["zoom"].icon().isNull()
    full = axes.get_xlim()
    assert not toolbar._actions["zoom_out"].isEnabled() and bar.isHidden()
    toolbar._actions["zoom_in"].trigger()
    assert axes.get_xlim()[1] - axes.get_xlim()[0] == pytest.approx((full[1] - full[0]) / 2)
    assert not bar.isHidden() and toolbar._actions["zoom_out"].isEnabled()
    toolbar._actions["zoom_out"].trigger()
    assert axes.get_xlim() == pytest.approx(full) and bar.isHidden()
    window.canvas.draw()
    toolbar.zoom()
    start, end = axes.transAxes.transform([(0.45, 0.3), (0.55, 0.7)])
    toolbar.press_zoom(MouseEvent("button_press_event", window.canvas, *start, button=3))
    toolbar.release_zoom(MouseEvent("button_release_event", window.canvas, *end, button=3))
    assert all(ax.get_xlim() == pytest.approx(full) for ax in window.figure.axes)
    assert bar.isHidden()
    for raw_toolbar in (window.data_toolbar, window.sensor_toolbar):
        assert "zoom_in" not in raw_toolbar._actions and "zoom_out" not in raw_toolbar._actions


def send_wheel(widget, *, pixels=0, angle=0, vertical=0, phase=Qt.ScrollUpdate, inverted=False):
    event = QWheelEvent(
        QPointF(30, 30),
        QPointF(widget.mapToGlobal(QPoint(30, 30))),
        QPoint(pixels, vertical),
        QPoint(angle, 0),
        Qt.NoButton,
        Qt.NoModifier,
        phase,
        inverted,
    )
    QApplication.sendEvent(widget, event)
    return event


@pytest.mark.parametrize("target", ["canvas", "time_axis", "viewport"])
@pytest.mark.parametrize("calendar", [False, True], ids=["elapsed", "calendar"])
def test_horizontal_trackpad_scrolls_shared_time_and_keeps_one_navigation_step(
    window, target, calendar
):
    result_graphs(window, calendar=calendar)
    toolbar, axes, bar = window.plot_toolbar, window.figure.axes[0], window.result_time_scroll
    full = axes.get_xlim()
    original_y = window.figure.axes[1].get_ylim()
    window.figure.axes[1].set_ylim(*original_y)
    toolbar._actions["zoom_in"].trigger()
    window.canvas.draw()
    original = axes.get_xlim()
    widget = window.graph_scroll.viewport() if target == "viewport" else getattr(window, target)
    width = axes.bbox.width / window.canvas.device_pixel_ratio
    event = send_wheel(widget, pixels=-60, vertical=5)
    assert event.isAccepted() and toolbar.scrolling_time
    expected = original[0] + 60 / width * (original[1] - original[0])
    assert axes.get_xlim()[0] - original[0] == pytest.approx(
        expected - original[0], rel=1e-5, abs=(original[1] - original[0]) / bar.STEPS * 2
    )
    assert window.figure.axes[1].get_ylim() == original_y
    shifted = axes.get_xlim()
    assert send_wheel(widget, phase=Qt.ScrollEnd).isAccepted()
    assert not toolbar.scrolling_time
    assert window.time_axis.axes.get_xlim() == pytest.approx(shifted)
    toolbar.back()
    assert axes.get_xlim() == pytest.approx(original)
    toolbar.back()
    assert axes.get_xlim() == pytest.approx(full) and bar.isHidden()


def test_trackpad_angle_fallback_debounce_and_recording_edges(window):
    result_graphs(window)
    toolbar, axes = window.plot_toolbar, window.figure.axes[0]
    full = axes.get_xlim()
    toolbar._actions["zoom_in"].trigger()
    span = axes.get_xlim()[1] - axes.get_xlim()[0]
    before = axes.get_xlim()
    assert send_wheel(window.canvas, angle=-120, phase=Qt.NoScrollPhase).isAccepted()
    assert axes.get_xlim()[0] > before[0]
    QTest.qWait(250)
    assert not toolbar.scrolling_time
    send_wheel(window.canvas, pixels=-100000, inverted=True)
    assert axes.get_xlim() == pytest.approx((full[1] - span, full[1]))
    send_wheel(window.canvas, pixels=100000, inverted=True)
    assert axes.get_xlim() == pytest.approx((full[0], full[0] + span))
    send_wheel(window.canvas, phase=Qt.ScrollEnd)


@pytest.mark.parametrize("action", ["home", "back", "series", "drag-zoom"])
def test_interrupting_trackpad_gestures_preserves_automatic_y_and_navigation(window, action):
    result_graphs(window)
    toolbar, axes, bar = window.plot_toolbar, window.figure.axes[0], window.result_time_scroll
    full = axes.get_xlim()
    toolbar._actions["zoom_in"].trigger()
    zoomed = axes.get_xlim()
    send_wheel(window.canvas, pixels=-60)
    shifted = axes.get_xlim()
    assert toolbar.scrolling_time and not axes.get_autoscaley_on()
    if action == "series":
        window._series_items[("quantifications/pulse_rate", "other")].setCheckState(0, Qt.Unchecked)
        assert axes.get_xlim() == shifted
    elif action == "drag-zoom":
        toolbar.zoom()
        start = axes.transAxes.transform((0.3, 0.3))
        toolbar.press_zoom(MouseEvent("button_press_event", window.canvas, *start, button=1))
        assert toolbar._zoom_info is not None
        toolbar.stop_navigation()
    else:
        getattr(toolbar, action)()
        assert axes.get_xlim() == (full if action == "home" else zoomed)
    assert not toolbar.scrolling_time and not bar._wheel_timer.isActive()
    assert all(ax.get_autoscaley_on() for ax in window.figure.axes)
    toolbar.home()
    assert axes.get_xlim() == full and bar.isHidden()


@pytest.mark.parametrize("pixel_ratio", [1, 2])
def test_drag_zoom_shades_graphs_and_gaps_continuously_and_cleans_up_on_cancel(window, pixel_ratio):
    result_graphs(window)
    toolbar, canvas, axes = window.plot_toolbar, window.canvas, window.figure.axes[0]
    canvas._set_device_pixel_ratio(pixel_ratio)
    canvas.draw()
    original = canvas.grab().toImage()
    image_buffer = np.asarray(canvas.buffer_rgba()).copy()
    bounds = [ax.dataLim.bounds for ax in window.figure.axes]
    toolbar.zoom()
    start, end = axes.transAxes.transform([(0.005, 0.3), (0.65, 0.7)])
    toolbar.press_zoom(MouseEvent("button_press_event", canvas, *start, button=1))
    toolbar.drag_zoom(MouseEvent("motion_notify_event", canvas, *end, buttons={1}))
    assert canvas.zoom_rectangle.width() > 0
    actual = canvas.grab().toImage()
    boxes = sorted((ax.bbox for ax in window.figure.axes), key=lambda box: box.y0)
    for lower, upper in zip(boxes, boxes[1:], strict=False):
        scale = actual.devicePixelRatio() / pixel_ratio
        row = round((window.figure.bbox.height - (lower.y1 + upper.y0) / 2) * scale)
        column = round((start[0] + end[0]) / 2 * scale)
        expected = np.array(original.pixelColor(column, row).getRgb()[:3]) * 0.8 + (
            np.array([71, 125, 163]) * 0.2
        )
        np.testing.assert_allclose(actual.pixelColor(column, row).getRgb()[:3], expected, atol=2)
    np.testing.assert_array_equal(canvas.buffer_rgba(), image_buffer)
    assert [ax.dataLim.bounds for ax in window.figure.axes] == bounds
    toolbar.drag_zoom(MouseEvent("motion_notify_event", canvas, *end, buttons=set()))
    assert canvas.zoom_rectangle is None and toolbar._zoom_info is None
    assert not toolbar._automatic_bar_y


@pytest.mark.parametrize("view", [0, 1, 2, 3], ids=["detailed", "30-minute", "day", "profile"])
@pytest.mark.parametrize("calendar", [False, True], ids=["elapsed", "calendar"])
def test_time_interval_selection_can_start_in_the_gap_between_graphs(window, view, calendar):
    result_graphs(window, view=view, calendar=calendar)
    toolbar, canvas = window.plot_toolbar, window.canvas
    upper, lower = window.figure.axes
    original = upper.get_xlim()
    manual_y = (40, 90)
    lower.set_ylim(*manual_y)
    canvas.draw()
    gap_y = (upper.bbox.y0 + lower.bbox.y1) / 2
    start_x, end_x = upper.transAxes.transform([(0.2, 0.5), (0.65, 0.5)])[:, 0]
    press = MouseEvent("button_press_event", canvas, start_x, gap_y, button=1)
    assert press.inaxes is None
    toolbar._actions["zoom"].trigger()
    canvas.callbacks.process("button_press_event", press)
    assert toolbar._zoom_info is not None and press.inaxes is None
    drag = MouseEvent("motion_notify_event", canvas, end_x, gap_y, buttons={1})
    canvas.callbacks.process("motion_notify_event", drag)
    assert canvas.zoom_rectangle is not None and drag.inaxes is None
    assert canvas.cursor().shape() == Qt.CrossCursor
    release = MouseEvent("button_release_event", canvas, end_x, gap_y, button=1)
    expected = upper.transData.inverted().transform([(press.x, gap_y), (release.x, gap_y)])[:, 0]
    canvas.callbacks.process("button_release_event", release)
    assert all(ax.get_xlim() == pytest.approx(expected) for ax in window.figure.axes)
    assert lower.get_ylim() == manual_y
    assert canvas.zoom_rectangle is None
    toolbar.home()
    assert upper.get_xlim() == original


def test_qt_pointer_events_select_time_from_a_gap_and_keep_shading_out_of_saved_figures(window):
    result_graphs(window, view=1, calendar=True)
    toolbar, canvas = window.plot_toolbar, window.canvas
    upper, lower = window.figure.axes
    before = BytesIO()
    window.figure.savefig(before, format="png", dpi=80)
    QApplication.instance().processEvents()
    canvas.draw()
    gap_y = (upper.bbox.y0 + lower.bbox.y1) / 2
    x = upper.transAxes.transform([(0.2, 0.5), (0.65, 0.5)])[:, 0]
    start, end = [QPoint(round(value), round(canvas.height() - gap_y)) for value in x]
    toolbar._actions["zoom"].trigger()
    QTest.mousePress(canvas, Qt.LeftButton, pos=start)
    QTest.mouseMove(canvas, end, delay=10)
    assert toolbar._zoom_info is not None and canvas.zoom_rectangle is not None
    selected = BytesIO()
    window.figure.savefig(selected, format="png", dpi=80)
    assert selected.getvalue() == before.getvalue()
    QTest.mouseRelease(canvas, Qt.LeftButton, pos=end)
    assert toolbar._zoom_info is None and canvas.zoom_rectangle is None


@pytest.mark.parametrize("position", ["left", "right", "above", "below"])
def test_interval_selection_does_not_start_outside_the_shaded_plot_area(window, position):
    result_graphs(window)
    toolbar, canvas, axes = window.plot_toolbar, window.canvas, window.figure.axes
    left, right = axes[0].bbox.intervalx
    bottom, top = min(ax.bbox.y0 for ax in axes), max(ax.bbox.y1 for ax in axes)
    point = {
        "left": (left - 5, (bottom + top) / 2),
        "right": (right + 5, (bottom + top) / 2),
        "above": ((left + right) / 2, top + 5),
        "below": ((left + right) / 2, bottom - 5),
    }[position]
    toolbar.zoom()
    toolbar.press_zoom(MouseEvent("button_press_event", canvas, *point, button=1))
    assert toolbar._zoom_info is None and canvas.zoom_rectangle is None


@pytest.mark.parametrize("sensor_context", [False, True], ids=["data", "sensor-context"])
def test_raw_graph_zoom_keeps_both_axes_and_pan_control(window, sensor_context):
    frame = pd.DataFrame({"time": np.arange(20.0), "gyroscope_x": np.arange(20.0) ** 2})
    window.loaded(("sensor.csv", frame))
    if sensor_context:
        window.sensor_frame = window._input_state.frame
        window.sensor_times = window._input_state.frame.time.to_numpy()
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
