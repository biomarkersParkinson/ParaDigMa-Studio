"""Cursor modes and axis limits change presentation without changing analysis data."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from matplotlib.backend_bases import MouseEvent
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLineEdit, QPushButton

from paradigma_studio.app import MainWindow
from paradigma_studio.epoch_profile import parse_profile_time
from paradigma_studio.plot_controls import _format_limit


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
        assert {"Home", "Back", "Forward", "Save"} <= set(actions)
        assert ("Select time interval" if toolbar is window.plot_toolbar else "Zoom") in actions
        assert ("Pan" in actions) == (toolbar is not window.plot_toolbar)
        assert ("Select timepoint" in actions) == (toolbar is window.plot_toolbar)
        assert not {"Graph settings", "Subplots", "Customize"} & set(actions)
        toolbar.settings_action.setChecked(True)
        panel = toolbar.settings
        assert not panel.isHidden() and not panel.limits_panel.isHidden()
        assert not any(
            hasattr(panel, name)
            for name in ("title", "x_label", "y_label", "grid", "legend", "limits_button")
        )
        assert set(panel.findChildren(QLineEdit)) == {
            edit for _, lower, upper in panel.bounds.values() for edit in (lower, upper)
        }
        assert set(panel.findChildren(QAbstractButton)) == {
            panel.reset_button,
            panel.close_button,
            *(automatic for automatic, _, _ in panel.bounds.values()),
        }
        assert not panel.findChildren(QComboBox)
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
    assert window.data_toolbar.settings.close_button.isVisible()
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
    panel.bounds["y"][2].editingFinished.emit()
    assert axes.get_xlim() == pytest.approx((0.5, 1.5))
    assert axes.get_ylim() == pytest.approx((1.2, 2.8))
    automatic, lower, upper = panel.bounds["x"]
    lower.setText("0")
    upper.setText("2")
    panel.bounds["y"][1].setText("inf")
    panel.bounds["y"][1].editingFinished.emit()
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


def test_reset_from_another_result_graph_restores_shared_time_and_selected_y_limits(window):
    results = {
        "quantifications": {
            "tremor": pd.DataFrame({"time": [0.0, 1.0, 2.0], "tremor_power": [2.0, 20.0, 200.0]}),
            "pulse_rate": pd.DataFrame({"time": [0.0, 1.0, 2.0], "pulse_rate": [60.0, 70.0, 80.0]}),
        }
    }
    window.analyzed(results)
    first, selected = window.figure.axes
    initial_x = selected.get_xlim()
    first.set_ylim(1000, 2000)
    toolbar = window.plot_toolbar
    toolbar.active_axes = selected
    toolbar.settings_action.setChecked(True)
    panel = toolbar.settings
    for axis, values in (("x", ("0.5", "1.5")), ("y", ("0", "10"))):
        automatic, lower, upper = panel.bounds[axis]
        automatic.setChecked(False)
        lower.setText(values[0])
        upper.setText(values[1])
    panel.apply()
    assert selected.get_ylim() == (0, 10)
    panel.reset_button.click()
    assert all(ax.get_xlim() == pytest.approx(initial_x) for ax in window.figure.axes)
    assert selected.get_autoscaley_on()
    assert selected.get_ylim()[0] <= 60 and selected.get_ylim()[1] > 80
    assert first.get_ylim() == (1000, 2000)
    pd.testing.assert_frame_equal(
        window._result_state.tables["quantifications/pulse_rate"],
        results["quantifications"]["pulse_rate"],
    )


def test_result_and_sensor_limits_use_clicked_graph_and_keep_original_tables(window):
    recording(window)
    result = pd.DataFrame({"time": [0.0, 1.0, 2.0], "metric": [10.0, 20.0, 30.0]})
    window.analyzed({"quantifications": {"tremor": result}})
    for toolbar, figure in (
        (window.plot_toolbar, window.figure),
        (window.sensor_toolbar, window.sensor_figure),
    ):
        if toolbar is window.sensor_toolbar:
            window._sensor_state.sensor_frame = window._input_state.frame
            window._sensor_state.sensor_times = window._input_state.frame.time.to_numpy()
            window.populate_sensor_channels()
            window.plot_sensor()
        toolbar.settings_action.setChecked(True)
        automatic, lower, upper = toolbar.settings.bounds["y"]
        automatic.setChecked(False)
        lower.setText("0")
        upper.setText("40")
        toolbar.settings.apply()
        assert figure.axes[0].get_ylim() == pytest.approx((0, 40))
    pd.testing.assert_frame_equal(window._result_state.active_frame, result)
    np.testing.assert_array_equal(
        window.sensor_figure.axes[0].lines[0].get_ydata(), window._input_state.frame.gyroscope_x
    )


def test_cursor_modes_are_exclusive_and_default_to_selection(window):
    recording(window)
    for toolbar in (window.plot_toolbar,):
        assert toolbar.select_action.isChecked() and not toolbar.mode
        assert not toolbar.select_action.icon().pixmap(24, 24).isNull()
        assert "pan" not in toolbar._actions
        toolbar._actions["zoom"].trigger()
        assert toolbar.mode and not toolbar.select_action.isChecked()
        assert toolbar._actions["zoom"].isChecked()
        toolbar.select_action.trigger()
        assert not toolbar.mode and toolbar.select_action.isChecked()
        toolbar.select_action.trigger()
        assert toolbar.select_action.isChecked()
        toolbar.zoom()
        toolbar.zoom()
        assert not toolbar.mode and toolbar.select_action.isChecked()


def test_raw_graphs_only_navigate_and_do_not_select_a_new_time(window):
    recording(window)
    result = pd.DataFrame({"time": [1.0], "metric": [2.0]})
    window._result_state.provenance = {"settings": {"skip_preparation": True}}
    window.analyzed({"quantifications": {"tremor": result}})
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    window.inspect_sensor_context()
    for toolbar, canvas in (
        (window.data_toolbar, window.data_canvas),
        (window.sensor_toolbar, window.sensor_canvas),
    ):
        assert toolbar.select_action is None and toolbar._actions["pan"].isChecked()
        assert "Select timepoint" not in [action.text() for action in toolbar.actions()]
        original = [
            (line.get_gid(), tuple(line.get_xdata()))
            for ax in canvas.figure.axes
            for line in ax.lines
            if line.get_gid() is not None
        ]
        if canvas is window.sensor_canvas:
            assert any(gid == "selected-result-time" for gid, _ in original)
        else:
            assert not original
        toolbar.pan()  # Even with navigation switched off, a click is not selection.
        ax = canvas.figure.axes[0]
        toolbar.select_axes(
            MouseEvent("button_press_event", canvas, *ax.transAxes.transform((0.7, 0.5)), button=1)
        )
        assert [
            (line.get_gid(), tuple(line.get_xdata()))
            for ax in canvas.figure.axes
            for line in ax.lines
            if line.get_gid() is not None
        ] == original
        toolbar.zoom()
        assert toolbar._actions["zoom"].isChecked() and not toolbar._actions["pan"].isChecked()
        toolbar.pan()
        assert toolbar._actions["pan"].isChecked() and not toolbar._actions["zoom"].isChecked()


def test_channel_labels_toggle_once_and_support_multiple_channels(window):
    recording(window)
    window._sensor_state.sensor_frame = window._input_state.frame
    window._sensor_state.sensor_times = window._input_state.frame.time.to_numpy()
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


def test_axis_limits_shade_only_the_selected_graph_and_restore_backgrounds(window):
    recording(window)
    window._input_state.frame["accelerometer_x"] = [0.1, 0.2, 0.3]
    window.populate_input_channels()
    window.set_input_channels(["gyroscope_x", "accelerometer_x"])
    toolbar, figure = window.data_toolbar, window.data_figure
    assert len(figure.axes) == 2
    colors = [ax.get_facecolor() for ax in figure.axes]
    toolbar.settings_action.setChecked(True)
    assert figure.axes[0].get_facecolor() != colors[0]
    assert figure.axes[1].get_facecolor() == colors[1]
    toolbar.select_axes(
        MouseEvent(
            "button_press_event",
            window.data_canvas,
            *figure.axes[1].transAxes.transform((0.5, 0.5)),
            button=1,
        )
    )
    assert toolbar.settings.axes() is figure.axes[1]
    assert figure.axes[0].get_facecolor() == colors[0]
    assert figure.axes[1].get_facecolor() != colors[1]
    toolbar.settings_action.setChecked(False)
    assert [ax.get_facecolor() for ax in figure.axes] == colors


def test_limit_edits_apply_on_enter_and_blur_with_reset_and_close_on_hint_row(window):
    recording(window)
    toolbar = window.data_toolbar
    toolbar.settings_action.setChecked(True)
    panel = toolbar.settings
    automatic, lower, upper = panel.bounds["y"]
    automatic.click()
    assert not automatic.isChecked()
    lower.setFocus()
    lower.selectAll()
    QTest.keyClicks(lower, "1.2")
    QTest.keyClick(lower, Qt.Key_Return)
    assert window.data_figure.axes[0].get_ylim()[0] == pytest.approx(1.2)
    upper.setFocus()
    upper.selectAll()
    QTest.keyClicks(upper, "2.8")
    panel.close_button.setFocus()  # Leaving the editor also commits its value.
    QApplication.instance().processEvents()
    assert window.data_figure.axes[0].get_ylim() == pytest.approx((1.2, 2.8))
    assert not hasattr(panel, "apply_button")
    assert set(panel.findChildren(QPushButton)) == {panel.reset_button, panel.close_button}
    row = panel.layout().itemAtPosition(3, 0).layout()
    assert all(
        row.indexOf(widget) >= 0
        for widget in (panel.graph_hint, panel.reset_button, panel.close_button)
    )
    assert panel.graph_hint.isVisible()
    panel.reset_button.click()
    assert window.data_figure.axes[0].get_autoscaley_on()
    panel.close_button.click()
    assert panel.isHidden() and not toolbar.settings_action.isChecked()
    assert toolbar._highlighted_axes is None


def assert_limit_fields_match_axes(panel):
    axes = panel.axes()
    for axis, (_, lower, upper) in panel.bounds.items():
        limits = getattr(axes, f"get_{axis}lim")()
        parse = (
            parse_profile_time
            if axis == "x" and getattr(axes, "_paradigma_profile", False)
            else float
        )
        assert [parse(edit.text()) for edit in (lower, upper)] == [
            round(value, 3) for value in limits
        ]


@pytest.mark.parametrize("view", range(4))
def test_limits_follow_zoom_buttons_scroll_history_and_home_on_selected_shared_graph(window, view):
    times = np.arange(2000.0)
    frame = pd.DataFrame({"time": times, "metric_a": times / 10, "metric_b": times / 20})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_graph_view.setCurrentIndex(view)
    toolbar = window.plot_toolbar
    toolbar.active_axes = window.figure.axes[-1]
    toolbar.settings_action.setChecked(True)
    for action in ("zoom_in", "zoom_out", "zoom_in"):
        toolbar._actions[action].trigger()
        QApplication.instance().processEvents()
        assert_limit_fields_match_axes(toolbar.settings)
    bar = window.result_time_scroll
    bar.setValue(bar.maximum() // 3)
    QApplication.instance().processEvents()
    assert_limit_fields_match_axes(toolbar.settings)
    for action in (toolbar.back, toolbar.forward, toolbar.home):
        action()
        QApplication.instance().processEvents()
        assert_limit_fields_match_axes(toolbar.settings)


def test_limit_display_rounding_never_changes_unedited_axes_or_user_precision(window):
    recording(window)
    toolbar = window.data_toolbar
    axes = window.data_figure.axes[0]
    exact_x = (0.123456789, 1.876543211)
    exact_y = (-2.987654321, 3.123456789)
    axes.set_xlim(*exact_x)
    axes.set_ylim(*exact_y)
    toolbar.settings_action.setChecked(True)
    panel = toolbar.settings
    assert [edit.text() for edit in panel.bounds["x"][1:]] == ["0.123", "1.877"]
    assert [edit.text() for edit in panel.bounds["y"][1:]] == ["-2.988", "3.123"]
    panel.bounds["y"][2].setText("4.123456789")
    panel.bounds["y"][2].editingFinished.emit()
    assert axes.get_xlim() == exact_x
    assert axes.get_ylim() == (exact_y[0], 4.123456789)
    assert panel.bounds["y"][2].text() == "4.123"
    panel.apply()  # Moving focus without editing must not round the view either.
    assert axes.get_xlim() == exact_x
    assert axes.get_ylim() == (exact_y[0], 4.123456789)


@pytest.mark.parametrize(
    "value,expected",
    [(1.234567, "1.235"), (1.000001, "1"), (-0.0004, "0"), (-9.9996, "-10"), (9.9996, "10")],
)
def test_numeric_limit_display_has_at_most_three_decimals_without_padding(value, expected):
    assert _format_limit(value) == expected


@pytest.mark.parametrize("clock", ["calendar", "profile"])
def test_clock_limit_fields_round_milliseconds_without_changing_the_view(window, clock):
    window._result_state.provenance = {
        "display_clock": {"origin": "2026-10-14T00:00:00+05:45", "timezone": "Asia/Kathmandu"}
    }
    times = np.arange(0, 3 * 86400, 60.0)
    frame = pd.DataFrame({"time": times, "metric": 2 + np.sin(times / 1000)})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    if clock == "profile":
        window.result_graph_view.setCurrentIndex(3)
        exact = (59.9996, 86399.9996)
        expected = ["00:01", "24:00"]
    else:
        stamps = pd.to_datetime(
            ["2026-10-14T12:00:00.123456+05:45", "2026-10-14T12:00:01.987654+05:45"]
        )
        exact = tuple(dates.date2num(stamps.to_pydatetime()))
        expected = ["2026-10-14T12:00:00.123+05:45", "2026-10-14T12:00:01.988+05:45"]
    axes, toolbar = window.figure.axes[0], window.plot_toolbar
    axes.set_xlim(*exact)
    toolbar.settings_action.setChecked(True)
    panel = toolbar.settings
    assert [edit.text() for edit in panel.bounds["x"][1:]] == expected
    panel.bounds["y"][0].setChecked(False)
    panel.bounds["y"][2].setText("10.123456789")
    panel.apply()
    assert axes.get_xlim() == exact
    assert axes.get_ylim()[1] == 10.123456789
    assert panel.bounds["y"][2].text() == "10.123"
    toolbar._actions["zoom_in"].trigger()
    QApplication.instance().processEvents()
    parse = parse_profile_time if clock == "profile" else dates.datestr2num
    tolerance = 0.00051 if clock == "profile" else 0.00051 / 86400
    for edit, value in zip(panel.bounds["x"][1:], axes.get_xlim(), strict=True):
        assert float(parse(edit.text())) == pytest.approx(value, abs=tolerance, rel=0)


@pytest.mark.parametrize("workspace", ["data", "sensor"])
def test_raw_limit_fields_follow_pan_zoom_and_silent_changes(window, workspace):
    recording(window)
    if workspace == "sensor":
        window._sensor_state.sensor_frame = window._input_state.frame
        window._sensor_state.sensor_times = window._input_state.frame.time.to_numpy()
        window.populate_sensor_channels()
        window.plot_sensor()
        window.result_tabs.setCurrentIndex(3)
        toolbar, canvas = window.sensor_toolbar, window.sensor_canvas
    else:
        toolbar, canvas = window.data_toolbar, window.data_canvas
    toolbar.settings_action.setChecked(True)
    axes = toolbar.settings.axes()
    canvas.draw()
    x, y = axes.transAxes.transform((0.5, 0.5))
    toolbar.press_pan(MouseEvent("button_press_event", canvas, x, y, button=1))
    toolbar.drag_pan(MouseEvent("motion_notify_event", canvas, x + 30, y + 10, buttons={1}))
    assert_limit_fields_match_axes(toolbar.settings)
    toolbar.release_pan(MouseEvent("button_release_event", canvas, x + 30, y + 10, button=1))
    toolbar.zoom()
    start, end = axes.transAxes.transform([(0.25, 0.3), (0.75, 0.7)])
    toolbar.press_zoom(MouseEvent("button_press_event", canvas, *start, button=1))
    toolbar.release_zoom(MouseEvent("button_release_event", canvas, *end, button=1))
    assert_limit_fields_match_axes(toolbar.settings)
    axes.set_xlim(0.234567, 0.987654, emit=False)
    canvas.draw()
    assert_limit_fields_match_axes(toolbar.settings)


def test_unchanged_redraw_preserves_pending_limit_edits_and_validation_error(window):
    recording(window)
    toolbar = window.data_toolbar
    toolbar.settings_action.setChecked(True)
    panel = toolbar.settings
    panel.bounds["y"][0].setChecked(False)
    panel.bounds["y"][1].setText("invalid")
    panel.apply()
    assert not panel.error.isHidden()
    window.data_canvas.draw()
    assert panel.bounds["y"][1].text() == "invalid"
    assert not panel.error.isHidden()
    panel.axes().set_ylim(-1.123456, 5.987654)
    assert_limit_fields_match_axes(panel)
    assert panel.error.isHidden()


def test_observers_release_replaced_graphs_and_reopening_reads_the_current_limits(window):
    import gc
    import weakref

    recording(window)
    toolbar = window.data_toolbar
    toolbar.settings_action.setChecked(True)
    previous = weakref.ref(toolbar.settings.axes())
    window.set_input_channels(["gyroscope_y"])
    QApplication.instance().processEvents()
    gc.collect()
    assert previous() is None
    panel = toolbar.settings
    assert_limit_fields_match_axes(panel)
    toolbar.settings_action.setChecked(False)
    panel.axes().set_xlim(0.123456, 0.987654)
    toolbar.settings_action.setChecked(True)
    assert_limit_fields_match_axes(panel)


def test_tiny_rounded_limits_and_retyping_a_displayed_value_preserve_edit_intent(window):
    recording(window)
    axes, toolbar = window.data_figure.axes[0], window.data_toolbar
    exact = (-0.0004, 0.0004)
    axes.set_ylim(*exact)
    toolbar.settings_action.setChecked(True)
    panel = toolbar.settings
    assert [edit.text() for edit in panel.bounds["y"][1:]] == ["0", "0"]
    panel.apply()
    assert axes.get_ylim() == exact
    axes.set_ylim(-0.123456, 1.123456)
    lower = panel.bounds["y"][1]
    lower.setFocus()
    lower.selectAll()
    QTest.keyClicks(lower, "-0.123")
    QTest.keyClick(lower, Qt.Key_Return)
    assert axes.get_ylim() == (-0.123, 1.123456)
