"""The hand tool moves shared time without changing scale, selection or data."""

import gc
import weakref

import numpy as np
import pandas as pd
import pytest
from matplotlib.backend_bases import MouseEvent
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from test_raw_navigation import open_graph
from test_result_navigation import result_graphs

VIEWS = ["data", "context", "detailed", "30-minute", "day", "profile"]


def workspace(window, view, calendar=False):
    if view in ("data", "context"):
        frame, figure, canvas, toolbar, _choose, _xs = open_graph(
            window, view == "context", calendar
        )
    else:
        frame = result_graphs(window, view=VIEWS.index(view) - 2, calendar=calendar)
        figure, canvas, toolbar = window.figure, window.canvas, window.plot_toolbar
        model = window.result_table.model()
        window.result_table.setCurrentIndex(model.index(100, 0))
    return frame, figure, canvas, toolbar


def mouse(canvas, name, x, y, *, button=None, buttons=None):
    event = MouseEvent(name, canvas, x, y, button=button, buttons=buttons)
    canvas.callbacks.process(name, event)
    return event


def start_drag(canvas, toolbar, *, gutter=False):
    toolbar._actions["pan"].trigger()
    axes = canvas.figure.axes
    x, y = axes[0].transAxes.transform((0.5, 0.5))
    if gutter:
        y = (axes[0].bbox.y0 + axes[1].bbox.y1) / 2
    press = mouse(canvas, "button_press_event", x, y, button=1)
    assert toolbar._pan_info is not None and toolbar.scrolling_time
    assert canvas.cursor().shape() == Qt.ClosedHandCursor
    return press


@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("calendar", [False, True], ids=["elapsed", "calendar"])
@pytest.mark.parametrize("gutter", [False, True], ids=["plot", "between-plots"])
def test_hand_moves_shared_time_and_records_one_settled_history_step(
    window, view, calendar, gutter
):
    frame, figure, canvas, toolbar = workspace(window, view, calendar)
    original = frame.copy(deep=True)
    figure.axes[1].set_ylim(-123, 456)
    home = figure.axes[0].get_xlim()
    toolbar.time_scroll.zoom(0.25)
    canvas.draw()
    before = figure.axes[0].get_xlim()
    previous_y = [ax.get_ylim() for ax in figure.axes]
    previous_flags = [ax.get_autoscaley_on() for ax in figure.axes]
    selection = window.result_table.currentIndex(), window._result_state._profile_selection
    history = len(toolbar._nav_stack)
    press = start_drag(canvas, toolbar, gutter=gutter)
    span = before[1] - before[0]
    for fraction in (0.1, 0.25):
        x = press.x - figure.axes[0].bbox.width * fraction
        mouse(canvas, "motion_notify_event", x, press.y + 40, buttons={1})
        assert [ax.get_ylim() for ax in figure.axes] == previous_y
    moved = figure.axes[0].get_xlim()
    assert moved[0] == pytest.approx(before[0] + span / 4, rel=0, abs=span / 200)
    assert moved[1] - moved[0] == pytest.approx(span)
    mouse(canvas, "button_release_event", x, press.y + 40, button=1)
    assert not toolbar.scrolling_time and toolbar._pan_info is None
    assert canvas.cursor().shape() == Qt.OpenHandCursor
    assert len(toolbar._nav_stack) == history + 1
    assert all(ax.get_xlim() == moved for ax in figure.axes)
    assert [ax.get_autoscaley_on() for ax in figure.axes] == previous_flags
    assert figure.axes[1].get_ylim() == (-123, 456)
    assert (
        window.result_table.currentIndex(),
        window._result_state._profile_selection,
    ) == selection
    assert toolbar.time_scroll.value() > 0
    if view not in ("data", "context"):
        assert window.time_axis.axes.get_xlim() == moved
    toolbar.back()
    assert figure.axes[0].get_xlim() == before
    toolbar.forward()
    assert figure.axes[0].get_xlim() == moved
    toolbar.home()
    assert figure.axes[0].get_xlim() == home
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("view", VIEWS)
def test_hand_clamps_both_ends_keeps_duration_and_does_nothing_at_full_range(window, view):
    _frame, figure, canvas, toolbar = workspace(window, view)
    full = tuple(toolbar.time_scroll._full_limits)
    # Raw context opens zoomed, whereas Home retains its original context window.
    figure.axes[0].set_xlim(*full)
    toolbar.push_current()
    toolbar._actions["pan"].trigger()
    point = figure.axes[0].transAxes.transform((0.5, 0.5))
    mouse(canvas, "button_press_event", *point, button=1)
    assert toolbar._pan_info is None and not toolbar.scrolling_time
    assert figure.axes[0].get_xlim() == full
    toolbar.time_scroll.zoom(0.25)
    canvas.draw()
    width = figure.axes[0].get_xlim()[1] - figure.axes[0].get_xlim()[0]
    for direction, expected in ((-1, (full[1] - width, full[1])), (1, (full[0], full[0] + width))):
        x, y = figure.axes[0].transAxes.transform((0.5, 0.5))
        mouse(canvas, "button_press_event", x, y, button=1)
        end = x + direction * figure.axes[0].bbox.width * 10
        mouse(canvas, "motion_notify_event", end, y, buttons={1})
        mouse(canvas, "button_release_event", end, y, button=1)
        np.testing.assert_allclose(figure.axes[0].get_xlim(), expected, rtol=0, atol=1e-8)
    assert toolbar.mode.name == "PAN" and not toolbar.scrolling_time
    if view == "profile":
        assert full == (0, 86400)


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
def test_raw_hand_loads_new_samples_and_refits_only_automatic_y_on_release(window, context):
    frame, figure, canvas, toolbar, _choose, xs = open_graph(window, context)
    figure.axes[1].set_ylim(1000, 1010)
    figure.axes[0].set_xlim(*xs[[30, 40]])
    toolbar.push_current()
    canvas.draw()
    previous_y = figure.axes[0].get_ylim()
    press = start_drag(canvas, toolbar)
    x = press.x - figure.axes[0].bbox.width * 4
    mouse(canvas, "motion_notify_event", x, press.y, buttons={1})
    assert figure.axes[0].get_ylim() == previous_y
    mouse(canvas, "button_release_event", x, press.y, button=1)
    assert figure.axes[0].get_ylim()[0] < 500 < figure.axes[0].get_ylim()[1]
    assert figure.axes[0].get_autoscaley_on()
    assert figure.axes[1].get_ylim() == (1000, 1010)
    if context:
        assert window._sensor_state.sensor_frame.time.min() > 60
        for line in figure.axes[0].lines:
            if line.get_gid() is None:
                np.testing.assert_array_equal(
                    line.get_ydata(), window._sensor_state.sensor_frame[line.get_label()]
                )
    pd.testing.assert_frame_equal(window._input_state.frame, frame)


