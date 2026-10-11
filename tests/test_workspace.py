"""Behavioral checks for navigation, linked exploration and previous runs."""

from conftest import bar_values, bar_starts, wait_for_previews, select_plot_metric
import json
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PySide6.QtTest import QTest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton
from PySide6.QtCore import Qt, QPoint

from paradigma_studio import app as desktop
from paradigma_studio.app import MainWindow
from paradigma_studio.exploration import source_timeline
from paradigma_studio.history import RunHistory, new_run


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = MainWindow(history_dir=tmp_path / "runs")
    yield widget
    wait_for_job(widget)
    widget.close()
    app.processEvents()


def wait_for_job(window):
    deadline = time.monotonic() + 10
    while window.worker is not None and time.monotonic() < deadline:
        QTest.qWait(20)
    assert window.worker is None, "Background operation did not finish"


def output():
    return pd.DataFrame(
        {
            "time": np.arange(6, dtype=float),
            "participant_id": ["a", "b", "a", "b", "a", "b"],
            "file_key": ["segment_1"] * 3 + ["segment_2"] * 3,
            "metric": np.arange(10, 16, dtype=float),
        }
    )


def test_navigation_and_integrated_controls_preserve_settings(window):
    assert window.pages.count() == 4
    assert window.SECTIONS == ("Data", "Analyze", "Results", "Runs")
    window.navigate(1)
    window.module_buttons["Tremor"].click()
    assert window.module_buttons["Gait"].isChecked()
    assert window.module_buttons["Tremor"].isChecked()
    assert not window.module_buttons["Pulse rate"].isChecked()
    assert set(window.module_buttons) == {"Gait", "Tremor", "Pulse rate"}
    assert window.pages.widget(1).isAncestorOf(window.settings_panel)
    assert not hasattr(window, "inspector")
    assert not hasattr(window, "pipeline")
    window.gyro.setCurrentText("rad/s")
    for index in range(4):
        window.nav_buttons[index].click()
        assert window.pages.currentIndex() == index
        assert window.nav_buttons[index].isChecked()
        assert sum(item.isChecked() for item in window.nav_buttons) == 1
    assert window.sidebar.width() == 68
    window.toggle_sidebar()
    assert window.sidebar.width() == window.sidebar.expanded_width
    assert window.sidebar.expanded_width >= 194
    assert [item.accessibleName() for item in window.nav_buttons] == list(window.SECTIONS)
    window.toggle_sidebar()
    assert window.sidebar.width() == 68
    window.navigate(1)
    assert window.selected_modules() == ["gait", "tremor"]
    assert window.gyro.currentText() == "rad/s"


def test_segmentation_defaults_match_official_package_and_resets_remain_available(window):
    from inspect import signature
    from paradigma.orchestrator import run_paradigma
    from paradigma.prepare_data import prepare_raw_data
    from paradigma_studio.analysis_help import DEFAULT_MAX_GAP_SECONDS, DEFAULT_MIN_SECTION_SECONDS

    defaults = signature(prepare_raw_data).parameters
    assert (
        window.max_gap.value() == DEFAULT_MAX_GAP_SECONDS == defaults["max_segment_gap_s"].default
    )
    assert (
        window.min_segment.value()
        == DEFAULT_MIN_SECTION_SECONDS
        == defaults["min_segment_length_s"].default
    )
    assert window.gaps.isChecked() == signature(run_paradigma).parameters["split_by_gaps"].default
    assert (
        window.acc.currentText()
        == signature(run_paradigma).parameters["accelerometer_units"].default
    )
    assert (
        window.gyro.currentText() == signature(run_paradigma).parameters["gyroscope_units"].default
    )
    assert (
        window.time.currentText() == signature(run_paradigma).parameters["time_input_unit"].default
    )
    assert (
        window.orientation.text().split(",")
        == signature(run_paradigma).parameters["device_orientation"].default
    )
    assert (
        window.prepared.isChecked()
        == signature(run_paradigma).parameters["skip_preparation"].default
    )
    window.navigate(1)
    window.show()
    QApplication.instance().processEvents()
    for prepared in (False, True):
        window.prepared.setChecked(prepared)
        window.max_gap.setValue(4.0)
        window.min_segment.setValue(8.0)
        for title in ("Maximum gap", "Minimum section duration"):
            reset = window.section_reset_buttons[title]
            assert reset.isEnabled()
            reset.click()
        assert window.max_gap.value() == DEFAULT_MAX_GAP_SECONDS
        assert window.min_segment.value() == DEFAULT_MIN_SECTION_SECONDS
    assert window.segmentation_controls.isAncestorOf(window.gaps)
    assert window.segmentation_controls.isAncestorOf(window.max_gap)
    assert window.segmentation_controls.isAncestorOf(window.min_segment)
    from PySide6.QtCore import QPoint

    ys = [
        item.mapTo(window.settings_panel, QPoint(0, 0)).y()
        for item in (
            window.gaps,
            window.max_gap,
            window.min_segment,
            window.mapping,
            window.prepared,
        )
    ]
    assert ys == sorted(ys)


