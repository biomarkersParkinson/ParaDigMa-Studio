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
from PySide6.QtWidgets import QApplication, QWidget, QStyle, QStyleOptionButton

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


@pytest.mark.parametrize("editor_minimum_width", [0, 382])
def test_calendar_fields_remain_readable_in_compact_results(window, editor_minimum_width):
    # Reproduce Windows-sized control hints independently of the host OS.
    for field in (window.clock_input, window.time_from, window.time_to):
        field.calendar.setMinimumWidth(editor_minimum_width)
        field.seconds.setMinimumWidth(editor_minimum_width)
    window.analyzed({"quantifications": {"tremor": pd.DataFrame({"time": [0., 1.], "power": [2., 3.]})}})
    window.result_tabs.setCurrentIndex(1)
    window.filters_toggle.setChecked(True)
    window.show_notice("Analysis warning: review the partial results in Runs.")
    window.resize(960, 720)
    QTest.qWait(50)  # Let nested layout/paint requests settle on Windows too.
    assert window._time_field_columns in (1, 2, 3)
    if editor_minimum_width:
        assert window._time_field_columns == 1
    for field in (window.clock_input, window.time_from, window.time_to):
        assert field.editors.currentWidget().height() >= 38
        assert field.editors.currentWidget().width() >= field.editors.currentWidget().minimumSizeHint().width()
        window.results_scroll.ensureWidgetVisible(field, 0, 0)
        QTest.qWait(20)
        assert field.visibleRegion().boundingRect().contains(field.rect())
    origin, lower, upper = window.time_fields
    if window._time_field_columns < 3:
        assert origin.geometry().bottom() < lower.geometry().top()
    else:
        assert origin.geometry().top() == lower.geometry().top() == upper.geometry().top()
    assert lower.geometry().bottom() < window.time_zone.geometry().top()
    for child in (window.time_zone, window.filter_apply, window.filter_reset):
        window.results_scroll.ensureWidgetVisible(child, 0, 0)
        QTest.qWait(20)
        assert child.isVisible(), f"{child.objectName() or type(child).__name__} is hidden"
        assert child.visibleRegion().boundingRect().contains(child.rect()), (
            f"Filter control is clipped: {child.objectName() or type(child).__name__}, "
            f"geometry={child.geometry()}, visible={child.visibleRegion().boundingRect()}, "
            f"screen={window.screen().geometry()}"
        )
    window.results_scroll.verticalScrollBar().setValue(0)
    QTest.qWait(20)
    tab_bar = window.result_tabs.tabBar()
    assert tab_bar.mapTo(window, QPoint(0, tab_bar.height())).y() <= window.filters_panel.mapTo(window, QPoint(0, 0)).y()
    window.resize(1800, 920)
    QTest.qWait(50)
    assert window._time_field_columns == 3
    assert window.time_grid.getItemPosition(window.time_grid.indexOf(window.time_fields[2])) == (0, 2, 1, 1)


def test_results_tabs_stay_anchored_across_views_filters_and_scrolling(window):
    window.analyzed({"quantifications": {"tremor": pd.DataFrame({"time": [0., 1.], "power": [2., 3.]})}})
    bar = window.result_tabs.tabBar()

    def positions():
        return [bar.mapTo(window, bar.tabRect(i).topLeft()) for i in range(3)]

    QTest.qWait(30)
    original = positions()
    assert original[0].y() < 125
    for filters in (False, True):
        window.filters_toggle.setChecked(filters)
        for index in (1, 2, 0, 2, 1):
            window.result_tabs.setCurrentIndex(index)
            QTest.qWait(30)
            assert positions() == original
            export_center = window.export_button.mapTo(window, window.export_button.rect().center()).y()
            assert bar.mapTo(window, QPoint(0, 0)).y() <= export_center <= bar.mapTo(window, QPoint(0, bar.height())).y()
            window.results_scroll.verticalScrollBar().setValue(window.results_scroll.verticalScrollBar().maximum())
            QTest.qWait(20)
            assert positions() == original
    assert window.dataset_field.isHidden()
    assert not window.filters_toggle.isHidden()
    assert not window.csv_button.isHidden()
    window.result_tabs.setCurrentIndex(0)
    assert window.filters_toggle.isHidden() and window.csv_button.isHidden()
    assert not window.export_button.isHidden()