@pytest.mark.parametrize(
    "end", ["lost-button", "interval", "timepoint", "home", "zoom-button", "view"]
)
def test_interrupted_hand_gestures_release_capture_restore_scaling_and_keep_controls_usable(
    window, end
):
    _frame, figure, canvas, toolbar = workspace(window, "detailed")
    toolbar.time_scroll.zoom(0.25)
    canvas.draw()
    press = start_drag(canvas, toolbar)
    mouse(canvas, "motion_notify_event", press.x - 50, press.y, buttons={1})
    if end == "lost-button":
        mouse(canvas, "motion_notify_event", press.x - 60, press.y, buttons=set())
    elif end == "interval":
        toolbar._actions["zoom"].trigger()
    elif end == "timepoint":
        toolbar.select_action.trigger()
    elif end == "home":
        toolbar.home()
    elif end == "zoom-button":
        toolbar._actions["zoom_in"].trigger()
    else:
        window.result_graph_view.setCurrentIndex(3)
    assert toolbar._pan_info is None and toolbar._time_pan is None
    assert not toolbar.scrolling_time and not canvas.panning
    assert all(ax.get_autoscaley_on() for ax in figure.axes)
    # A later motion cannot move the finished or newly created view.
    limits = [ax.get_xlim() for ax in figure.axes]
    mouse(canvas, "motion_notify_event", press.x - 100, press.y, buttons={1})
    assert [ax.get_xlim() for ax in figure.axes] == limits


def test_replacing_raw_data_ends_hand_capture_and_releases_old_axes(window):
    _frame, figure, canvas, toolbar = workspace(window, "data")
    toolbar.time_scroll.zoom(0.25)
    canvas.draw()
    start_drag(canvas, toolbar)
    previous = weakref.ref(figure.axes[0])
    window.loaded(("new.csv", pd.DataFrame({"time": [200, 201], "gyroscope_x": [1, 2]})))
    assert toolbar._pan_info is None and toolbar._time_pan is None
    assert not toolbar.scrolling_time and toolbar._nav_stack() is None
    gc.collect()
    assert previous() is None


@pytest.mark.parametrize("pixel_ratio", [1, 2])
def test_native_mouse_hand_uses_a_hand_cursor_and_right_button_does_not_zoom(window, pixel_ratio):
    _frame, figure, canvas, toolbar = workspace(window, "data")
    canvas._set_device_pixel_ratio(pixel_ratio)
    toolbar.time_scroll.zoom(0.25)
    canvas.draw()
    toolbar._actions["pan"].trigger()
    assert toolbar._actions["pan"].text() == "Drag time"
    assert not toolbar._actions["pan"].icon().isNull()
    x, y = figure.axes[0].transAxes.transform((0.5, 0.5))
    pos = QPoint(round(x / pixel_ratio), round((figure.bbox.height - y) / pixel_ratio))
    QTest.mouseMove(canvas, pos)
    assert canvas.cursor().shape() == Qt.OpenHandCursor
    before = figure.axes[0].get_xlim()
    QTest.mouseClick(canvas, Qt.RightButton, pos=pos)
    assert toolbar._pan_info is None and figure.axes[0].get_xlim() == before
    QTest.mousePress(canvas, Qt.LeftButton, pos=pos)
    assert canvas.cursor().shape() == Qt.ClosedHandCursor
    QTest.mouseMove(canvas, pos - QPoint(40, 0), delay=10)
    QTest.mouseRelease(canvas, Qt.LeftButton, pos=pos - QPoint(40, 0))
    assert canvas.cursor().shape() == Qt.OpenHandCursor and toolbar._pan_info is None
    assert figure.axes[0].get_xlim()[0] > before[0]
    assert figure.axes[0].get_xlim()[1] - figure.axes[0].get_xlim()[0] == pytest.approx(
        before[1] - before[0]
    )
