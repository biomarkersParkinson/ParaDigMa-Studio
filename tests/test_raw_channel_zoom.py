"""Raw channel edits retain the current view while clocks and recordings reset it."""

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.mark.parametrize(
    "unit", ["relative_s", "relative_ms", "difference_ms", "absolute_ms", "datetime"]
)
def test_raw_channel_edits_keep_zoom_and_manual_y_with_working_home_and_history(window, unit):
    seconds = np.arange(1001) / 100
    raw = seconds
    if unit == "relative_ms":
        raw = seconds * 1000
    elif unit == "difference_ms":
        raw = np.r_[0, np.full(1000, 10)]
    elif unit == "absolute_ms":
        raw = pd.Timestamp("2026-10-27T12:00:00Z").timestamp() * 1000 + seconds * 1000
    elif unit == "datetime":
        raw = pd.Timestamp("2026-10-27T12:00:00+01:00") + pd.to_timedelta(seconds, unit="s")
    frame = pd.DataFrame(
        {
            "time": raw,
            "gyroscope_x": np.sin(seconds),
            "gyroscope_y": np.cos(seconds),
            "accelerometer_x": 100 * np.sin(seconds),
            "wear_flag": np.resize([0, 1], len(seconds)),
        }
    )
    original = frame.copy(deep=True)
    window.loaded(("source.parquet", frame))
    if unit != "datetime":
        window.data_time_unit.setCurrentText(unit)
    window.set_input_channels(["gyroscope_x"])
    window.data_tabs.setCurrentIndex(1)
    axes = window.data_figure.axes[0]
    coordinates = axes.lines[0].time_index.coordinates
    zoom = tuple(coordinates[[200, 400]])
    axes.set_xlim(*zoom)
    axes.set_ylim(-0.2, 0.4)
    toolbar = window.data_toolbar
    toolbar.active_axes = axes
    toolbar.settings_action.setChecked(True)
    # Exercise the same itemChanged signal as clicking a channel checkbox.
    item = next(
        window.data_channels.item(i)
        for i in range(window.data_channels.count())
        if window.data_channels.item(i).data(Qt.UserRole) == "gyroscope_y"
    )
    item.setCheckState(Qt.Checked)
    for selection in (
        ["gyroscope_y"],
        ["gyroscope_x", "accelerometer_x"],
        ["gyroscope_y", "wear_flag"],
    ):
        window.set_input_channels(selection)
        assert all(ax.get_xlim() == zoom for ax in window.data_figure.axes)
        gyroscope = next(
            ax
            for ax in window.data_figure.axes
            if any(line.get_label().startswith("gyroscope") for line in ax.lines)
        )
        assert gyroscope.get_ylim() == (-0.2, 0.4)
        assert not gyroscope.get_autoscaley_on()
        assert toolbar.active_axes is gyroscope
        for ax in window.data_figure.axes:
            if ax is not gyroscope and ax.lines:
                assert ax.get_autoscaley_on()
    toolbar.home()
    full = window.data_figure.axes[0].get_xlim()
    assert full[0] <= coordinates[0] and full[1] >= coordinates[-1]
    toolbar.back()
    assert all(ax.get_xlim() == zoom for ax in window.data_figure.axes)
    toolbar.forward()
    assert all(ax.get_xlim() == full for ax in window.data_figure.axes)
    pd.testing.assert_frame_equal(frame, original)
    pd.testing.assert_frame_equal(window.input_table.model().frame, original)


@pytest.mark.parametrize("dated", [False, True])
def test_clear_select_all_and_reselection_keep_time_zoom(window, dated):
    seconds = np.arange(1001) / 100
    times = (
        pd.Timestamp("2026-10-27T12:00:00Z") + pd.to_timedelta(seconds, unit="s")
        if dated
        else seconds
    )
    window.loaded(
        (
            "source.parquet",
            pd.DataFrame(
                {
                    "time": times,
                    "gyroscope_x": np.sin(seconds),
                    "accelerometer_x": 100 * np.cos(seconds),
                }
            ),
        )
    )
    window.set_input_channels(["gyroscope_x"])
    axes = window.data_figure.axes[0]
    zoom = tuple(axes.lines[0].time_index.coordinates[[200, 400]])
    axes.set_xlim(*zoom)
    actions = {
        button.text(): button
        for button in window.data_channels.parentWidget().findChildren(QPushButton)
    }
    for action in ("Clear", "Select all", "Clear"):
        actions[action].click()
        assert all(ax.get_xlim() == zoom for ax in window.data_figure.axes)
        assert (
            isinstance(window.data_figure.axes[0].xaxis.get_major_locator(), dates.DateLocator)
            == dated
        )
    window.set_input_channels(["accelerometer_x"])
    assert window.data_figure.axes[0].get_xlim() == zoom
    window.data_toolbar.home()
    assert window.data_figure.axes[0].get_xlim() != zoom


@pytest.mark.parametrize("reuse_frame", [False, True])
def test_new_recordings_and_time_selections_start_with_their_own_full_range(window, reuse_frame):
    frame = pd.DataFrame(
        {
            "time": np.arange(101, dtype=float),
            "clock_ms": np.arange(101) * 10,
            "gyroscope_x": np.arange(101),
        }
    )
    window.loaded(("source.csv", frame))
    window.set_input_channels(["gyroscope_x"])
    window.data_figure.axes[0].set_xlim(20, 30)
    # A new recording at the same path must not inherit the previous zoom.
    window.loaded(("source.csv", frame if reuse_frame else frame.copy(deep=True)))
    assert window.data_figure.axes[0].get_xlim()[1] >= 100
    window.data_tabs.setCurrentIndex(1)
    window.data_figure.axes[0].set_xlim(20, 30)
    window.data_time_unit.setCurrentText("relative_ms")
    assert window.data_figure.axes[0].get_xlim()[1] < 1
    window.data_figure.axes[0].set_xlim(0.02, 0.03)
    window.data_time_channel.setCurrentIndex(window.data_time_channel.findData("clock_ms"))
    assert window.data_figure.axes[0].get_xlim()[1] >= 1


def test_time_zoom_keeps_automatic_value_scaling_for_new_channels(window):
    seconds = np.arange(1001) / 100
    frame = pd.DataFrame(
        {"time": seconds, "gyroscope_x": np.sin(seconds), "gyroscope_y": 1000 * np.cos(seconds)}
    )
    window.loaded(("source.csv", frame))
    window.set_input_channels(["gyroscope_x"])
    window.data_figure.axes[0].set_xlim(2, 4)
    window.set_input_channels(["gyroscope_x", "gyroscope_y"])
    axes = window.data_figure.axes[0]
    assert axes.get_xlim() == (2, 4)
    assert axes.get_autoscaley_on()
    assert axes.get_ylim()[0] < -999 and axes.get_ylim()[1] < 200