def test_run_button_remains_visible_in_compact_analysis_workspace(window):
    app = QApplication.instance()
    window.navigate(1)
    window.sidebar.setExpanded(False, animated=False)
    window.resize(1050, 720)
    window.show()
    app.processEvents()
    assert window.run_button.isVisible()
    assert window.run_button.parentWidget() is window.status_row
    assert not window.pages.widget(1).isAncestorOf(window.run_button)
    assert window.run_button.geometry().bottom() < window.status_row.height()
    assert (
        window.run_button.mapTo(window, window.run_button.rect().center()).y()
        == window.status.mapTo(window, window.status.rect().center()).y()
    )


def test_page_actions_share_the_status_row_and_navigation_only_shows_relevant_actions(window):
    window.resize(1050, 720)
    window.show()
    heights = []
    for index, expected in [
        (0, [window.continue_button]),
        (1, [window.stop_button, window.run_button]),
        (2, []),
        (3, []),
    ]:
        window.navigate(index)
        QApplication.instance().processEvents()
        heights.append(window.status_row.height())
        visible = [
            control
            for control in (window.continue_button, window.stop_button, window.run_button)
            if control.isVisible()
        ]
        assert visible == expected
        for control in expected:
            assert control.parentWidget() is window.status_row
            assert (
                control.mapTo(window, control.rect().center()).y()
                == window.status.mapTo(window, window.status.rect().center()).y()
            )
            assert control.visibleRegion().boundingRect().contains(control.rect())
        bottom = window.pages.mapTo(window, QPoint(0, window.pages.height())).y()
        assert window.status_row.mapTo(window, QPoint(0, 0)).y() >= bottom
    assert len(set(heights)) == 1


@pytest.mark.parametrize(
    "control_minimum_height, larger_surrounding_controls",
    [(0, False), (40, False), (44, False), (44, True)],
)
def test_analysis_preserves_spacing_accessible_fields_and_uniform_help_across_window_sizes(
    window, control_minimum_height, larger_surrounding_controls
):
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0.0, 1.0], "gyroscope_x": [1.0, 2.0]})))
    window.set_modules(["gait", "tremor", "pulse_rate"])
    # Larger native Windows control hints overflowed the previous layout even
    # though the same fields fitted under the headless Linux font metrics.
    for control in (
        window.side,
        window.acc,
        window.gyro,
        window.time,
        window.orientation,
        window.max_gap,
        window.min_segment,
    ):
        control.setMinimumHeight(control_minimum_height)
    if larger_surrounding_controls:
        # Input controls alone did not reproduce the Windows overflow. Native
        # labels, checkboxes and action buttons also consume vertical space.
        body = window.analysis_scroll.widget()
        for control in body.findChildren(QLabel):
            if control.objectName() != "fieldHelp":
                control.setMinimumHeight(28)
        for control in body.findChildren(QCheckBox):
            control.setMinimumHeight(36)
        for control in body.findChildren(QPushButton):
            if control.objectName() != "helpInfo":
                control.setMinimumHeight(44)
    window.navigate(1)
    window.resize(1200, 900)
    window.show()
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() == 0
    controls = (
        window.side,
        window.acc,
        window.gyro,
        window.time,
        window.orientation,
        window.drop_missing,
        window.gaps,
        window.max_gap,
        window.min_segment,
        window.mapping,
        window.prepared,
        *window.section_reset_buttons.values(),
    )
    for control in controls:
        assert control.visibleRegion().boundingRect().contains(control.rect())
    for previous, following in zip(
        (window.side, window.acc, window.gyro), (window.acc, window.gyro, window.time)
    ):
        bottom = previous.mapTo(window.settings_panel, QPoint(0, previous.height())).y()
        top = following.mapTo(window.settings_panel, QPoint(0, 0)).y()
        assert top - bottom >= 8, "Parameter rows must retain comfortable separation"
    help_buttons = [info for info, description in window.analysis_help.values()]
    assert {(info.width(), info.height()) for info in help_buttons} == {(22, 22)}
    assert all(info.objectName() == "helpInfo" and info.isCheckable() for info in help_buttons)
    # Small windows may scroll rather than compressing controls and whitespace.
    # Every field remains reachable and the action stays outside the scroll area.
    window.resize(960, 650)
    QTest.qWait(30)
    small_scroll_maximum = window.analysis_scroll.verticalScrollBar().maximum()
    if larger_surrounding_controls:
        assert small_scroll_maximum > 0
    for control in controls:
        # Text editors' ensureWidgetVisible follows their cursor rectangle;
        # scroll the whole control into view to check complete accessibility.
        center = control.mapTo(window.analysis_scroll.widget(), control.rect().center())
        window.analysis_scroll.ensureVisible(center.x(), center.y(), 0, control.height() // 2 + 8)
        QApplication.instance().processEvents()
        assert control.visibleRegion().boundingRect().contains(control.rect())
        assert window.run_button.visibleRegion().boundingRect().contains(window.run_button.rect())
    for info in help_buttons:
        info.click()
        assert sum(button.isChecked() for button in help_buttons) == 1
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() > small_scroll_maximum
    for info in help_buttons:
        if info.isChecked():
            info.click()
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() == small_scroll_maximum
    assert window.analysis_help_panel.isHidden()
    window.resize(1200, 900)
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() == 0


def test_data_overview_graphs_and_tables_use_original_recording(window):
    frame = pd.DataFrame(
        {"time": [0.0, 0.1, 0.2], "gyroscope_x": [1.0, np.nan, 3.0], "green": [5.0, 6.0, 7.0]}
    )
    original = frame.copy(deep=True)
    window.loaded(("sensor.csv", frame))
    assert [window.data_tabs.tabText(i) for i in range(3)] == ["Overview", "Graphs", "Tables"]
    assert [item.text() for item in window.data_values] == ["3", "3", "1"]
    assert window.data_tabs.widget(0).isAncestorOf(window.data_values[0])
    assert not hasattr(window, "data_metadata")
    assert window.data_tabs.widget(0).isAncestorOf(window.time_table)
    assert window.data_tabs.widget(1).isAncestorOf(window.data_channels)
    assert window.data_tabs.widget(2) is window.input_table
    summary = window.channel_table.model().frame.set_index("Channel")
    assert summary.index.tolist() == ["gyroscope_x", "green"]
    assert summary["Missing"].tolist() == [1, 0]
    assert summary.loc["gyroscope_x", "Median"] == 2
    assert summary.loc["gyroscope_x", "IQR"] == 1
    assert summary.loc["gyroscope_x", "Range"] == "1 – 3"
    timing = window.time_table.model().frame.set_index("Statistic")
    assert timing.loc["Estimated sampling rate (Hz)", "Value"] == pytest.approx(10)
    window.set_input_channels(["green"])
    line = window.data_figure.axes[0].lines[0]
    np.testing.assert_array_equal(line.get_xdata(), frame.time)
    np.testing.assert_array_equal(line.get_ydata(), frame.green)
    pd.testing.assert_frame_equal(window.input_table.model().frame, original)
    pd.testing.assert_frame_equal(frame, original)


def test_module_cards_allow_every_combination(window):
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0.0, 1.0]})))
    assert window.selected_modules() == ["gait"]
    window.module_buttons["Tremor"].click()
    assert window.selected_modules() == ["gait", "tremor"]
    window.module_buttons["Gait"].click()
    assert window.selected_modules() == ["tremor"]
    assert not window.side.isEnabled()
    window.module_buttons["Tremor"].click()
    assert window.selected_modules() == []
    assert not window.run_button.isEnabled()
    window.run_analysis()
    assert window.worker is None and window.runs == []
    assert "Select an analysis module" in window.notice.text()
    window.module_buttons["Gait"].click()
    window.module_buttons["Tremor"].click()
    window.module_buttons["Pulse rate"].click()
    assert window.selected_modules() == ["gait", "tremor", "pulse_rate"]
    assert window.side.isEnabled()
    window.module_buttons["Tremor"].click()
    assert window.selected_modules() == ["gait", "pulse_rate"]
    window.set_modules(["tremor", "pulse_rate"])
    assert window.selected_modules() == ["tremor", "pulse_rate"]
    window.set_modules(["pulse_rate"])
    assert "Accelerometer" in window.module_requirements.text()
    window.prepared.setChecked(True)
    assert window.module_requirements.text() == "Raw green PPG required."
    window.set_modules(["gait", "pulse_rate"])
    assert "Accelerometer" in window.module_requirements.text()


