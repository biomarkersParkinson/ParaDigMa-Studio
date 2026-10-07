"""Time-only selection, categorical rasters and actual Qt wheel delivery."""
import os
from copy import deepcopy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from paradigma_desktop.app import MainWindow
from paradigma_desktop.plotting import binary_indicator
from paradigma_desktop.time_controls import TimeField


@pytest.fixture
def window(tmp_path):
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")  # Match the style selected by app.main().
    widget = MainWindow(history_dir=tmp_path)
    widget.resize(1050, 720)
    widget.show()
    yield widget
    widget.close()
    application.processEvents()


def test_analysis_help_is_clickable_without_parameter_hover_text(window):
    for child in window.pages.widget(1).findChildren(QWidget):
        assert not child.toolTip()
    info, explanation = window.analysis_help["Device axes"]
    info.click()
    assert not explanation.isHidden()


def test_plot_tree_is_graph_selector_and_table_dataset_selection_remains(window):
    frame = pd.DataFrame({"time": [0., 1., 2.], "power": [2., 3., 4.], "other": [5., 6., 7.]})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    assert window.dataset_field.isHidden() and window.y_column.isHidden()
    item = window._series_items[("quantifications/tremor", "other")]
    item.setCheckState(0, Qt.Checked)
    window.result_series.setCurrentItem(item)
    assert window.y_column.currentData() == "other"
    assert len(window.selected_result_series()) == 2
    item.setCheckState(0, Qt.Unchecked)
    assert len(window.selected_result_series()) == 1
    window.result_tabs.setCurrentIndex(2)
    assert not window.dataset_field.isHidden() and window.y_column.isHidden()
    assert not hasattr(window, "filter_column") and not hasattr(window, "participant")


def test_binary_raster_preserves_timestamps_states_missingness_and_rare_events(window):
    t = np.arange(20002, dtype=float)
    values = np.zeros(len(t)); values[1] = 1.; values[2] = np.nan
    frame = pd.DataFrame({"time": t, "pred_event": values})
    original = frame.copy(deep=True)
    window.analyzed({"quantifications": {"tremor": frame}})
    axes = window.figure.axes[0]
    assert not axes.lines
    assert [v.get_text() for v in axes.get_yticklabels()] == ["Absent · 0", "Present · 1"]
    offsets = axes.collections[0].get_offsets()
    valid = np.isfinite(values)
    np.testing.assert_array_equal(offsets[:, 0], t[valid])
    np.testing.assert_array_equal(offsets[:, 1], values[valid])
    assert offsets[1].tolist() == [1., 1.]
    window.time_from.setText("1"); window.time_to.setText("3"); window.apply_filters()
    np.testing.assert_array_equal(window.figure.axes[0].collections[0].get_offsets(), [[1., 1.], [3., 0.]])
    pd.testing.assert_frame_equal(frame, original)
    assert not binary_indicator(pd.Series([0., 1.]), "pred_event_proba")
    assert not binary_indicator(pd.Series([0., 1.]), "gyroscope_x")
    assert binary_indicator(pd.Series([1., 1.]), "pred_event")


def test_raw_graphs_separate_states_and_signals_without_changing_values(window):
    raw = pd.DataFrame({"time": [0., 1., 2.], "gyroscope_x": [1., 2., 3.], "wear_flag": [0, 1, 0]})
    window.loaded(("sensor.csv", raw))
    window.set_input_channels(["gyroscope_x", "wear_flag"])
    signal, states = window.data_figure.axes
    np.testing.assert_array_equal(signal.lines[0].get_ydata(), raw.gyroscope_x)
    assert not states.lines
    np.testing.assert_array_equal(states.collections[0].get_offsets(), [[0., 0.], [1., 1.], [2., 0.]])


