"""Cursor modes and axis limits change presentation without changing analysis data."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from matplotlib.backend_bases import MouseEvent
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from paradigma_desktop.app import MainWindow


@pytest.fixture
def window(tmp_path):
    application = QApplication.instance() or QApplication([])
    original_palette = application.palette()
    dark = QPalette()
    for role in (QPalette.Window, QPalette.Base, QPalette.Button):
        dark.setColor(role, QColor("#101522"))
    dark.setColor(QPalette.Text, QColor("#000000"))
    application.setPalette(dark)
    widget = MainWindow(history_dir=tmp_path / "runs")
    widget.show()
    application.processEvents()
    yield widget
    widget.close()
    application.processEvents()
    application.setPalette(original_palette)


def recording(window):
    frame = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0], "gyroscope_x": [1.0, 2.0, 3.0], "gyroscope_y": [3.0, 2.0, 1.0]}
    )
    window.loaded(("sensor.csv", frame))
    window.set_input_channels(["gyroscope_x", "gyroscope_y"])
    window.data_tabs.setCurrentIndex(1)
    return frame


def test_axis_limits_are_the_only_settings_and_remain_readable_and_fitted(window):
    recording(window)
    for toolbar in (window.data_toolbar, window.plot_toolbar, window.sensor_toolbar):
        actions = [action.text() for action in toolbar.actions() if not action.isSeparator()]
        assert actions.count("Axis limits") == 1
        assert {"Home", "Back", "Forward", "Select timepoint", "Pan", "Zoom", "Save"} <= set(
            actions
        )
        assert not {"Graph settings", "Subplots", "Customize"} & set(actions)
        toolbar.settings_action.setChecked(True)
        panel = toolbar.settings
        assert not panel.isHidden() and not panel.limits_panel.isHidden()
        assert not any(
            hasattr(panel, name)
            for name in ("title", "x_label", "y_label", "grid", "legend", "limits_button")
        )
        assert panel.palette().color(QPalette.Text) == QColor("#22324a")
        for _, lower, upper in panel.bounds.values():
            for edit in (lower, upper):
                assert edit.palette().color(QPalette.Active, QPalette.Base) == QColor("#ffffff")
                assert edit.palette().color(QPalette.Active, QPalette.Text) == QColor("#22324a")
        toolbar.settings_action.setChecked(False)
        assert panel.isHidden()
    window.resize(960, 650)
    window.data_toolbar.settings_action.setChecked(True)
    QApplication.instance().processEvents()
    assert window.data_toolbar.settings.apply_button.isVisible()
    assert window.data_canvas.height() >= 100


def test_limits_validate_atomically_and_reset_preserves_data_and_other_presentation(window):
    frame = recording(window)
    original = frame.copy(deep=True)
    toolbar = window.data_toolbar
    toolbar.settings_action.setChecked(True)
    panel, axes = toolbar.settings, window.data_figure.axes[0]
    title, xlabel, ylabel = axes.get_title(loc="left"), axes.get_xlabel(), axes.get_ylabel()
    for axis, values in (("x", ("0.5", "1.5")), ("y", ("1.2", "2.8"))):
        automatic, lower, upper = panel.bounds[axis]
        automatic.setChecked(False)
        assert lower.isEnabled() and upper.isEnabled()
        lower.setText(values[0])
        upper.setText(values[1])
    panel.apply_button.click()
    assert axes.get_xlim() == pytest.approx((0.5, 1.5))
    assert axes.get_ylim() == pytest.approx((1.2, 2.8))
    automatic, lower, upper = panel.bounds["x"]
    lower.setText("0")
    upper.setText("2")
    panel.bounds["y"][1].setText("inf")
    panel.apply_button.click()
    assert not panel.error.isHidden()
    assert axes.get_xlim() == pytest.approx((0.5, 1.5))
    assert axes.get_ylim() == pytest.approx((1.2, 2.8))
    panel.reset_button.click()
    assert panel.error.isHidden()
    assert axes.get_autoscalex_on() and axes.get_autoscaley_on()
    assert axes.get_xlim()[0] < 0 and axes.get_xlim()[1] > 2
    assert axes.get_ylim()[0] < 1 and axes.get_ylim()[1] > 3
    assert (axes.get_title(loc="left"), axes.get_xlabel(), axes.get_ylabel()) == (
        title,
        xlabel,
        ylabel,
    )
    assert axes.get_legend().get_visible()
    for line in axes.lines:
        np.testing.assert_array_equal(line.get_ydata(), frame[line.get_label()])
    pd.testing.assert_frame_equal(frame, original)


def test_date_limits_accept_zoned_timestamps_and_replot_refreshes_settings(window):
    frame = pd.DataFrame(
        {
            "time": pd.date_range("2026-10-07", periods=3, freq="1s", tz="Europe/Amsterdam"),
            "gyroscope_x": [1.0, 2.0, 3.0],
            "gyroscope_y": [3.0, 2.0, 1.0],
        }
    )
    window.loaded(("dated.csv", frame))
    window.data_toolbar.settings_action.setChecked(True)
    panel = window.data_toolbar.settings
    automatic, lower, upper = panel.bounds["x"]
    assert "ISO date/time" in lower.toolTip()
    automatic.setChecked(False)
    lower.setText(frame.time.iloc[0].isoformat())
    upper.setText(frame.time.iloc[1].isoformat())
    panel.apply()
    assert window.data_figure.axes[0].get_xlim() == pytest.approx(
        dates.date2num(frame.time.iloc[:2].to_numpy())
    )
    window.set_input_channels(["gyroscope_y"])
    assert automatic.isChecked() and not panel.error.isVisible()
    assert window.data_toolbar._nav_stack() is None


def test_result_and_sensor_limits_use_clicked_graph_and_keep_original_tables(window):
    recording(window)
    result = pd.DataFrame({"time": [0.0, 1.0, 2.0], "metric": [10.0, 20.0, 30.0]})
    window.analyzed({"quantifications": {"tremor": result}})
    for toolbar, figure in (
        (window.plot_toolbar, window.figure),
        (window.sensor_toolbar, window.sensor_figure),
    ):
        if toolbar is window.sensor_toolbar:
            window.sensor_frame = window.frame
            window.sensor_times = window.frame.time.to_numpy()
            window.populate_sensor_channels()
            window.plot_sensor()
        toolbar.settings_action.setChecked(True)
        automatic, lower, upper = toolbar.settings.bounds["y"]
        automatic.setChecked(False)
        lower.setText("0")
        upper.setText("40")
        toolbar.settings.apply()
        assert figure.axes[0].get_ylim() == pytest.approx((0, 40))
    pd.testing.assert_frame_equal(window.active_frame, result)
    np.testing.assert_array_equal(
        window.sensor_figure.axes[0].lines[0].get_ydata(), window.frame.gyroscope_x
    )


def test_cursor_modes_are_exclusive_and_default_to_selection(window):
    recording(window)
    for toolbar in (window.data_toolbar, window.plot_toolbar, window.sensor_toolbar):
        assert toolbar.select_action.isChecked() and not toolbar.mode
        assert not toolbar.select_action.icon().pixmap(24, 24).isNull()
        for mode in ("pan", "zoom", "pan"):
            toolbar._actions[mode].trigger()
            assert toolbar.mode and not toolbar.select_action.isChecked()
            assert sum(toolbar._actions[name].isChecked() for name in ("pan", "zoom")) == 1
        toolbar.select_action.trigger()
        assert not toolbar.mode and toolbar.select_action.isChecked()
        toolbar.select_action.trigger()
        assert toolbar.select_action.isChecked()
        toolbar.zoom()
        toolbar.zoom()
        assert not toolbar.mode and toolbar.select_action.isChecked()
    axes = window.data_figure.axes[0]
    window.data_canvas.draw()
    limits = axes.get_ylim()
    point = axes.transData.transform((1, 2))
    event = MouseEvent("button_press_event", window.data_canvas, *point, button=1)
    window.data_toolbar.pan()
    window.data_toolbar.select_axes(event)
    assert not any(line.get_gid() == "selected-result-time" for line in axes.lines)
    window.data_toolbar.select_timepoint()
    window.data_toolbar.select_axes(event)
    marker = next(line for line in axes.lines if line.get_gid() == "selected-result-time")
    np.testing.assert_allclose(marker.get_xdata(), [1, 1])
    assert axes.get_ylim() == limits


def test_channel_labels_toggle_once_and_support_multiple_channels(window):
    recording(window)
    window.sensor_frame = window.frame
    window.sensor_times = window.frame.time.to_numpy()
    window.populate_sensor_channels()
    window.plot_sensor()
    window.result_tabs.setCurrentIndex(3)
    for channel_list in (window.data_channels, window.sensor_channels):
        # Show the relevant workspace before clicking its real viewport.
        if channel_list is window.data_channels:
            window.navigate(0)
            window.data_tabs.setCurrentIndex(1)
        else:
            window.navigate(2)
            window.result_tabs.setCurrentIndex(3)
        QApplication.instance().processEvents()
        for i in range(channel_list.count()):
            item = channel_list.item(i)
            before = item.checkState()
            rect = channel_list.visualItemRect(item)
            QTest.mouseClick(
                channel_list.viewport(),
                Qt.LeftButton,
                pos=QPoint(rect.left() + 55, rect.center().y()),
            )
            assert item.checkState() != before
            QTest.mouseClick(
                channel_list.viewport(),
                Qt.LeftButton,
                pos=QPoint(rect.left() + 10, rect.center().y()),
            )
            assert item.checkState() == before