def test_inline_analysis_help_does_not_change_configuration(window):
    from paradigma_studio.analysis_help import FIELD_HELP

    assert set(window.analysis_help) == set(FIELD_HELP)

    def configuration():
        return (
            window.selected_modules(),
            window.side.currentText(),
            window.acc.currentText(),
            window.gyro.currentText(),
            window.time.currentText(),
            window.orientation.text(),
            window.prepared.isChecked(),
            window.gaps.isChecked(),
            window.drop_missing.isChecked(),
            window.max_gap.value(),
            window.min_segment.value(),
            window.mapping.toPlainText(),
        )

    before = configuration()
    window.navigate(1)
    window.show()
    for title, (info, description) in window.analysis_help.items():
        assert description.isHidden()
        assert info.accessibleName() == f"Information: {title}"
        info.click()
        assert not description.isHidden()
        assert "ParaDigMa documentation" in description.text()
        assert window.pages.widget(1).isAncestorOf(description)
        info.click()
        assert description.isHidden()
    assert configuration() == before
    assert "toolbox X = minus sensor Y" in window.analysis_help["Device axes"][1].text()
    assert "column_in_your_file" in window.analysis_help["Column mapping (JSON)"][1].text()


def test_input_graph_multi_selection_has_original_values_distinct_stable_colors_and_legend(window):
    frame = pd.DataFrame(
        {
            "time": [0.0, 0.1, 0.2],
            "gyroscope_x": [1.0, 2.0, 3.0],
            "gyroscope_y": [3.0, 2.0, 1.0],
            "gyroscope_z": [0.0, 1.0, 0.0],
        }
    )
    original = frame.copy(deep=True)
    window.loaded(("sensor.csv", frame))
    window.set_input_channels(["gyroscope_x", "gyroscope_z"])
    axes = window.data_figure.axes[0]
    lines = axes.lines
    assert [line.get_label() for line in lines] == ["gyroscope_x", "gyroscope_z"]
    assert lines[0].get_color() != lines[1].get_color()
    previous_color = lines[1].get_color()
    assert [text.get_text() for text in axes.get_legend().get_texts()] == [
        "gyroscope_x",
        "gyroscope_z",
    ]
    for line in lines:
        np.testing.assert_array_equal(line.get_xdata(), frame.time)
        np.testing.assert_array_equal(line.get_ydata(), frame[line.get_label()])
    window.data_channels.item(0).setCheckState(Qt.Unchecked)
    assert window.selected_input_channels() == ["gyroscope_z"]
    assert window.data_figure.axes[0].lines[0].get_color() == previous_color
    window.set_input_channels(window._channel_colors)
    assert len(window.data_figure.axes[0].lines) == 3
    window.set_input_channels([])
    assert not window.data_figure.axes[0].lines
    pd.testing.assert_frame_equal(window.input_table.model().frame, original)
    pd.testing.assert_frame_equal(frame, original)


