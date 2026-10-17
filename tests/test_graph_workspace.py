"""Shared recording clocks, categorical rasters and actual Qt wheel delivery."""

import os
from copy import deepcopy
from types import SimpleNamespace

from conftest import wait_for_previews

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QWidget,
)

from paradigma_studio.app import MainWindow
from paradigma_studio.day_axis import RecordingDayFormatter
from paradigma_studio.plotting import binary_indicator
from paradigma_studio.results_view import clock_times
from paradigma_studio.time_controls import TimeField


@pytest.mark.parametrize("dtype", ["float64", "Float64"])
def test_gait_window_threshold_boundaries_preserve_probabilities_and_raw_tables(dtype):
    from importlib.resources import files

    from paradigma.classification import ClassifierPackage

    from paradigma_studio.results_view import plot_tables

    for stage, asset, probability, indicator in (
        ("detection", "gait_detection_clf_package.pkl", "pred_gait_proba", "pred_gait_window"),
        (
            "arm_activity",
            "gait_filtering_clf_package.pkl",
            "pred_no_other_arm_activity_proba",
            "pred_no_other_arm_activity_window",
        ),
    ):
        threshold = ClassifierPackage.load(files("paradigma.assets") / asset).threshold
        values = [
            np.nextafter(threshold, -np.inf),
            threshold,
            np.nextafter(threshold, np.inf),
            np.nan,
            np.inf,
            -np.inf,
        ]
        frame = pd.DataFrame(
            {"time": np.arange(len(values)), probability: pd.Series(values, dtype=dtype)}
        )
        original = frame.copy(deep=True)
        name = f"classifications/gait/{stage}"
        plots, labels = plot_tables({name: frame})
        np.testing.assert_array_equal(
            plots[name][indicator], [0.0, 1.0, 1.0, np.nan, np.nan, np.nan]
        )
        pd.testing.assert_series_equal(
            plots[name][probability], original[probability], check_exact=True
        )
        pd.testing.assert_frame_equal(frame, original, check_exact=True)
        title = "Gait presence" if stage == "detection" else "Filtered gait presence"
        assert labels[(name, indicator)] == f"{title} (prediction)"
        assert labels[(name, probability)] == f"{title} (probability)"


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
    frame = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0], "power": [2.0, 3.0, 4.0], "other": [5.0, 6.0, 7.0]}
    )
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
    # Inspect actual controls, including hidden ones, rather than window aliases.
    assert set(window.result_tabs.findChildren(QComboBox)) == {
        window.dataset,
        window.table_dataset,
        window.y_column,
        window.result_graph_view,
    }
    assert window.detail_controls.findChildren(QCheckBox) == [window.timing_toggle]
    assert window.detail_controls.findChildren(QPushButton) == [window.context_button]
    assert not window.result_tabs.findChildren(TimeField)
    assert not window.result_tabs.findChildren(QAbstractSpinBox)
    assert window.results_header.findChildren(QPushButton) == [window.sensor_close]
    assert window.result_tabs.cornerWidget(Qt.TopRightCorner).findChildren(QPushButton) == [
        window.save_results_button,
        window.export_button,
    ]


def test_binary_raster_shows_only_presence_without_losing_time_range_or_rare_events(window):
    t = np.arange(20002, dtype=float)
    values = np.zeros(len(t))
    values[1] = 1.0
    values[2] = np.nan
    frame = pd.DataFrame({"time": t, "pred_event": values})
    original = frame.copy(deep=True)
    window.analyzed({"quantifications": {"tremor": frame}})
    axes = window.figure.axes[0]
    assert not axes.lines
    assert not axes.get_yticks().size
    paths = axes.collections[0].get_paths()
    assert len(paths) == 1
    assert (paths[0].vertices[:, 0].min(), paths[0].vertices[:, 0].max()) == (1.0, 2.0)
    assert axes.get_xlim()[0] <= t[0] and axes.get_xlim()[1] >= t[-1]
    axes.set_xlim(3.0, 9.0)
    window.canvas.draw()
    assert len(axes.collections[0].get_paths()) == 1
    assert len(window._result_state.active_frame) == len(frame)
    pd.testing.assert_frame_equal(frame, original)
    axes.set_xlim(1.2, 1.8)
    assert paths[0].contains_point((1.5, 1.0))
    assert not binary_indicator(pd.Series([0.0, 1.0]), "pred_event_proba")
    assert not binary_indicator(pd.Series([0.0, 1.0]), "gyroscope_x")
    assert binary_indicator(pd.Series([1.0, 1.0]), "pred_event")