def test_calendar_filter_preserves_source_precision_and_filters_all_outputs(window):
    start = pd.Timestamp("2026-10-07T12:00:00.123456789+02:00")
    raw = pd.DataFrame({"time": [0., 1., 2.], "time_dt": start + pd.to_timedelta([0., 1., 2.], unit="s")})
    window.loaded(("sensor.csv", raw))
    window.provenance = {"settings": {"skip_preparation": True}}
    result = {"quantifications": {name: pd.DataFrame({"time": [0., 1., 2.], "metric": [4., 5., 6.]})
                                for name in ("tremor", "pulse_rate")}}
    window.analyzed(result)
    original = deepcopy(window.display_clock)
    window.apply_filters()
    assert window.display_clock == original
    assert window.clock_input.text() == start.isoformat()
    assert window.time_from.calendar.calendarPopup()
    window.time_to.use.setChecked(True)
    window.apply_filters()
    assert all(positions.tolist() == [0, 1, 2] for _, positions in window._detail_selections.values())
    window.time_to.clear()
    window.time_from.use.setChecked(True)
    window.time_from.calendar.setDateTime(window.time_from.calendar.dateTime().addMSecs(1500))
    window.apply_filters()
    assert all(positions.tolist() == [2] for _, positions in window._detail_selections.values())
    assert not window.filter_status.text()
    assert "Calendar times" in window.time_zone.text()
    window.clock_input.clear()
    window.apply_filters()
    assert window.display_clock is None
    assert all(positions.tolist() == [2] for _, positions in window._detail_selections.values())
    assert window.time_from.editors.currentWidget() is window.time_from.seconds
    assert not window.filter_status.text()


def test_calendar_clock_preserves_named_timezone_across_dst():
    application = QApplication.instance() or QApplication([])
    field = TimeField("From")
    field.set_clock({"origin": "2026-10-25T00:30:00+02:00", "timezone": "Europe/Amsterdam"})
    field.setText("10800")
    assert field.calendar.dateTime().toString(Qt.ISODateWithMs) == "2026-10-25T02:30:00.000+01:00"
    field.calendar.setDateTime(field.calendar.dateTime().addSecs(3600))
    assert field.text() == "2026-10-25T03:30:00.000+01:00"
    field.set_clock(None)
    assert float(field.text()) == 14400.
    field.close()
    application.processEvents()


def test_result_canvas_accepts_mouse_wheel_and_touchpad_scrolling(window):
    frame = pd.DataFrame({"time": [0., 1., 2.], **{f"metric_{i}": [2., 3., 4.] for i in range(8)}})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.plot()
    QApplication.instance().processEvents()
    bar = window.graph_scroll.verticalScrollBar()
    assert bar.maximum() > 200
    def wheel(pixels, angle):
        event = QWheelEvent(QPointF(30, 30), QPointF(window.canvas.mapToGlobal(QPoint(30, 30))),
                            QPoint(0, pixels), QPoint(0, angle), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
        QApplication.sendEvent(window.canvas, event)
        assert event.isAccepted()
    wheel(-70, 0)
    assert bar.value() == 70
    wheel(0, -120)
    assert bar.value() > 70
    wheel(1000, 0)
    assert bar.value() == 0


def test_calendar_fields_remain_readable_in_compact_results(window):
    window.analyzed({"quantifications": {"tremor": pd.DataFrame({"time": [0., 1.], "power": [2., 3.]})}})
    window.result_tabs.setCurrentIndex(1)
    window.filters_toggle.setChecked(True)
    window.show_notice("Analysis warning: review the partial results in Runs.")
    window.resize(960, 720)
    QTest.qWait(50)  # Let nested layout/paint requests settle on Windows too.
    assert window.time_grid.getItemPosition(window.time_grid.indexOf(window.time_fields[0])) == (0, 0, 1, 2)
    for field in (window.clock_input, window.time_from, window.time_to):
        assert field.editors.currentWidget().height() >= 38
        assert field.editors.currentWidget().width() >= field.editors.currentWidget().minimumSizeHint().width()
        assert field.visibleRegion().boundingRect().height() == field.height()
    origin, lower, upper = window.time_fields
    assert origin.geometry().bottom() < lower.geometry().top()
    assert lower.geometry().bottom() < window.time_zone.geometry().top()
    for child in (window.time_zone, window.filter_apply, window.filter_reset):
        assert child.isVisible(), f"{child.objectName() or type(child).__name__} is hidden"
        assert child.visibleRegion().boundingRect().contains(child.rect()), (
            f"Filter control is clipped: {child.objectName() or type(child).__name__}, "
            f"geometry={child.geometry()}, visible={child.visibleRegion().boundingRect()}, "
            f"screen={window.screen().geometry()}"
        )
    assert window.filters_panel.mapTo(window, QPoint(0, window.filters_panel.height())).y() <= window.result_tabs.mapTo(window, QPoint(0, 0)).y()
    window.resize(1450, 920)
    QTest.qWait(50)
    assert window.time_grid.getItemPosition(window.time_grid.indexOf(window.time_fields[2])) == (0, 2, 1, 1)