def test_long_input_graphs_keep_bounded_display_sampling_per_selected_channel(window):
    t = np.arange(60001, dtype=float) / 100
    frame = pd.DataFrame({"time": t, "accelerometer_x": np.sin(t), "gyroscope_x": np.cos(t)})
    window.loaded(("long.csv", frame))
    window.set_input_channels(["accelerometer_x", "gyroscope_x"])
    step = 4
    assert len(window.data_figure.axes) == 2
    for line in (line for ax in window.data_figure.axes for line in ax.lines):
        assert len(line.get_ydata()) <= 20000
        np.testing.assert_array_equal(line.get_ydata(), frame[line.get_label()].iloc[::step])
    assert window.input_table.model().rowCount() == 60001


def test_data_time_units_are_explicit_and_do_not_change_analysis_parameters(window):
    window.loaded(
        (
            "milliseconds.csv",
            pd.DataFrame({"device_ticks": [0.0, 10.0, 20.0], "gyroscope_x": [1.0, 2.0, 3.0]}),
        )
    )
    window.data_time_channel.setCurrentIndex(window.data_time_channel.findData("device_ticks"))
    window.data_time_unit.setCurrentText("relative_ms")
    wait_for_previews(window)
    assert window.time.currentText() == "relative_s"
    stats = window.time_table.model().frame.set_index("Statistic")
    assert stats.loc["Estimated sampling rate (Hz)", "Value"] == pytest.approx(100)
    assert window.channel_table.model().frame.Channel.tolist() == ["gyroscope_x"]


def test_all_table_headings_are_left_aligned_and_fit_after_replacing_the_model(window):
    heading = "quantified_sensor_measurement_with_a_long_column_heading"
    frame = pd.DataFrame({heading: [1.0, 2.0], "short": [3.0, 4.0]})
    window.loaded(("sensor.csv", frame))
    window.analyzed({"quantifications": {"test": frame}, "errors": []})
    for widget in window.findChildren(desktop.ReadableTable):
        assert widget.horizontalHeader().defaultAlignment() & Qt.AlignLeft
        assert widget.horizontalHeader().textElideMode() == Qt.ElideNone
        if widget.model() is not None:
            for column in range(widget.model().columnCount()):
                title = widget.model().headerData(column, Qt.Horizontal)
                assert (
                    widget.columnWidth(column)
                    >= widget.horizontalHeader().fontMetrics().horizontalAdvance(title) + 28
                )
                assert widget.model().headerData(column, Qt.Horizontal, Qt.ToolTipRole) == title
    window.input_table.setColumnWidth(0, 20)
    assert window.input_table.columnWidth(0) >= window.input_table._heading_widths[0]


def test_metric_selection_and_zoom_leave_official_overview_aggregates_unchanged(window):
    frame = output().assign(other_metric=lambda data: data.metric * 2)
    window.analyzed(
        {
            "quantifications": {"test": frame},
            "aggregations": {"test": {"median_metric": 12.5}},
            "errors": [],
        }
    )
    aggregate = window.overview_values[("test", "Aggregates", ("median_metric",))]
    assert aggregate.text() == "12.5"
    assert not hasattr(window, "summary_table")
    select_plot_metric(window, "quantifications/test", "other_metric")
    np.testing.assert_array_equal(bar_values(window.figure.axes[0]), frame.other_metric)
    window.figure.axes[0].set_xlim(2.0, 4.0)
    assert window.overview_values[("test", "Aggregates", ("median_metric",))] is aggregate
    assert aggregate.text() == "12.5"
    pd.testing.assert_frame_equal(window.active_frame, frame)
    window.clear_results()
    assert window.overview_values == {}
    assert window.result_table.model() is None