def test_raw_graphs_separate_states_and_signals_without_changing_values(window):
    raw = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0], "gyroscope_x": [1.0, 2.0, 3.0], "wear_flag": [0, 1, 0]}
    )
    window.loaded(("sensor.csv", raw))
    window.set_input_channels(["gyroscope_x", "wear_flag"])
    signal, states = window.data_figure.axes
    np.testing.assert_array_equal(signal.lines[0].get_ydata(), raw.gyroscope_x)
    assert not states.lines
    np.testing.assert_array_equal(states.collections[0].get_offsets(), [[1.0, 1.0]])
    assert states.get_xlim()[0] <= 0.0 and states.get_xlim()[1] >= 2.0


def test_analyze_calendar_default_preserves_source_precision_and_results(window):
    start = pd.Timestamp("2026-10-07T12:00:00.123456789+02:00")
    raw = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0], "time_dt": start + pd.to_timedelta([0.0, 1.0, 2.0], unit="s")}
    )
    window.loaded(("sensor.csv", raw))
    wait_for_previews(window)
    assert window.clock_input.text() == start.isoformat()
    assert window.clock_input.calendar.calendarPopup()
    window.provenance = {"settings": {"skip_preparation": True}}
    result = {
        "quantifications": {
            name: pd.DataFrame({"time": [0.0, 1.0, 2.0], "metric": [4.0, 5.0, 6.0]})
            for name in ("tremor", "pulse_rate")
        }
    }
    window.analyzed(result)
    original = deepcopy(window._result_state.display_clock)
    window.clock_input.calendar.setDateTime(window.clock_input.calendar.dateTime().addMSecs(1500))
    assert window.origin_setting()["mode"] == "custom"
    assert window._result_state.display_clock == original
    assert all(
        positions.tolist() == [0, 1, 2]
        for _, positions in window._result_state._detail_selections.values()
    )
    window.origin_reset.click()
    assert window.clock_input.text() == start.isoformat()


def test_calendar_clock_preserves_named_timezone_across_dst():
    application = QApplication.instance() or QApplication([])
    field = TimeField("From")
    field.set_clock({"origin": "2026-10-25T00:30:00+02:00", "timezone": "Europe/Amsterdam"})
    field.setText("10800")
    assert field.calendar.dateTime().toString(Qt.ISODateWithMs) == "2026-10-25T02:30:00.000+01:00"
    field.calendar.setDateTime(field.calendar.dateTime().addSecs(3600))
    assert field.text() == "2026-10-25T03:30:00.000+01:00"
    field.set_clock(None)
    assert float(field.text()) == 14400.0
    field.close()
    application.processEvents()