def test_sidebar_hover_expands_without_moving_page_and_about_stays_in_footer(window):
    window.navigate(2)
    QTest.mouseMove(window.pages, QPoint(300, 100))
    QTest.qWait(150)
    assert window.sidebar_collapsed and window.sidebar.width() == 68
    position = window.result_tabs.mapTo(window, QPoint(0, 0))
    QTest.mouseMove(window.sidebar, QPoint(30, 100))
    QTest.qWait(160)
    assert not window.sidebar_collapsed and window.sidebar.width() == window.sidebar.expanded_width
    assert window.sidebar.expanded_width >= 194
    assert [item.text() for item in window.nav_buttons] == [f"{i + 1}    {title}" for i, title in enumerate(window.SECTIONS)]
    assert window.result_tabs.mapTo(window, QPoint(0, 0)) == position
    QTest.mouseMove(window.pages, QPoint(300, 100))
    QTest.qWait(160)
    assert window.sidebar_collapsed and window.sidebar.width() == 68
    assert window.result_tabs.mapTo(window, QPoint(0, 0)) == position
    assert window.about_button.text() == "About"
    assert window.sidebar.isAncestorOf(window.about_button)
    assert window.about_button.geometry().bottom() > window.sidebar.height() - 70
    option = QStyleOptionButton()
    window.about_button.initStyleOption(option)
    contents = window.about_button.style().subElementRect(QStyle.SE_PushButtonContents, option, window.about_button)
    text = window.about_button.fontMetrics().boundingRect(contents, Qt.AlignLeft | Qt.AlignVCenter, "About")
    assert window.about_button.visibleRegion().contains(text)
    assert not hasattr(window, "local_label") and not hasattr(window, "collapse_button")
    window.about_button.click()
    assert window._acknowledgements_dialog.isVisible()
    window._acknowledgements_dialog.close()


@pytest.mark.parametrize("caption_font_px", [None, 22])
def test_sidebar_text_anchors_stay_fixed_through_animation(window, caption_font_px):
    QTest.mouseMove(window.pages, QPoint(300, 100))
    QTest.qWait(150)
    sidebar = window.sidebar
    if caption_font_px is not None:
        # Reproduce the wider native Windows font metrics on any platform.
        window.brand_caption.setStyleSheet(f"font-size: {caption_font_px}px;")
    sidebar.setExpanded(False, animated=False)
    QApplication.instance().processEvents()
    controls = [*window.nav_buttons, window.about_button, window.brand_icon, window.brand, window.brand_caption]
    positions = [(widget.mapTo(window, QPoint(0, 0)), widget.size()) for widget in controls]
    if caption_font_px is not None:
        assert window.brand_caption.fontMetrics().horizontalAdvance(window.brand_caption.text()) > 170
        assert sidebar.expanded_width > 194

    def text_box(widget, text):
        option = QStyleOptionButton()
        widget.initStyleOption(option)
        contents = widget.style().subElementRect(QStyle.SE_PushButtonContents, option, widget)
        return widget.fontMetrics().boundingRect(contents, Qt.AlignLeft | Qt.AlignVCenter, text)

    anchors = [widget.mapTo(window, text_box(widget, text).topLeft())
               for widget, text in zip([*window.nav_buttons, window.about_button], ["1", "2", "3", "4", "About"])]
    assert len({point.x() for point in anchors}) == 1  # About shares the number alignment.
    assert window.about_button.visibleRegion().contains(text_box(window.about_button, "About"))
    for expanded in (True, False):
        sidebar.setExpanded(expanded)
        for elapsed in (0, 20, 40, 60, 90, 120):
            sidebar.animation.setCurrentTime(elapsed)
            QApplication.instance().processEvents()
            assert [(widget.mapTo(window, QPoint(0, 0)), widget.size()) for widget in controls] == positions
            assert not window.brand_caption.wordWrap() and not window.brand.wordWrap()
            assert window.brand_caption.height() == window.brand_caption.sizeHint().height()
            assert window.brand_caption.fontMetrics().horizontalAdvance(window.brand_caption.text()) <= window.brand_caption.width()
            current = [widget.mapTo(window, text_box(widget, text).topLeft())
                       for widget, text in zip([*window.nav_buttons, window.about_button], ["1", "2", "3", "4", "About"])]
            assert current == anchors
            assert window.about_button.visibleRegion().contains(text_box(window.about_button, "About"))