def test_multi_selection_and_all_parameters_reach_analysis_and_history(window, monkeypatch):
    frame = pd.DataFrame({"time": [0.0, 1.0]})
    window.loaded(("sensor.csv", frame))
    window.module_buttons["Tremor"].click()
    window.side.setCurrentText("right")
    window.acc.setCurrentText("m/s^2")
    window.gyro.setCurrentText("rad/s")
    window.time.setCurrentText("relative_ms")
    window.orientation.setText("-y,x,z")
    window.mapping.setPlainText('{"device_time": "time"}')
    window.gaps.setChecked(True)
    window.max_gap.setValue(2.5)
    window.min_segment.setValue(4)
    window.drop_missing.setChecked(False)
    captured = []

    def analyze(source, logger, **settings):
        assert source is frame
        captured.append(settings)
        return {"quantifications": {"test": output()}, "errors": []}

    monkeypatch.setattr(desktop, "analyze", analyze)
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: desktop.analyze(frame, logger=logger, **settings),
    )
    window.run_analysis()
    wait_for_job(window)
    expected = dict(
        pipelines=["gait", "tremor"],
        watch_side="right",
        accelerometer_units="m/s^2",
        gyroscope_units="rad/s",
        time_input_unit="relative_ms",
        device_orientation=["-y", "x", "z"],
        column_mapping={"device_time": "time"},
        skip_preparation=False,
        split_by_gaps=True,
        drop_missing_samples=False,
        max_gap_seconds=2.5,
        min_segment_seconds=4.0,
    )
    assert captured == [expected]
    assert window.runs[0]["settings"] == {**expected, "plot_time_origin": {"mode": "automatic"}}
    window.set_modules(["pulse_rate"])
    window.gyro.setCurrentText("deg/s")
    window.use_run_parameters()
    assert window.pages.currentIndex() == 1
    assert window.selected_modules() == ["gait", "tremor"]
    assert window.gyro.currentText() == "rad/s"
    assert window.max_gap.value() == 2.5
    assert window.orientation.text() == "-y,x,z"
    assert json.loads(window.mapping.toPlainText()) == {"device_time": "time"}


def test_dropdown_popup_text_is_readable_under_dark_system_palette(tmp_path):
    app = QApplication.instance() or QApplication([])
    previous = app.palette()
    dark = QPalette(previous)
    for role in (QPalette.Window, QPalette.Base, QPalette.Button, QPalette.Highlight):
        dark.setColor(role, QColor("#101522"))
    dark.setColor(QPalette.Text, QColor("#000000"))
    dark.setColor(QPalette.HighlightedText, QColor("#000000"))
    app.setPalette(dark)
    window = None

    def luminance(color):
        channels = [color.redF(), color.greenF(), color.blueF()]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    try:
        window = MainWindow(history_dir=tmp_path / "runs")
        window.navigate(1)
        window.show()
        window.time.showPopup()
        app.processEvents()
        popup = window.time.view().window()
        assert popup.palette().color(QPalette.Window).name() == "#ffffff"
        assert popup.autoFillBackground()
        for combo in window.findChildren(QComboBox):
            palette = combo.view().palette()
            for foreground, background in (
                (QPalette.Text, QPalette.Base),
                (QPalette.HighlightedText, QPalette.Highlight),
            ):
                values = sorted(
                    [
                        luminance(palette.color(QPalette.Active, foreground)),
                        luminance(palette.color(QPalette.Active, background)),
                    ]
                )
                assert (values[1] + 0.05) / (values[0] + 0.05) >= 4.5
        for checkbox in (window.prepared, window.gaps, window.drop_missing):
            assert checkbox.palette().color(QPalette.WindowText).name() == "#22324a"
        window.time.hidePopup()
    finally:
        if window is not None:
            window.close()
        app.setPalette(previous)


def test_graph_zoom_preserves_full_official_table_and_csv(window, tmp_path, monkeypatch):
    window.timing_toggle.setChecked(True)
    frame = output()
    window.analyzed({"quantifications": {"test": frame}})
    assert not hasattr(window, "time_from") and not hasattr(window, "filters_toggle")
    for limits in ((4.0, 5.0), (9.0, 10.0)):
        window.figure.axes[0].set_xlim(*limits)
        np.testing.assert_array_equal(window.active_positions, np.arange(len(frame)))
        pd.testing.assert_frame_equal(window.active_frame, frame)
        pd.testing.assert_frame_equal(window.result_table.model().frame[frame.columns], frame)
        np.testing.assert_allclose(bar_starts(window.figure.axes[0]), frame.time, atol=1e-12)
        np.testing.assert_array_equal(bar_values(window.figure.axes[0]), frame.metric)
        assert len(bar_values(window.figure.axes[0])) == len(frame)
    path = tmp_path / "full.csv"
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.export_csv()
    pd.testing.assert_frame_equal(pd.read_csv(path)[frame.columns], frame)


def test_graph_click_selects_nearest_row_within_active_selection(window):
    window.analyzed({"quantifications": {"test": output()}, "errors": []})
    window.graph_clicked(SimpleNamespace(inaxes=window.figure.axes[0], xdata=3.1))
    assert window.result_table.currentIndex().row() == 3
    assert window.active_frame.iloc[3]["time"] == 3.0


def test_context_drills_into_original_mapped_sensor_values(window):
    frame = pd.DataFrame(
        {
            "timestamp": 1_700_000_000_000 + np.arange(3001) * 10,
            "gyr_x": np.arange(3001, dtype=float) * 100,
        },
        index=np.arange(3001) + 500,
    )
    original = frame.copy()
    window.loaded(("sensor.csv", frame))
    window.provenance = {
        "source": "sensor.csv",
        "settings": {
            "time_input_unit": "absolute_ms",
            "column_mapping": {"timestamp": "time"},
            "pipelines": ["tremor"],
            "drop_missing_samples": True,
        },
    }
    window.analyzed(
        {
            "quantifications": {
                "tremor": pd.DataFrame({"time": [15.0, 25.0], "metric": [5.0, 6.0]})
            },
            "errors": [],
        }
    )
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    assert window.context_button.isEnabled()
    assert not hasattr(window, "context_radius")
    window.inspect_sensor_context()
    assert window.result_tabs.currentIndex() == window.sensor_tab_index
    assert window.result_tabs.isTabVisible(window.sensor_tab_index)
    mask = np.abs(np.arange(3001) / 100 - 15.0) <= 10.0
    pd.testing.assert_frame_equal(
        window.sensor_table.model().frame, frame.iloc[np.flatnonzero(mask)]
    )
    assert (
        list(window.sensor_figure.axes[0].lines[0].get_ydata())
        == frame.iloc[np.flatnonzero(mask)]["gyr_x"].tolist()
    )
    assert window._sensor_context.end - window._sensor_context.start == 20
    pd.testing.assert_frame_equal(frame, original)
    window.hide_sensor_context()
    assert not window.result_tabs.isTabVisible(window.sensor_tab_index)