def test_result_canvas_accepts_mouse_wheel_and_touchpad_scrolling(window):
    frame = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0], **{f"metric_{i}": [2.0, 3.0, 4.0] for i in range(8)}}
    )
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
        event = QWheelEvent(
            QPointF(30, 30),
            QPointF(window.canvas.mapToGlobal(QPoint(30, 30))),
            QPoint(0, pixels),
            QPoint(0, angle),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(window.canvas, event)
        assert event.isAccepted()

    wheel(-70, 0)
    assert bar.value() == 70
    wheel(0, -120)
    assert bar.value() > 70
    wheel(1000, 0)
    assert bar.value() == 0


@pytest.mark.parametrize("editor_minimum_width", [0, 382])
def test_analyze_origin_calendar_remains_readable_at_windows_control_widths(
    window, editor_minimum_width
):
    field = window.clock_input
    field.calendar.setMinimumWidth(editor_minimum_width)
    field.seconds.setMinimumWidth(editor_minimum_width)
    window.navigate(1)
    window.resize(960, 720)
    QTest.qWait(50)
    window.analysis_scroll.ensureWidgetVisible(field, 0, 0)
    QTest.qWait(20)
    assert field.editors.currentWidget().height() >= 38
    assert (
        field.editors.currentWidget().width()
        >= field.editors.currentWidget().minimumSizeHint().width()
    )
    assert field.visibleRegion().boundingRect().contains(field.rect())
    assert window.analysis_scroll.isAncestorOf(field)
    assert not window.result_tabs.isAncestorOf(field)


def test_results_tabs_stay_anchored_across_views_and_scrolling(window):
    window.analyzed(
        {"quantifications": {"tremor": pd.DataFrame({"time": [0.0, 1.0], "power": [2.0, 3.0]})}}
    )
    bar = window.result_tabs.tabBar()

    def positions():
        return [bar.mapTo(window, bar.tabRect(i).topLeft()) for i in range(3)]

    QTest.qWait(30)
    original = positions()
    assert original[0].y() < 125
    for index in (1, 2, 0, 2, 1):
        window.result_tabs.setCurrentIndex(index)
        QTest.qWait(30)
        assert positions() == original
        export_center = window.export_button.mapTo(window, window.export_button.rect().center()).y()
        assert (
            bar.mapTo(window, QPoint(0, 0)).y()
            <= export_center
            <= bar.mapTo(window, QPoint(0, bar.height())).y()
        )
        window._result_state.results_scroll.verticalScrollBar().setValue(
            window._result_state.results_scroll.verticalScrollBar().maximum()
        )
        QTest.qWait(20)
        assert positions() == original
        assert window.export_button.isVisible()


def test_sidebar_hover_expands_without_moving_page_and_about_stays_in_footer(window):
    window.navigate(2)
    QTest.mouseMove(window.pages, QPoint(300, 100))
    QTest.qWait(150)
    assert window._shell_state.sidebar_collapsed and window.sidebar.width() == 68
    position = window.result_tabs.mapTo(window, QPoint(0, 0))
    QTest.mouseMove(window.sidebar, QPoint(30, 100))
    QTest.qWait(160)
    assert (
        not window._shell_state.sidebar_collapsed
        and window.sidebar.width() == window.sidebar.expanded_width
    )
    assert window.sidebar.expanded_width >= 194
    assert [item.text() for item in window.nav_buttons] == [
        f"{i + 1}    {title}" for i, title in enumerate(window.SECTIONS)
    ]
    assert window.result_tabs.mapTo(window, QPoint(0, 0)) == position
    QTest.mouseMove(window.pages, QPoint(300, 100))
    QTest.qWait(160)
    assert window._shell_state.sidebar_collapsed and window.sidebar.width() == 68
    assert window.result_tabs.mapTo(window, QPoint(0, 0)) == position
    assert window.about_button.text() == "About"
    assert window.sidebar.isAncestorOf(window.about_button)
    assert window.about_button.geometry().bottom() > window.sidebar.height() - 70
    option = QStyleOptionButton()
    window.about_button.initStyleOption(option)
    contents = window.about_button.style().subElementRect(
        QStyle.SE_PushButtonContents, option, window.about_button
    )
    text = window.about_button.fontMetrics().boundingRect(
        contents, Qt.AlignLeft | Qt.AlignVCenter, "About"
    )
    assert window.about_button.visibleRegion().contains(text)
    assert window.sidebar.findChildren(QPushButton) == [*window.nav_buttons, window.about_button]
    window.about_button.click()
    assert window._shell_state._acknowledgements_dialog.isVisible()
    window._shell_state._acknowledgements_dialog.close()


@pytest.mark.parametrize("brand_font_px", [None, 30])
def test_sidebar_text_anchors_stay_fixed_through_animation(window, brand_font_px):
    QTest.mouseMove(window.pages, QPoint(300, 100))
    QTest.qWait(150)
    sidebar = window.sidebar
    if brand_font_px is not None:
        # Reproduce the wider native Windows font metrics on any platform.
        window.brand.setStyleSheet(f"font-size: {brand_font_px}px;")
    sidebar.setExpanded(False, animated=False)
    QApplication.instance().processEvents()
    controls = [
        *window.nav_buttons,
        window.about_button,
        window.brand_icon,
        window.brand,
    ]
    positions = [(widget.mapTo(window, QPoint(0, 0)), widget.size()) for widget in controls]
    if brand_font_px is not None:
        assert window.brand.fontMetrics().horizontalAdvance(window.brand.text()) > 170
        assert sidebar.expanded_width > 194

    def text_box(widget, text):
        option = QStyleOptionButton()
        widget.initStyleOption(option)
        contents = widget.style().subElementRect(QStyle.SE_PushButtonContents, option, widget)
        return widget.fontMetrics().boundingRect(contents, Qt.AlignLeft | Qt.AlignVCenter, text)

    anchors = [
        widget.mapTo(window, text_box(widget, text).topLeft())
        for widget, text in zip(
            [*window.nav_buttons, window.about_button], ["1", "2", "3", "4", "About"], strict=False
        )
    ]
    assert len({point.x() for point in anchors}) == 1  # About shares the number alignment.
    assert window.about_button.visibleRegion().contains(text_box(window.about_button, "About"))
    for expanded in (True, False):
        sidebar.setExpanded(expanded)
        for elapsed in (0, 20, 40, 60, 90, 120):
            sidebar.animation.setCurrentTime(elapsed)
            QApplication.instance().processEvents()
            assert [
                (widget.mapTo(window, QPoint(0, 0)), widget.size()) for widget in controls
            ] == positions
            assert not window.brand.wordWrap()
            assert window.brand.height() >= window.brand.sizeHint().height()
            assert (
                window.brand.fontMetrics().horizontalAdvance(window.brand.text())
                <= window.brand.width()
            )
            current = [
                widget.mapTo(window, text_box(widget, text).topLeft())
                for widget, text in zip(
                    [*window.nav_buttons, window.about_button],
                    ["1", "2", "3", "4", "About"],
                    strict=False,
                )
            ]
            assert current == anchors
            assert window.about_button.visibleRegion().contains(
                text_box(window.about_button, "About")
            )


def test_canvas_wheel_reaches_outer_results_scroll_when_single_graph_fits(window):
    window.analyzed(
        {"quantifications": {"tremor": pd.DataFrame({"time": [0.0, 1.0], "power": [2.0, 3.0]})}}
    )
    window.result_tabs.setCurrentIndex(1)
    window.results_header.setMinimumHeight(350)
    window.resize(960, 650)
    QTest.qWait(50)
    inner = window.graph_scroll.verticalScrollBar()
    outer = window._result_state.results_scroll.verticalScrollBar()
    assert inner.maximum() == 0 and outer.maximum() > 120
    tab_position = window.result_tabs.tabBar().mapTo(window, QPoint(0, 0))
    outer.setValue(100)
    for pixels, expected in ((30, 70), (-30, 100)):
        event = QWheelEvent(
            QPointF(30, 30),
            QPointF(window.canvas.mapToGlobal(QPoint(30, 30))),
            QPoint(0, pixels),
            QPoint(0, 0),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(window.canvas, event)
        assert event.isAccepted() and outer.value() == expected
        assert window.result_tabs.tabBar().mapTo(window, QPoint(0, 0)) == tab_position


def test_recording_time_axis_stays_visible_below_both_scrolling_views_and_tracks_zoom(window):
    start = pd.Timestamp("2026-10-07T12:00:00.123456789+02:00")
    window.loaded(
        (
            "sensor.csv",
            pd.DataFrame(
                {"time": [0.0, 1.0, 2.0], "time_dt": start + pd.to_timedelta([0, 1, 2], unit="s")}
            ),
        )
    )
    window.provenance = {"settings": {"skip_preparation": True}}
    frame = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0], **{f"metric_{i}": [2.0, 3.0, 4.0] for i in range(8)}}
    )
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_series.blockSignals(True)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.plot()
    window.results_header.setMinimumHeight(350)
    window.result_tabs.setCurrentIndex(1)
    window.resize(960, 720)
    QTest.qWait(50)
    window.canvas.draw()
    anchor = window.time_axis.mapTo(window, QPoint(0, 0))
    assert window.graph_view.isAncestorOf(window.time_axis)
    assert not window._result_state.results_scroll.isAncestorOf(window.time_axis)
    assert not window.graph_scroll.isAncestorOf(window.time_axis)
    assert isinstance(window.time_axis.axes.xaxis.get_major_formatter(), RecordingDayFormatter)
    assert "Recording time" in window.time_axis.axes.get_xlabel()
    for bar in (
        window._result_state.results_scroll.verticalScrollBar(),
        window.graph_scroll.verticalScrollBar(),
    ):
        assert bar.maximum() > 100
        for position in (bar.maximum() // 2, bar.maximum(), 0):
            bar.setValue(position)
            QTest.qWait(20)
            assert window.time_axis.mapTo(window, QPoint(0, 0)) == anchor
            assert window.time_axis.visibleRegion().contains(window.time_axis.rect())
            assert window.time_axis.axes.get_xlim() == pytest.approx(
                window.figure.axes[0].get_xlim()
            )
    low, high = window.figure.axes[0].get_xlim()
    window.figure.axes[-1].set_xlim(low + (high - low) * 0.25, high - (high - low) * 0.25)
    window.canvas.draw()
    assert window.time_axis.axes.get_xlim() == pytest.approx(window.figure.axes[-1].get_xlim())
    # The ruler aligns horizontally with the plotted data, including its tree
    # selector and the margin needed for y labels.
    source = window.figure.axes[0]
    plot_left = (
        window.canvas.mapToGlobal(QPoint(0, 0)).x()
        + source.get_position().x0 * window.canvas.width()
    )
    ruler_left = (
        window.time_axis.mapToGlobal(QPoint(0, 0)).x()
        + window.time_axis.axes.get_position().x0 * window.time_axis.width()
    )
    assert ruler_left == pytest.approx(plot_left, abs=1)


def test_module_colors_match_analysis_overview_and_graphs(window):
    from matplotlib.colors import to_rgba

    from paradigma_studio.theme import MODULE_PALETTE, module_color

    frame = pd.DataFrame({"time": [0.0, 1.0, 2.0], "power": [2.0, 3.0, 4.0]})
    window.analyzed(
        {
            "quantifications": {
                "gait": {"unfiltered": frame},
                "tremor": frame,
                "pulse_rate": frame,
            },
            "aggregations": {module: {"median": 3.0} for module in MODULE_PALETTE},
        }
    )
    window.set_modules(list(MODULE_PALETTE))
    window.navigate(1)
    QTest.qWait(30)
    for title, module in window.MODULES.items():
        control = window.module_buttons[title]
        assert control.property("analysisModule") == module
        image = control.grab().toImage()
        ratio = image.devicePixelRatio()
        assert (
            image.pixelColor(int(20 * ratio), int(5 * ratio)).name().upper()
            == MODULE_PALETTE[module]["tint"]
        )
    window.navigate(2)
    for module, panel in window._result_state.overview_module_cards.items():
        assert panel.property("analysisModule") == module
        image = panel.grab().toImage()
        ratio = image.devicePixelRatio()
        assert (
            image.pixelColor(int(20 * ratio), int(5 * ratio)).name().upper()
            == MODULE_PALETTE[module]["tint"]
        )
    for axes in window.figure.axes:
        module = axes._paradigma_dataset.split("/")[1]
        assert (
            tuple(axes.collections[0].get_facecolor()[0][:3]) == to_rgba(module_color(module))[:3]
        )
    window.dataset.setCurrentText("quantifications/tremor")
    window.result_tabs.setTabVisible(window.sensor_tab_index, True)
    window.result_tabs.setCurrentIndex(window.sensor_tab_index)
    QTest.qWait(30)
    window._sensor_state.sensor_frame = pd.DataFrame({"gyroscope_x": [1.0, 2.0, 3.0]})
    window._sensor_state.sensor_times = np.array([0.0, 1.0, 2.0])
    window.populate_sensor_channels()
    window.plot_sensor()
    assert to_rgba(window.sensor_figure.axes[0].lines[0].get_color()) == to_rgba(
        window._sensor_state._sensor_channel_colors["gyroscope_x"]
    )


def test_binary_display_fills_positive_intervals_without_shading_missing_or_zero_states(window):
    frame = pd.DataFrame({"time": [0.0, 1.0, 2.0, 3.0], "pred_event": [0.0, 1.0, np.nan, 0.0]})
    window.analyzed({"classifications": {"tremor": frame}})
    item = window._series_items[("classifications/tremor", "pred_event")]
    item.setCheckState(0, Qt.Checked)
    axes = window.figure.axes[0]
    bars = axes.collections[0].get_paths()
    assert len(bars) == 1
    assert (bars[0].vertices[:, 0].min(), bars[0].vertices[:, 0].max()) == (1.0, 2.0)
    assert axes.get_ylim() == pytest.approx((0.65, 1.35))
    assert window.canvas.minimumHeight() == window.canvas.maximumHeight() == 88
    assert not axes.patches
    axes.set_xlim(1.2, 1.8)
    window.canvas.draw()
    assert bars[0].contains_point((1.5, 1.0))
    assert not axes.get_yticks().size
    window.plot_toolbar.settings.reset()
    assert axes.get_ylim() == pytest.approx((0.65, 1.35))


def test_binary_intervals_respect_recording_gaps_and_clicks_inside_bars(window):
    frame = pd.DataFrame(
        {
            "time": [0.0, 4.0, 8.0, 100.0, 104.0, 108.0],
            "file_key": ["first"] * 3 + ["second"] * 3,
            "pred_tremor_checked": [1.0, 0.0, 1.0, 1.0, np.nan, 0.0],
        }
    )
    original = frame.copy(deep=True)
    window.analyzed({"classifications": {"tremor": frame}})
    axes = window.figure.axes[0]
    intervals = [
        (bar.vertices[:, 0].min(), bar.vertices[:, 0].max())
        for bar in axes.collections[0].get_paths()
    ]
    assert intervals == [(0.0, 4.0), (8.0, 12.0), (100.0, 104.0)]
    axes.set_xlim(1.0, 3.0)
    window.canvas.draw()
    assert axes.collections[0].get_paths()[0].contains_point((2.0, 1.0))
    window.graph_clicked(SimpleNamespace(inaxes=axes, xdata=3.5))
    assert window.result_table.currentIndex().row() == 0
    axes.set_xlim(8.0, 9.0)
    window.canvas.draw()
    assert axes.collections[0].get_paths()[1].contains_point((8.5, 1.0))
    assert len(window._result_state.active_frame) == len(frame)
    pd.testing.assert_frame_equal(frame, original)


def test_view_shares_figure_toolbar_and_sensor_context_stays_bottom_right(window):
    window.analyzed(
        {"quantifications": {"tremor": pd.DataFrame({"time": [0.0, 1.0], "power": [2.0, 3.0]})}}
    )
    window.result_tabs.setCurrentIndex(1)
    QTest.qWait(50)
    for width in (1050, 1450, 960):
        window.resize(width, 720)
        QTest.qWait(30)
        toolbar = window.plot_toolbar
        controls = window.graph_view_controls
        assert window.figure_actions.isAncestorOf(controls)
        assert window.graph_footer.isAncestorOf(window.context_controls)
        assert window.context_controls.visibleRegion().contains(window.context_controls.rect())
        toolbar_center = toolbar.mapTo(window, toolbar.rect().center()).y()
        top = controls.mapTo(window, QPoint(0, 0)).y()
        if window.figure_actions.secondary.isVisible():
            assert top >= toolbar.mapTo(window, QPoint(0, toolbar.height())).y()
        else:
            assert top <= toolbar_center <= top + controls.height()
            assert (
                controls.mapTo(window, QPoint(0, 0)).x()
                > toolbar.mapTo(window, QPoint(toolbar.width(), 0)).x()
            )
        assert controls.visibleRegion().contains(controls.rect())
        body = window._layout._result_view_layouts[1]
        assert body.itemAt(body.count() - 1).widget() is window.graphs_workspace
        graph_bottom = window.graph_scroll.mapTo(
            window, QPoint(0, window.graph_scroll.height())
        ).y()
        axis_top = window.time_axis.mapTo(window, QPoint(0, 0)).y()
        assert 0 <= axis_top - graph_bottom <= 40
    window.result_tabs.setCurrentIndex(2)
    QTest.qWait(30)
    assert window.detail_controls.isAncestorOf(window.context_controls)
    assert window.context_controls.isVisible()
    window.result_tabs.setCurrentIndex(1)
    assert window.graph_footer.isAncestorOf(window.context_controls)
    assert window.figure_actions.isAncestorOf(window.graph_view_controls)


def test_selected_result_is_marked_across_date_plots_without_changing_zoom_or_data(window):
    from matplotlib import dates

    start = pd.Timestamp("2026-10-07T12:00:00+02:00")
    raw = pd.DataFrame(
        {
            "time": np.arange(4.0),
            "time_dt": start + pd.to_timedelta(np.arange(4.0), unit="s"),
            "gyroscope_x": np.arange(4.0),
        }
    )
    window.loaded(("sensor.csv", raw))
    window.provenance = {"settings": {"skip_preparation": True}}
    states = pd.DataFrame({"time": np.arange(4.0), "pred_tremor": [0.0, 1.0, np.nan, 0.0]})
    window.analyzed(
        {
            "classifications": {"tremor": states},
            "quantifications": {
                module: pd.DataFrame({"time": np.arange(4.0), "power": [2.0, 3.0, 4.0, 5.0]})
                for module in ("tremor", "pulse_rate")
            },
        }
    )
    window._series_items[("classifications/tremor", "pred_tremor")].setCheckState(0, Qt.Checked)
    window.dataset.setCurrentText("classifications/tremor")
    window.result_tabs.setCurrentIndex(1)
    x = dates.date2num(clock_times([1.0], window._result_state.display_clock))[0]
    axes = next(
        ax for ax in window.figure.axes if ax._paradigma_dataset == "classifications/tremor"
    )
    axes.set_xlim(x - 0.5 / 86400.0, x + 1.5 / 86400.0)
    limits = [(ax.get_xlim(), ax.get_ylim()) for ax in window.figure.axes]
    window.graph_clicked(SimpleNamespace(inaxes=axes, xdata=x))
    assert window.result_table.currentIndex().row() == 1
    assert window.context_button.isEnabled()
    for ax in window.figure.axes:
        marker = next(line for line in ax.lines if line.get_gid() == "selected-result-time")
        assert marker.get_xdata() == pytest.approx([x, x])
    point = next(line for line in axes.lines if line.get_gid() == "selected-result-point")
    assert point.get_ydata() == [1.0]
    assert [(ax.get_xlim(), ax.get_ylim()) for ax in window.figure.axes] == limits
    assert window.time_axis.selection_marker.get_visible()
    assert window.time_axis.selection_label.get_text() == "07 Oct 2026 12:00:01"
    window.time_axis.draw()
    bounds = window.time_axis.selection_label.get_window_extent(window.time_axis.get_renderer())
    assert bounds.y0 > window.time_axis.axes.bbox.y0
    assert bounds.y1 <= window.time_axis.figure.bbox.y1
    axes.set_xlim(x + 2.0 / 86400.0, x + 3.0 / 86400.0)
    assert not window.time_axis.selection_marker.get_visible()
    assert window.time_axis.selection_label.get_visible()
    axes.set_xlim(*limits[0][0])
    assert window.time_axis.selection_marker.get_visible()
    window.plot()  # Changing graph presentation retains the linked selection.
    assert all(
        any(line.get_gid() == "selected-result-time" for line in ax.lines)
        for ax in window.figure.axes
    )
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    assert not any(
        line.get_gid() == "selected-result-point" for ax in window.figure.axes for line in ax.lines
    )
    window.activate_dataset_rows()
    assert not window._graph_state._result_selection_artists
    assert not window.time_axis.selection_marker.get_visible()
    assert not window.context_button.isEnabled()
    np.testing.assert_array_equal(states.pred_tremor, [0.0, 1.0, np.nan, 0.0])


def test_exported_results_figure_retains_its_time_axis_and_restores_pinned_display(
    window, tmp_path
):
    frame = pd.DataFrame({"time": [0.0, 1.0, 2.0], "power": [2.0, 3.0, 4.0]})
    window.analyzed({"quantifications": {"tremor": frame}})
    seen = []
    window.canvas.mpl_connect(
        "draw_event",
        lambda event: seen.append(
            (window.canvas.exporting_time_axis, window.figure.axes[-1].xaxis.label.get_visible())
        ),
    )
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