def test_canvas_wheel_reaches_outer_results_scroll_when_single_graph_fits(window):
    for field in (window.clock_input, window.time_from, window.time_to):
        field.calendar.setMinimumWidth(382)
        field.seconds.setMinimumWidth(382)
    window.analyzed({"quantifications": {"tremor": pd.DataFrame({"time": [0., 1.], "power": [2., 3.]})}})
    window.result_tabs.setCurrentIndex(1)
    window.filters_toggle.setChecked(True)
    window.resize(960, 650)
    QTest.qWait(50)
    inner = window.graph_scroll.verticalScrollBar()
    outer = window.results_scroll.verticalScrollBar()
    assert inner.maximum() == 0 and outer.maximum() > 120
    tab_position = window.result_tabs.tabBar().mapTo(window, QPoint(0, 0))
    outer.setValue(100)
    for pixels, expected in ((30, 70), (-30, 100)):
        event = QWheelEvent(QPointF(30, 30), QPointF(window.canvas.mapToGlobal(QPoint(30, 30))),
                            QPoint(0, pixels), QPoint(0, 0), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
        QApplication.sendEvent(window.canvas, event)
        assert event.isAccepted() and outer.value() == expected
        assert window.result_tabs.tabBar().mapTo(window, QPoint(0, 0)) == tab_position


def test_recording_time_axis_stays_visible_below_both_scrolling_views_and_tracks_zoom(window):
    from matplotlib import dates
    start = pd.Timestamp("2026-10-07T12:00:00+02:00")
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0., 1., 2.], "time_dt": start + pd.to_timedelta([0, 1, 2], unit="s")})))
    window.provenance = {"settings": {"skip_preparation": True}}
    frame = pd.DataFrame({"time": [0., 1., 2.], **{f"metric_{i}": [2., 3., 4.] for i in range(8)}})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_series.blockSignals(True)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.plot()
    for field in (window.clock_input, window.time_from, window.time_to):
        field.calendar.setMinimumWidth(382)
        field.seconds.setMinimumWidth(382)
    window.result_tabs.setCurrentIndex(1)
    window.filters_toggle.setChecked(True)
    window.resize(960, 720)
    QTest.qWait(50)
    window.canvas.draw()
    anchor = window.time_axis.mapTo(window, QPoint(0, 0))
    assert window.graph_view.isAncestorOf(window.time_axis)
    assert not window.results_scroll.isAncestorOf(window.time_axis)
    assert not window.graph_scroll.isAncestorOf(window.time_axis)
    assert isinstance(window.time_axis.axes.xaxis.get_major_formatter(), dates.ConciseDateFormatter)
    assert "Recording date/time" in window.time_axis.axes.get_xlabel()
    for bar in (window.results_scroll.verticalScrollBar(), window.graph_scroll.verticalScrollBar()):
        assert bar.maximum() > 100
        for position in (bar.maximum() // 2, bar.maximum(), 0):
            bar.setValue(position)
            QTest.qWait(20)
            assert window.time_axis.mapTo(window, QPoint(0, 0)) == anchor
            assert window.time_axis.visibleRegion().contains(window.time_axis.rect())
            assert window.time_axis.axes.get_xlim() == pytest.approx(window.figure.axes[0].get_xlim())
    low, high = window.figure.axes[0].get_xlim()
    window.figure.axes[-1].set_xlim(low + (high - low) * .25, high - (high - low) * .25)
    window.canvas.draw()
    assert window.time_axis.axes.get_xlim() == pytest.approx(window.figure.axes[-1].get_xlim())
    # The ruler aligns horizontally with the plotted data, including its tree
    # selector and the margin needed for y labels.
    source = window.figure.axes[0]
    plot_left = window.canvas.mapToGlobal(QPoint(0, 0)).x() + source.get_position().x0 * window.canvas.width()
    ruler_left = window.time_axis.mapToGlobal(QPoint(0, 0)).x() + window.time_axis.axes.get_position().x0 * window.time_axis.width()
    assert ruler_left == pytest.approx(plot_left, abs=1)


def test_module_colors_match_analysis_overview_and_graphs(window):
    from matplotlib.colors import to_rgba
    from paradigma_desktop.theme import MODULE_PALETTE, module_color
    frame = pd.DataFrame({"time": [0., 1., 2.], "power": [2., 3., 4.]})
    window.analyzed({"quantifications": {"gait": {"unfiltered": frame}, "tremor": frame, "pulse_rate": frame},
                     "aggregations": {module: {"median": 3.} for module in MODULE_PALETTE}})
    window.set_modules(list(MODULE_PALETTE))
    window.navigate(1)
    QTest.qWait(30)
    for title, module in window.MODULES.items():
        control = window.module_buttons[title]
        assert control.property("analysisModule") == module
        image = control.grab().toImage()
        ratio = image.devicePixelRatio()
        assert image.pixelColor(int(20 * ratio), int(5 * ratio)).name().upper() == MODULE_PALETTE[module]["tint"]
    window.navigate(2)
    for module, panel in window.overview_module_cards.items():
        assert panel.property("analysisModule") == module
        image = panel.grab().toImage()
        ratio = image.devicePixelRatio()
        assert image.pixelColor(int(20 * ratio), int(5 * ratio)).name().upper() == MODULE_PALETTE[module]["tint"]
    for axes in window.figure.axes:
        module = axes._paradigma_dataset.split("/")[1]
        assert to_rgba(axes.lines[0].get_color()) == to_rgba(module_color(module))
    window.dataset.setCurrentText("quantifications/tremor")
    window.result_tabs.setTabVisible(window.sensor_tab_index, True)
    window.result_tabs.setCurrentIndex(window.sensor_tab_index)
    QTest.qWait(30)
    window.sensor_frame = pd.DataFrame({"gyroscope_x": [1., 2., 3.]})
    window.sensor_times = np.array([0., 1., 2.])
    window.sensor_channel.addItem("gyroscope_x", "gyroscope_x")
    window.plot_sensor()
    assert to_rgba(window.sensor_figure.axes[0].lines[0].get_color()) == to_rgba(module_color("tremor"))


def test_binary_display_uses_larger_marks_and_compact_bands_without_losing_observations(window):
    frame = pd.DataFrame({"time": [0., 1., 2., 3.], "pred_event": [0., 1., np.nan, 0.]})
    window.analyzed({"classifications": {"tremor": frame}})
    item = window._series_items[("classifications/tremor", "pred_event")]
    item.setCheckState(0, Qt.Checked)
    axes = window.figure.axes[0]
    assert axes.collections[0].get_sizes().tolist() == [48, 64, 48]
    np.testing.assert_array_equal(axes.collections[0].get_offsets(), [[0., 0.], [1., 1.], [3., 0.]])
    assert axes.get_ylim() == pytest.approx((-.32, 1.32))
    assert window.canvas.minimumHeight() == window.canvas.maximumHeight() == 140
    for band in axes.patches:
        assert band.get_height() == pytest.approx(.22)


def test_exported_results_figure_retains_its_time_axis_and_restores_pinned_display(window, tmp_path):
    frame = pd.DataFrame({"time": [0., 1., 2.], "power": [2., 3., 4.]})
    window.analyzed({"quantifications": {"tremor": frame}})
    seen = []
    window.canvas.mpl_connect("draw_event", lambda event: seen.append((window.canvas.exporting_time_axis,
                                               window.figure.axes[-1].xaxis.label.get_visible())))
    destination = tmp_path / "results.png"
    window.figure.savefig(destination)
    assert destination.stat().st_size > 1000
    assert (True, True) in seen
    assert not window.canvas.exporting_time_axis
    assert not window.figure.axes[-1].xaxis.label.get_visible()
    window.canvas.draw()
    assert window.time_axis.axes.get_xlabel() == window.figure.axes[0].get_xlabel()
    window.clear_results()
    assert not window.time_axis.axes.get_visible()