def test_missing_original_recording_disables_sensor_context(window):
    window.analyzed(
        {
            "quantifications": {"tremor": pd.DataFrame({"time": [1.0, 2.0], "power": [1.0, 2.0]})},
            "errors": [],
        }
    )
    assert not hasattr(window, "participant")
    assert not hasattr(window, "filter_column")
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    assert not window.context_button.isEnabled()
    assert window.context_button.toolTip() == "Original sensor data unavailable"


def test_gait_defaults_to_measurement_and_drills_using_explicit_segment_metadata(window):
    window.timing_toggle.setChecked(True)
    raw = pd.DataFrame({"time": np.arange(40) / 10, "gyroscope_x": np.arange(40, dtype=float)})
    window.loaded(("sensor.csv", raw))
    quantified = pd.DataFrame({"gait_segment_nr": [3, 3], "range_of_motion": [20.0, 30.0]})
    window.provenance = {"source": "sensor.csv", "settings": {"skip_preparation": True}}
    window.analyzed(
        {
            "quantifications": {"gait": {"unfiltered": quantified}},
            "metadata": {
                "gait": {"unfiltered": {"per_segment": {"3": {"start_s": 1.0, "end_s": 2.0}}}}
            },
            "errors": [],
        }
    )
    assert window.y_column.currentData() == "range_of_motion"
    assert window.result_table.model().frame["Analysis time (s)"].tolist() == [1.25, 1.75]
    assert window.result_table.model().frame["Time basis"].eq("Estimated within gait segment").all()
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    assert window.context_button.isEnabled()
    assert window.context_button.text() == "Inspect gait segment"
    assert window.time_axis.selection_label.get_text() == "1.25 s"
    window.inspect_sensor_context()
    pd.testing.assert_frame_equal(window.sensor_table.model().frame, raw.iloc[10:20])
    assert not window._sensor_context.include_end
    window.analyzed({"quantifications": {"gait": {"unfiltered": quantified}}, "errors": []})
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    assert not window.context_button.isEnabled()  # No inferred timing without metadata.


def test_nullable_result_values_plot_without_losing_rows(window):
    frame = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0], "power": pd.Series([1.0, pd.NA, 3.0], dtype="Float64")}
    )
    window.analyzed({"quantifications": {"tremor": frame}, "errors": []})
    assert window.result_table.model().rowCount() == 3
    np.testing.assert_array_equal(bar_values(window.figure.axes[0]), [1.0, 3.0])
    np.testing.assert_allclose(bar_starts(window.figure.axes[0]), [0.0, 2.0], atol=1e-12)


def test_completed_and_failed_runs_persist_and_previous_result_can_reopen(window, monkeypatch):
    frame = pd.DataFrame({"time": [0.0, 1.0], "gyroscope_x": [1.0, 2.0]})
    window.loaded(("first.csv", frame))
    window.set_modules(["tremor"])

    def analyze(frame, logger, **settings):
        logger.warning("Example quality warning")
        return {"quantifications": {"tremor": output()}, "errors": []}

    monkeypatch.setattr(desktop, "analyze", analyze)
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: desktop.analyze(frame, logger=logger, **settings),
    )
    window.run_analysis()
    window.navigate(3)  # Navigation stays available while analysis runs.
    wait_for_job(window)
    first = window.runs[0]
    assert first["status"] == "Completed"
    assert "Example quality warning" in first["warnings"]
    saved = json.loads((window.history.directory / f"{first['id']}.json").read_text())
    assert "_frame" not in saved and "_results" not in saved
    assert saved["settings"]["pipelines"] == ["tremor"]
    assert window.pages.currentIndex() == 2

    def fail(*args, **kwargs):
        raise ValueError("Sensor validation failed")

    monkeypatch.setattr(desktop, "analyze", fail)
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: desktop.analyze(frame, logger=logger, **settings),
    )
    window.loaded(("second.csv", frame.copy()))
    window.run_analysis()
    wait_for_job(window)
    assert window.runs[0]["status"] == "Failed"
    assert window.runs[0]["warnings"] == []
    assert window.runs[0]["errors"] == ["ValueError: Sensor validation failed"]
    assert window.run_errors.toPlainText() == "ValueError: Sensor validation failed"
    assert window.run_warnings.toPlainText() == "No recorded warnings."
    assert "0 warning(s), 1 error(s)" in window.run_summary.text()
    assert window.run_button.isEnabled() and window.open_button.isEnabled()
    assert window.settings_panel.isEnabled() and window.analysis_controls.isEnabled()
    window.run_table.setCurrentIndex(window.run_table.model().index(1, 0))
    window.open_run()
    assert window.current_run is first
    assert window.provenance["source"] == "first.csv"
    assert window.source == "second.csv"  # Exploring history does not replace input.
    assert window.result_source_frame is frame
    assert window.result_table.model().rowCount() == 6


