"""Graph settings change presentation without changing sensor or result data."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
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
    frame = pd.DataFrame({"time": [0., 1., 2.], "gyroscope_x": [1., 2., 3.],
                          "gyroscope_y": [3., 2., 1.]})
    window.loaded(("sensor.csv", frame))
    window.set_input_channels(["gyroscope_x", "gyroscope_y"])
    window.data_tabs.setCurrentIndex(1)
    return frame


def test_each_graph_has_one_inline_settings_control_under_dark_system_palette(window):
    recording(window)
    for toolbar in (window.data_toolbar, window.plot_toolbar, window.sensor_toolbar):
        actions = [action.text() for action in toolbar.actions() if not action.isSeparator()]
        assert actions.count("Graph settings") == 1
        assert "Subplots" not in actions and "Customize" not in actions
        assert {"Home", "Back", "Forward", "Pan", "Zoom", "Save"} <= set(actions)
        toolbar.settings_action.setChecked(True)
        assert not toolbar.settings.isHidden()
        assert toolbar.settings.palette().color(QPalette.Text) == QColor("#22324a")
        assert toolbar.settings.title.palette().color(QPalette.Active, QPalette.Base) == QColor("#ffffff")
        assert toolbar.settings.title.palette().color(QPalette.Active, QPalette.Text) == QColor("#22324a")
        toolbar.settings_action.setChecked(False)
        assert toolbar.settings.isHidden()
    # The single panel remains usable in the compact Data graph workspace.
    window.resize(960, 650)
    window.data_toolbar.settings_action.setChecked(True)
    QApplication.instance().processEvents()
    panel = window.data_toolbar.settings
    assert panel.apply_button.isVisible()
    assert panel.apply_button.geometry().right() <= panel.width()
    assert window.data_canvas.height() >= 100


def test_graph_settings_apply_reset_and_invalid_bounds_preserve_original_values(window):
    frame = recording(window)
    original = frame.copy(deep=True)
    toolbar = window.data_toolbar
    toolbar.settings_action.setChecked(True)
    panel, axes = toolbar.settings, window.data_figure.axes[0]
    panel.limits_button.click()
    assert not panel.limits_panel.isHidden()
    panel.title.setText("Selected motion channels")
    panel.x_label.setText("Time (s)")
    panel.y_label.setText("Angular velocity")
    automatic, lower, upper = panel.bounds["x"]
    automatic.setChecked(False)
    lower.setText("0.5")
    upper.setText("1.5")
    panel.grid.setChecked(False)
    panel.legend.setChecked(False)
    panel.apply_button.click()
    assert axes.get_xlim() == pytest.approx((.5, 1.5))
    assert axes.get_title(loc="left") == "Selected motion channels"
    assert axes.get_xlabel() == "Time (s)"
    assert not axes.get_legend().get_visible()
    assert not any(line.get_visible() for line in axes.get_xgridlines())
    for line in axes.lines:
        np.testing.assert_array_equal(line.get_ydata(), frame[line.get_label()])
    pd.testing.assert_frame_equal(frame, original)
    # Invalid limits fail atomically, including presentation changes.
    lower.setText("inf")
    panel.title.setText("Do not apply this")
    panel.apply_button.click()
    assert not panel.error.isHidden()
    assert axes.get_xlim() == pytest.approx((.5, 1.5))
    assert axes.get_title(loc="left") == "Selected motion channels"
    panel.reset_button.click()
    assert panel.error.isHidden()
    assert axes.get_autoscalex_on()
    assert axes.get_xlim()[0] < 0 and axes.get_xlim()[1] > 2
    assert axes.get_title(loc="left") == ""
    assert axes.get_xlabel() == "Time (file units)"
    assert axes.get_legend().get_visible()


def test_date_limits_accept_iso_timestamps_and_graph_changes_refresh_settings(window):
    frame = pd.DataFrame({"time": pd.date_range("2026-10-07", periods=3, freq="1s", tz="Europe/Amsterdam"),
                          "gyroscope_x": [1., 2., 3.], "gyroscope_y": [3., 2., 1.]})
    window.loaded(("dated.csv", frame))
    window.data_toolbar.settings_action.setChecked(True)
    panel = window.data_toolbar.settings
    automatic, lower, upper = panel.bounds["x"]
    assert lower.toolTip() == "ISO date/time"
    automatic.setChecked(False)
    lower.setText(frame.time.iloc[0].isoformat())
    upper.setText(frame.time.iloc[1].isoformat())
    panel.apply()
    axes = window.data_figure.axes[0]
    assert axes.get_xlim() == pytest.approx(dates.date2num(frame.time.iloc[:2].to_numpy()))
    window.set_input_channels(["gyroscope_y"])
    assert panel.y_label.text() == "gyroscope_y"
    assert automatic.isChecked()
    assert panel.error.isHidden()
    assert window.data_toolbar._nav_stack() is None


def test_result_and_sensor_context_settings_use_current_graph_without_mutating_tables(window):
    recording(window)
    result = pd.DataFrame({"time": [0., 1., 2.], "metric": [10., 20., 30.]})
    window.analyzed({"quantifications": {"tremor": result}})
    window.plot_toolbar.settings_action.setChecked(True)
    panel = window.plot_toolbar.settings
    panel.y_label.setText("Derived metric")
    panel.apply()
    assert window.figure.axes[0].get_ylabel() == "Derived metric"
    pd.testing.assert_frame_equal(window.active_frame, result)
    window.sensor_frame = window.frame
    window.sensor_times = window.frame.time.to_numpy()
    window.populate_sensor_channels()
    window.plot_sensor()
    window.sensor_toolbar.settings_action.setChecked(True)
    panel = window.sensor_toolbar.settings
    panel.y_label.setText("Raw sensor")
    panel.apply()
    assert window.sensor_figure.axes[0].get_ylabel() == "Raw sensor"
    np.testing.assert_array_equal(window.sensor_figure.axes[0].lines[0].get_ydata(), window.frame.gyroscope_x)
