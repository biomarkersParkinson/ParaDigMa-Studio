"""Time zoom buttons share raw axes while retaining values, history and context."""

import math

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates

from paradigma_studio.exploration import SensorContext


def raw_graph(window, context, calendar):
    seconds = np.arange(2001) / 100
    origin = pd.Timestamp("2026-10-27T12:00:00+01:00")
    times = origin + pd.to_timedelta(seconds, unit="s") if calendar and not context else seconds
    frame = pd.DataFrame(
        {"time": times, "gyroscope_x": np.sin(seconds), "accelerometer_x": 100 * np.cos(seconds)}
    )
    window.loaded(("source.parquet", frame))
    if context:
        if calendar:
            window._result_state.display_clock = {
                "origin": origin.isoformat(),
                "timezone": "Europe/Amsterdam",
            }
        window._sensor_state._sensor_context = SensorContext(frame, seconds, seconds, 4, 8, 6)
        window._sensor_controller.show_sensor_context()
        choose, figure, toolbar = (
            window.set_sensor_channels,
            window.sensor_figure,
            window.sensor_toolbar,
        )
        domain = (
            dates.date2num(origin + pd.to_timedelta([0, 20], unit="s")) if calendar else (0, 20)
        )
    else:
        choose, figure, toolbar = window.set_input_channels, window.data_figure, window.data_toolbar
        domain = None
    choose(["gyroscope_x", "accelerometer_x"])
    return frame, figure, toolbar, choose, domain


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
@pytest.mark.parametrize("calendar", [False, True], ids=["seconds", "dates"])
def test_zoom_buttons_change_only_time_and_keep_channel_edits_and_history(
    window, context, calendar
):
    frame, figure, toolbar, choose, _domain = raw_graph(window, context, calendar)
    original = frame.copy(deep=True)
    initial = figure.axes[0].get_xlim()
    figure.axes[0].set_ylim(-0.2, 0.4)
    vertical = [(ax.get_ylim(), ax.get_autoscaley_on()) for ax in figure.axes]
    for name in ("zoom_in", "zoom_out"):
        assert not toolbar._actions[name].icon().isNull()
        assert [action.text() for action in toolbar.actions()].count(
            toolbar._actions[name].text()
        ) == 1
    toolbar.settings_action.setChecked(True)
    toolbar._actions["zoom_in"].trigger()
    zoomed = figure.axes[0].get_xlim()
    assert zoomed[1] - zoomed[0] == pytest.approx((initial[1] - initial[0]) / 2, rel=1e-5)
    assert sum(zoomed) / 2 == pytest.approx(sum(initial) / 2, rel=0, abs=1e-10)
    assert all(ax.get_xlim() == zoomed for ax in figure.axes)
    assert [(ax.get_ylim(), ax.get_autoscaley_on()) for ax in figure.axes] == vertical
    assert not toolbar.settings.bounds["x"][0].isChecked()
    toolbar._actions["zoom_out"].trigger()
    np.testing.assert_allclose(figure.axes[0].get_xlim(), initial, rtol=0, atol=1e-10)
    toolbar._actions["zoom_in"].trigger()
    choose(["gyroscope_x"])
    np.testing.assert_allclose(figure.axes[0].get_xlim(), zoomed, rtol=0, atol=1e-10)
    assert figure.axes[0].get_ylim() == vertical[0][0]
    toolbar.home()
    np.testing.assert_allclose(figure.axes[0].get_xlim(), initial, rtol=0, atol=1e-10)
    toolbar.back()
    np.testing.assert_allclose(figure.axes[0].get_xlim(), zoomed, rtol=0, atol=1e-10)
    toolbar.forward()
    np.testing.assert_allclose(figure.axes[0].get_xlim(), initial, rtol=0, atol=1e-10)
    pd.testing.assert_frame_equal(frame, original)
    pd.testing.assert_frame_equal(window.input_table.model().frame, original)


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
@pytest.mark.parametrize("calendar", [False, True], ids=["seconds", "dates"])
def test_zoom_out_stops_at_recording_bounds_and_loads_new_context_samples(
    window, context, calendar
):
    frame, figure, toolbar, _choose, domain = raw_graph(window, context, calendar)
    initial = figure.axes[0].get_xlim()
    if not context:
        domain = initial
        assert not toolbar._actions["zoom_out"].isEnabled()
        toolbar._actions["zoom_in"].trigger()
    else:
        original_size = len(window._sensor_state.sensor_frame)
        toolbar._actions["zoom_out"].trigger()
        assert len(window._sensor_state.sensor_frame) > original_size
    for _ in range(10):
        toolbar._actions["zoom_out"].trigger()
    for axes in figure.axes:
        np.testing.assert_allclose(axes.get_xlim(), domain, rtol=0, atol=1e-10)
    assert not toolbar._actions["zoom_out"].isEnabled()
    if context:
        pd.testing.assert_frame_equal(window._sensor_state.sensor_frame, frame)
    toolbar.home()
    np.testing.assert_allclose(figure.axes[0].get_xlim(), initial, rtol=0, atol=1e-10)


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
def test_zoom_actions_disable_without_channels_and_reenable_after_selection(window, context):
    for toolbar in (window.data_toolbar, window.sensor_toolbar):
        assert not any(toolbar._actions[name].isEnabled() for name in ("zoom_in", "zoom_out"))
    _frame, _figure, toolbar, choose, _domain = raw_graph(window, context, False)
    assert toolbar._actions["zoom_in"].isEnabled()
    choose([])
    assert not any(toolbar._actions[name].isEnabled() for name in ("zoom_in", "zoom_out"))
    choose(["gyroscope_x"])
    assert toolbar._actions["zoom_in"].isEnabled()


@pytest.mark.parametrize("calendar", [False, True], ids=["centered-on-zero", "dates"])
def test_repeated_zoom_in_stops_at_finite_time_precision(window, calendar):
    times = (
        pd.date_range("2026-10-27", periods=3, freq="s", tz="UTC") if calendar else [-1.0, 0.0, 1.0]
    )
    window.loaded(("source.parquet", pd.DataFrame({"time": times, "gyroscope_x": [2, 3, 4]})))
    toolbar = window.data_toolbar
    for _ in range(80):
        if not toolbar._actions["zoom_in"].isEnabled():
            break
        toolbar._actions["zoom_in"].trigger()
    assert not toolbar._actions["zoom_in"].isEnabled()
    low, high = window.data_figure.axes[0].get_xlim()
    assert math.isfinite(low) and math.isfinite(high) and high > low
    toolbar.home()
    assert toolbar._actions["zoom_in"].isEnabled()