def test_exported_json_can_reopen_after_restart_without_loading_pickle(
    window, tmp_path, monkeypatch
):
    window.loaded((str(tmp_path / "trusted.pkl"), pd.DataFrame({"time": [0.0, 1.0]})))
    monkeypatch.setattr(
        desktop,
        "analyze",
        lambda *args, **kwargs: {"quantifications": {"tremor": output()}, "errors": []},
    )
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: desktop.analyze(frame, logger=logger, **settings),
    )
    window.set_modules(["tremor"])
    window.run_analysis()
    wait_for_job(window)
    target = tmp_path / "results.json"
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    window.export()
    assert window.current_run["outputs"][-1]["path"] == str(target)
    reopened = MainWindow(history_dir=window.history.directory)
    try:
        monkeypatch.setattr(
            desktop,
            "load_sensor_file",
            lambda *args, **kwargs: pytest.fail("Must not reload source recording"),
        )
        assert reopened.open_run_button.isEnabled()
        reopened.open_run()
        wait_for_job(reopened)
        assert reopened.frame is None
        assert reopened.result_source_frame is None
        assert reopened.result_table.model().rowCount() == 6
        assert reopened.provenance["source"].endswith("trusted.pkl")
        assert not reopened.context_button.isEnabled()
    finally:
        reopened.close()


@pytest.mark.parametrize("target_input", ["previous", "current"])
def test_export_protects_result_source_and_current_input(
    window, tmp_path, monkeypatch, target_input
):
    original = tmp_path / "original.csv"
    original.write_text("original samples")
    window.loaded((str(original), pd.DataFrame({"time": [0.0, 1.0]})))
    window.provenance = {"source": str(original), "settings": {}}
    window.analyzed({"quantifications": {"tremor": output()}, "errors": []})
    current = tmp_path / "new.csv"
    current.write_text("current sensor samples")
    window.loaded((str(current), pd.DataFrame({"time": [5.0, 6.0]})))
    target = original if target_input == "previous" else current
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    window.export_csv()
    assert original.read_text() == "original samples"
    assert current.read_text() == "current sensor samples"
    assert "cannot overwrite" in window.notice.text()


def test_history_write_failure_keeps_result_available(window, monkeypatch):
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0.0, 1.0]})))
    monkeypatch.setattr(
        desktop,
        "analyze",
        lambda *args, **kwargs: {"quantifications": {"test": output()}, "errors": []},
    )
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: desktop.analyze(frame, logger=logger, **settings),
    )

    def cannot_save(record):
        raise OSError("disk is read-only")

    monkeypatch.setattr(window.history, "save", cannot_save)
    window.run_analysis()
    wait_for_job(window)
    assert window.result_table.model().rowCount() == 6
    assert window.export_button.isEnabled()
    assert window.runs[0]["status"] == "Completed"
    assert "history could not be saved" in window.notice.text()


def test_history_rejects_damaged_entries_and_marks_unfinished_runs(tmp_path):
    history = RunHistory(tmp_path / "runs")
    record = new_run("sensor.csv", {"pipelines": ["tremor"]})
    history.save(record)
    (history.directory / "bad.json").write_text("{broken")
    records, issues = history.load()
    assert len(records) == 1 and records[0]["status"] == "Unfinished"
    assert len(issues) == 1
    record["outputs"] = ["not an output object"]
    history.save(record)
    assert history.load()[0] == []


@pytest.mark.parametrize("unit", ["difference_s", "difference_ms"])
def test_sensor_context_preserves_elapsed_time_when_missing_rows_were_excluded(unit):
    scale = 1000 if unit.endswith("ms") else 1
    frame = pd.DataFrame(
        {
            "time": np.array([0.1, 0.1, 0.3, 0.1]) * scale,
            "gyroscope_x": [1.0, np.nan, 1.0, 1.0],
            "gyroscope_y": 1.0,
            "gyroscope_z": 1.0,
        }
    )
    aligned = source_timeline(
        frame, {"time_input_unit": unit, "pipelines": ["tremor"], "drop_missing_samples": True}
    )
    assert aligned == pytest.approx([0.0, 0.1, 0.4, 0.5])


def test_sensor_context_absolute_origin_uses_first_retained_sample():
    frame = pd.DataFrame(
        {
            "time": [1000.0, 1001.0, 1002.0],
            "gyroscope_x": [np.nan, 1.0, 1.0],
            "gyroscope_y": 1.0,
            "gyroscope_z": 1.0,
        }
    )
    settings = {
        "time_input_unit": "absolute_s",
        "pipelines": ["tremor"],
        "drop_missing_samples": True,
    }
    assert source_timeline(frame, settings).tolist() == [-1.0, 0.0, 1.0]


def test_run_warning_and_error_counts_match_details_without_duplicate_pipeline_failures(
    window, monkeypatch
):
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0.0, 1.0]})))

    def partial(frame, logger, **settings):
        logger.warning("Some windows excluded")
        logger.warning("tremor pipeline returned error: No tremor windows")
        logger.error("Modules pulse_rate failed: No pulse signal")
        logger.warning("ParaDigMa analysis completed with 2 error(s)")
        return {
            "quantifications": {"gait": output()},
            "errors": [
                {"pipeline": "tremor", "stage": "pipeline_execution", "error": "No tremor windows"},
                {
                    "pipelines": ["pulse_rate"],
                    "stage": "desktop_execution",
                    "error": "ValueError: No pulse signal",
                },
            ],
        }

    monkeypatch.setattr(desktop, "analyze", partial)
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: desktop.analyze(frame, logger=logger, **settings),
    )
    window.run_analysis()
    wait_for_job(window)
    record = window.runs[0]
    assert record["status"] == "Partial"
    assert record["warnings"] == ["Some windows excluded"]
    assert len(record["errors"]) == 2
    assert "tremor" in record["errors"][0] and "pulse_rate" in record["errors"][1]
    assert window.run_table.model().frame.loc[0, ["Warnings", "Errors"]].tolist() == [1, 2]
    assert "1 warning(s), 2 error(s)" in window.run_summary.text()
    assert window.run_warnings.toPlainText() == "Some windows excluded"
    assert window.run_errors.toPlainText() == "\n\n".join(record["errors"])
    assert "2 processing error(s)" in window.status.text()
    assert window.notice.property("severity") == "error"
    saved, issues = window.history.load()
    assert not issues and saved[0]["errors"] == record["errors"]
    assert saved[0]["warnings"] == record["warnings"]


def test_no_quantified_windows_is_a_warning_without_processing_errors(window, monkeypatch):
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0.0, 1.0]})))
    monkeypatch.setattr(
        desktop,
        "analyze",
        lambda *args, **kwargs: {"quantifications": {"tremor": pd.DataFrame()}, "errors": []},
    )
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: desktop.analyze(frame, logger=logger, **settings),
    )
    window.run_analysis()
    wait_for_job(window)
    record = window.runs[0]
    assert record["status"] == "Completed"
    assert len(record["warnings"]) == 1 and record["errors"] == []
    assert window.run_table.model().frame.loc[0, "Status"] == "Completed with warnings"
    assert window.run_heading.text().startswith("Completed with warnings")
    assert window.notice.property("severity") == "warning"


def test_legacy_history_moves_known_failures_to_errors_and_preserves_quality_warnings(tmp_path):
    history = RunHistory(tmp_path)
    record = new_run("sensor.csv", {"pipelines": ["tremor"]})
    record.pop("errors")
    record["status"] = "Partial"
    record["warnings"] = [
        "Quality warning",
        "ParaDigMa analysis completed with 1 error(s)",
        "tremor pipeline returned error: Failed aggregation",
        json.dumps(
            {"pipeline": "tremor", "stage": "pipeline_execution", "error": "Failed aggregation"}
        ),
    ]
    history.save(record)
    records, issues = history.load()
    assert not issues
    assert records[0]["warnings"] == ["Quality warning"]
    assert records[0]["errors"] == ["tremor · pipeline_execution: Failed aggregation"]
    record["status"] = "Failed"
    record["warnings"] = ["Quality warning", "ValueError: Invalid data"]
    history.save(record)
    records, issues = history.load()
    assert not issues
    assert records[0]["warnings"] == ["Quality warning"]
    assert records[0]["errors"] == ["ValueError: Invalid data"]
    record["errors"] = "invalid"
    history.save(record)
    assert history.load()[0] == []


def test_running_problem_counts_update_immediately(window):
    record = new_run("sensor.csv", {"pipelines": ["tremor"]})
    window.runs.insert(0, record)
    window.active_run = record
    window.refresh_runs()
    window.capture_warning("Quality warning")
    window.capture_error("Pipeline error")
    window.capture_warning("Quality warning")
    window.capture_error("Pipeline error")
    assert window.run_table.model().frame.loc[0, ["Warnings", "Errors"]].tolist() == [1, 1]
    assert "1 warning(s), 1 error(s)" in window.run_summary.text()
    assert window.run_warnings.toPlainText() == "Quality warning"
    assert window.run_errors.toPlainText() == "Pipeline error"
    window.finish_run("Completed")
    assert record["status"] == "Partial"


def test_legacy_history_rejects_non_text_warnings_without_crashing(tmp_path):
    history = RunHistory(tmp_path)
    record = new_run("sensor.csv", {"pipelines": ["tremor"]})
    record.pop("errors")
    record["warnings"] = [42]
    history.save(record)
    records, issues = history.load()
    assert records == [] and len(issues) == 1


def test_identical_errors_in_different_recording_sections_remain_separate():
    from paradigma_studio.history import merge_errors

    errors = [
        {
            "pipeline": "tremor",
            "stage": "pipeline_execution",
            "file": section,
            "error": "No windows",
        }
        for section in ("section_1", "section_2")
    ]
    messages = merge_errors(["tremor pipeline returned error: No windows"], errors)
    assert messages == [
        "tremor · pipeline_execution · section_1: No windows",
        "tremor · pipeline_execution · section_2: No windows",
    ]
