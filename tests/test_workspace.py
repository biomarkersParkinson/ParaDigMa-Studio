"""Behavioral checks for navigation, linked exploration and previous runs."""
import json
import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
import pytest
from PySide6.QtTest import QTest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton, QTableView
from PySide6.QtCore import Qt

from paradigma_desktop import app as desktop
from paradigma_desktop.app import MainWindow
from paradigma_desktop.core import export_results
from paradigma_desktop.exploration import source_timeline
from paradigma_desktop.history import RunHistory, load_result_export, new_run


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
    return pd.DataFrame({"time": np.arange(6, dtype=float),
        "participant_id": ["a", "b", "a", "b", "a", "b"],
        "file_key": ["segment_1"] * 3 + ["segment_2"] * 3,
        "metric": np.arange(10, 16, dtype=float)})


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
    from paradigma_desktop.analysis_help import DEFAULT_MAX_GAP_SECONDS, DEFAULT_MIN_SECTION_SECONDS
    defaults = signature(prepare_raw_data).parameters
    assert window.max_gap.value() == DEFAULT_MAX_GAP_SECONDS == defaults["max_segment_gap_s"].default
    assert window.min_segment.value() == DEFAULT_MIN_SECTION_SECONDS == defaults["min_segment_length_s"].default
    assert window.gaps.isChecked() == signature(run_paradigma).parameters["split_by_gaps"].default
    assert window.acc.currentText() == signature(run_paradigma).parameters["accelerometer_units"].default
    assert window.gyro.currentText() == signature(run_paradigma).parameters["gyroscope_units"].default
    assert window.time.currentText() == signature(run_paradigma).parameters["time_input_unit"].default
    assert window.orientation.text().split(",") == signature(run_paradigma).parameters["device_orientation"].default
    assert window.prepared.isChecked() == signature(run_paradigma).parameters["skip_preparation"].default
    window.navigate(1)
    window.show()
    QApplication.instance().processEvents()
    for prepared in (False, True):
        window.prepared.setChecked(prepared)
        window.max_gap.setValue(4.)
        window.min_segment.setValue(8.)
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
    ys = [item.mapTo(window.settings_panel, QPoint(0, 0)).y() for item in
          (window.gaps, window.max_gap, window.min_segment, window.mapping, window.prepared)]
    assert ys == sorted(ys)


def test_run_button_remains_visible_in_compact_analysis_workspace(window):
    app = QApplication.instance()
    window.navigate(1)
    window.sidebar.setExpanded(False, animated=False)
    window.resize(1050, 720)
    window.show()
    app.processEvents()
    assert window.run_button.isVisible()
    assert window.run_button.parentWidget() is window.pages.widget(1)
    assert window.run_button.geometry().bottom() <= window.pages.widget(1).height()


@pytest.mark.parametrize("control_minimum_height, larger_surrounding_controls", [(0, False), (40, False), (44, False), (44, True)])
def test_compact_analysis_fits_all_parameters_and_uniform_help_without_scrolling(window, control_minimum_height, larger_surrounding_controls):
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0., 1.], "gyroscope_x": [1., 2.]})))
    window.set_modules(["gait", "tremor", "pulse_rate"])
    # Larger native Windows control hints overflowed the previous layout even
    # though the same fields fitted under the headless Linux font metrics.
    for control in (window.side, window.acc, window.gyro, window.time, window.orientation,
                    window.max_gap, window.min_segment):
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
    window.resize(960, 650)
    window.show()
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() == 0
    for control in (window.side, window.acc, window.gyro, window.time, window.orientation,
                    window.gaps, window.max_gap, window.min_segment, window.mapping, window.prepared,
                    *window.section_reset_buttons.values()):
        assert control.visibleRegion().boundingRect().contains(control.rect())
    help_buttons = [info for info, description in window.analysis_help.values()]
    assert {(info.width(), info.height()) for info in help_buttons} == {(22, 22)}
    assert all(info.objectName() == "helpInfo" and info.isCheckable() for info in help_buttons)
    for info in help_buttons:
        info.click()
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() > 0
    for info in help_buttons:
        info.click()
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() == 0


def test_data_overview_graphs_and_tables_use_original_recording(window):
    frame = pd.DataFrame({"time": [0., .1, .2], "gyroscope_x": [1., np.nan, 3.], "green": [5., 6., 7.]})
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
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0., 1.]})))
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
    from paradigma_desktop.analysis_help import FIELD_HELP
    assert set(window.analysis_help) == set(FIELD_HELP)
    def configuration():
        return (window.selected_modules(), window.side.currentText(), window.acc.currentText(),
                window.gyro.currentText(), window.time.currentText(), window.orientation.text(),
                window.prepared.isChecked(), window.gaps.isChecked(), window.drop_missing.isChecked(),
                window.max_gap.value(), window.min_segment.value(), window.mapping.toPlainText())
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
    frame = pd.DataFrame({"time": [0., .1, .2], "gyroscope_x": [1., 2., 3.],
                          "gyroscope_y": [3., 2., 1.], "gyroscope_z": [0., 1., 0.]})
    original = frame.copy(deep=True)
    window.loaded(("sensor.csv", frame))
    window.set_input_channels(["gyroscope_x", "gyroscope_z"])
    axes = window.data_figure.axes[0]
    lines = axes.lines
    assert [line.get_label() for line in lines] == ["gyroscope_x", "gyroscope_z"]
    assert lines[0].get_color() != lines[1].get_color()
    previous_color = lines[1].get_color()
    assert [text.get_text() for text in axes.get_legend().get_texts()] == ["gyroscope_x", "gyroscope_z"]
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
    for line in window.data_figure.axes[0].lines:
        assert len(line.get_ydata()) <= 20000
        np.testing.assert_array_equal(line.get_ydata(), frame[line.get_label()].iloc[::step])
    assert window.input_table.model().rowCount() == 60001


def test_data_time_units_are_explicit_and_do_not_change_analysis_parameters(window):
    window.loaded(("milliseconds.csv", pd.DataFrame({"device_ticks": [0., 10., 20.], "gyroscope_x": [1., 2., 3.]})))
    window.data_time_channel.setCurrentIndex(window.data_time_channel.findData("device_ticks"))
    window.data_time_unit.setCurrentText("relative_ms")
    assert window.time.currentText() == "relative_s"
    stats = window.time_table.model().frame.set_index("Statistic")
    assert stats.loc["Estimated sampling rate (Hz)", "Value"] == pytest.approx(100)
    assert window.channel_table.model().frame.Channel.tolist() == ["gyroscope_x"]


def test_all_table_headings_are_left_aligned_and_fit_after_replacing_the_model(window):
    heading = "quantified_sensor_measurement_with_a_long_column_heading"
    frame = pd.DataFrame({heading: [1., 2.], "short": [3., 4.]})
    window.loaded(("sensor.csv", frame))
    window.analyzed({"quantifications": {"test": frame}, "errors": []})
    for widget in window.findChildren(desktop.ReadableTable):
        assert widget.horizontalHeader().defaultAlignment() & Qt.AlignLeft
        assert widget.horizontalHeader().textElideMode() == Qt.ElideNone
        if widget.model() is not None:
            for column in range(widget.model().columnCount()):
                title = widget.model().headerData(column, Qt.Horizontal)
                assert widget.columnWidth(column) >= widget.horizontalHeader().fontMetrics().horizontalAdvance(title) + 28
                assert widget.model().headerData(column, Qt.Horizontal, Qt.ToolTipRole) == title
    window.input_table.setColumnWidth(0, 20)
    assert window.input_table.columnWidth(0) >= window.input_table._heading_widths[0]


def test_metric_and_filter_changes_leave_official_overview_aggregates_unchanged(window):
    frame = output().assign(other_metric=lambda data: data.metric * 2)
    window.analyzed({"quantifications": {"test": frame},
                     "aggregations": {"test": {"median_metric": 12.5}}, "errors": []})
    aggregate = window.overview_values[("test", "Aggregates", ("median_metric",))]
    assert aggregate.text() == "12.5"
    assert not hasattr(window, "summary_table")
    window.y_column.setCurrentText("other_metric")
    np.testing.assert_array_equal(window.figure.axes[0].lines[0].get_ydata(), frame.other_metric)
    window.time_from.setText("2")
    window.time_to.setText("4")
    window.apply_filters()
    assert window.overview_values[("test", "Aggregates", ("median_metric",))] is aggregate
    assert aggregate.text() == "12.5"
    pd.testing.assert_frame_equal(window.active_frame, frame.iloc[[2, 3, 4]])
    window.clear_results()
    assert window.overview_values == {}
    assert window.result_table.model() is None


def test_multi_selection_and_all_parameters_reach_analysis_and_history(window, monkeypatch):
    frame = pd.DataFrame({"time": [0., 1.]})
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
    window.run_analysis()
    wait_for_job(window)
    expected = dict(pipelines=["gait", "tremor"], watch_side="right", accelerometer_units="m/s^2",
        gyroscope_units="rad/s", time_input_unit="relative_ms", device_orientation=["-y", "x", "z"],
        column_mapping={"device_time": "time"}, skip_preparation=False, split_by_gaps=True,
        drop_missing_samples=False, max_gap_seconds=2.5, min_segment_seconds=4.)
    assert captured == [expected]
    assert window.runs[0]["settings"] == expected
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
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]
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
            for foreground, background in ((QPalette.Text, QPalette.Base),
                                            (QPalette.HighlightedText, QPalette.Highlight)):
                values = sorted([luminance(palette.color(QPalette.Active, foreground)),
                                 luminance(palette.color(QPalette.Active, background))])
                assert (values[1] + .05) / (values[0] + .05) >= 4.5
        for checkbox in (window.prepared, window.gaps, window.drop_missing):
            assert checkbox.palette().color(QPalette.WindowText).name() == "#22324a"
        window.time.hidePopup()
    finally:
        if window is not None:
            window.close()
        app.setPalette(previous)


def test_one_selection_drives_detailed_graph_table_and_csv(window, tmp_path, monkeypatch):
    window.timing_toggle.setChecked(True)
    frame = output()
    original = frame.copy()
    window.analyzed({"quantifications": {"test": frame}, "errors": []})
    window.time_from.setText("4")
    window.time_to.setText("4")
    window.apply_filters()
    assert window.active_positions.tolist() == [4]
    pd.testing.assert_frame_equal(window.result_table.model().frame[frame.columns], frame.iloc[[4]])
    assert list(window.figure.axes[0].lines[0].get_xdata()) == [4.]
    assert list(window.figure.axes[0].lines[0].get_ydata()) == [14.]
    assert "1 / 6 rows" in window.selection_note.text()
    assert window.result_table.model().frame["Analysis time (s)"].tolist() == [4.]
    path = tmp_path / "selection.csv"
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.export_csv()
    assert pd.read_csv(path)["metric"].tolist() == [14.]
    window.reset_filters()
    assert len(window.active_frame) == 6
    assert window.result_table.model().rowCount() == 6
    pd.testing.assert_frame_equal(frame, original)


def test_invalid_filter_retains_selection_and_empty_filter_clears_graph(window):
    window.analyzed({"quantifications": {"test": output()}, "errors": []})
    window.time_from.setText("5")
    window.time_to.setText("1")
    window.apply_filters()
    assert "minimum" in window.filter_status.text()
    assert len(window.active_frame) == window.result_table.model().rowCount() == 6
    window.time_from.setText("9")
    window.time_to.setText("10")
    window.apply_filters()
    assert window.active_frame.empty
    assert window.result_table.model().rowCount() == 0
    assert not window.figure.axes[0].lines
    assert "0 / 6 rows" in window.selection_note.text()


def test_graph_click_selects_nearest_row_within_active_selection(window):
    window.analyzed({"quantifications": {"test": output()}, "errors": []})
    window.time_from.setText("2")
    window.apply_filters()
    window.graph_clicked(SimpleNamespace(inaxes=window.figure.axes[0], xdata=3.1))
    assert window.result_table.currentIndex().row() == 1
    assert window.active_frame.iloc[1]["time"] == 3.


def test_context_drills_into_original_mapped_sensor_values(window):
    frame = pd.DataFrame({"timestamp": 1_700_000_000_000 + np.arange(301) * 10,
                          "gyr_x": np.arange(301, dtype=float) * 100}, index=np.arange(301) + 500)
    original = frame.copy()
    window.loaded(("sensor.csv", frame))
    window.provenance = {"source": "sensor.csv", "settings": {
        "time_input_unit": "absolute_ms", "column_mapping": {"timestamp": "time"},
        "pipelines": ["tremor"], "drop_missing_samples": True}}
    window.analyzed({"quantifications": {"tremor": pd.DataFrame({"time": [1., 2.], "metric": [5., 6.]})}, "errors": []})
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    assert window.context_button.isEnabled()
    window.context_radius.setValue(.2)
    window.inspect_sensor_context()
    assert window.result_tabs.currentIndex() == window.sensor_tab_index
    assert window.result_tabs.isTabVisible(window.sensor_tab_index)
    mask = np.abs(np.arange(301) / 100 - 1.) <= .2
    pd.testing.assert_frame_equal(window.sensor_table.model().frame, frame.iloc[np.flatnonzero(mask)])
    assert list(window.sensor_figure.axes[0].lines[0].get_ydata()) == frame.iloc[np.flatnonzero(mask)]["gyr_x"].tolist()
    assert "not the algorithm's exact window" in window.sensor_note.text()
    pd.testing.assert_frame_equal(frame, original)
    window.hide_sensor_context()
    assert not window.result_tabs.isTabVisible(window.sensor_tab_index)


def test_time_only_filters_and_missing_original_recording_are_explicit(window):
    window.analyzed({"quantifications": {"tremor": pd.DataFrame({"time": [1., 2.], "power": [1., 2.]})}, "errors": []})
    assert not hasattr(window, "participant")
    assert not hasattr(window, "filter_column")
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    assert not window.context_button.isEnabled()
    assert window.context_button.toolTip() == "Original sensor data unavailable"


def test_gait_defaults_to_measurement_and_drills_using_explicit_segment_metadata(window):
    window.timing_toggle.setChecked(True)
    raw = pd.DataFrame({"time": np.arange(40) / 10, "gyroscope_x": np.arange(40, dtype=float)})
    window.loaded(("sensor.csv", raw))
    quantified = pd.DataFrame({"gait_segment_nr": [3, 3], "range_of_motion": [20., 30.]})
    window.provenance = {"source": "sensor.csv", "settings": {"skip_preparation": True}}
    window.analyzed({"quantifications": {"gait": {"unfiltered": quantified}},
        "metadata": {"gait": {"unfiltered": {"per_segment": {"3": {"start_s": 1., "end_s": 2.}}}}}, "errors": []})
    assert window.y_column.currentData() == "range_of_motion"
    assert window.result_table.model().frame["Analysis time (s)"].tolist() == [1.25, 1.75]
    assert window.result_table.model().frame["Time basis"].eq("Estimated within gait segment").all()
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    assert window.context_button.isEnabled()
    assert window.context_button.text() == "Inspect gait segment"
    assert "Estimated" in window.time_axis.selection_label.get_text()
    window.inspect_sensor_context()
    pd.testing.assert_frame_equal(window.sensor_table.model().frame, raw.iloc[10:20])
    assert "using toolbox metadata" in window.sensor_note.text()
    assert "Individual arm-swing timestamps are not provided" in window.sensor_note.text()
    window.analyzed({"quantifications": {"gait": {"unfiltered": quantified}}, "errors": []})
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    assert not window.context_button.isEnabled()  # No inferred timing without metadata.


def test_nullable_result_values_plot_without_losing_rows(window):
    frame = pd.DataFrame({"time": [0., 1., 2.], "power": pd.Series([1., pd.NA, 3.], dtype="Float64")})
    window.analyzed({"quantifications": {"tremor": frame}, "errors": []})
    assert window.result_table.model().rowCount() == 3
    assert np.isnan(window.figure.axes[0].lines[0].get_ydata()[1])


def test_completed_and_failed_runs_persist_and_previous_result_can_reopen(window, monkeypatch):
    frame = pd.DataFrame({"time": [0., 1.], "gyroscope_x": [1., 2.]})
    window.loaded(("first.csv", frame))
    window.set_modules(["tremor"])
    def analyze(frame, logger, **settings):
        logger.warning("Example quality warning")
        return {"quantifications": {"tremor": output()}, "errors": []}
    monkeypatch.setattr(desktop, "analyze", analyze)
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


def test_exported_json_can_reopen_after_restart_without_loading_pickle(window, tmp_path, monkeypatch):
    window.loaded((str(tmp_path / "trusted.pkl"), pd.DataFrame({"time": [0., 1.]})))
    monkeypatch.setattr(desktop, "analyze", lambda *args, **kwargs: {"quantifications": {"tremor": output()}, "errors": []})
    window.set_modules(["tremor"])
    window.run_analysis()
    wait_for_job(window)
    target = tmp_path / "results.json"
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    window.export()
    assert window.current_run["outputs"][-1]["path"] == str(target)
    reopened = MainWindow(history_dir=window.history.directory)
    try:
        monkeypatch.setattr(desktop, "load_sensor_file", lambda *args, **kwargs: pytest.fail("Must not reload source recording"))
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
def test_export_protects_result_source_and_current_input(window, tmp_path, monkeypatch, target_input):
    original = tmp_path / "original.csv"
    original.write_text("original samples")
    window.loaded((str(original), pd.DataFrame({"time": [0., 1.]})))
    window.provenance = {"source": str(original), "settings": {}}
    window.analyzed({"quantifications": {"tremor": output()}, "errors": []})
    current = tmp_path / "new.csv"
    current.write_text("current sensor samples")
    window.loaded((str(current), pd.DataFrame({"time": [5., 6.]})))
    target = original if target_input == "previous" else current
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    window.export_csv()
    assert original.read_text() == "original samples"
    assert current.read_text() == "current sensor samples"
    assert "cannot overwrite" in window.notice.text()


def test_history_write_failure_keeps_result_available(window, monkeypatch):
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0., 1.]})))
    monkeypatch.setattr(desktop, "analyze", lambda *args, **kwargs: {"quantifications": {"test": output()}, "errors": []})
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


def test_export_round_trip_preserves_numeric_columns_and_float_values(tmp_path):
    path = tmp_path / "results.json"
    frame = pd.DataFrame({0: [np.nextafter(1., 2.), None], "power": [2., 3.]})
    export_results(path, {"quantifications": {"test": frame}, "errors": []}, {"source": "input.csv"})
    provenance, results = load_result_export(path)
    assert provenance["source"] == "input.csv"
    pd.testing.assert_frame_equal(results["quantifications"]["test"], frame)


@pytest.mark.parametrize("unit", ["difference_s", "difference_ms"])
def test_sensor_context_preserves_elapsed_time_when_missing_rows_were_excluded(unit):
    scale = 1000 if unit.endswith("ms") else 1
    frame = pd.DataFrame({"time": np.array([.1, .1, .3, .1]) * scale,
        "gyroscope_x": [1., np.nan, 1., 1.], "gyroscope_y": 1., "gyroscope_z": 1.})
    aligned = source_timeline(frame, {"time_input_unit": unit, "pipelines": ["tremor"], "drop_missing_samples": True})
    assert aligned == pytest.approx([0., .1, .4, .5])


def test_sensor_context_absolute_origin_uses_first_retained_sample():
    frame = pd.DataFrame({"time": [1000., 1001., 1002.], "gyroscope_x": [np.nan, 1., 1.],
                          "gyroscope_y": 1., "gyroscope_z": 1.})
    settings = {"time_input_unit": "absolute_s", "pipelines": ["tremor"], "drop_missing_samples": True}
    assert source_timeline(frame, settings).tolist() == [-1., 0., 1.]


def test_run_warning_and_error_counts_match_details_without_duplicate_pipeline_failures(window, monkeypatch):
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0., 1.]})))

    def partial(frame, logger, **settings):
        logger.warning("Some windows excluded")
        logger.warning("tremor pipeline returned error: No tremor windows")
        logger.error("Modules pulse_rate failed: No pulse signal")
        logger.warning("ParaDigMa analysis completed with 2 error(s)")
        return {"quantifications": {"gait": output()}, "errors": [
            {"pipeline": "tremor", "stage": "pipeline_execution", "error": "No tremor windows"},
            {"pipelines": ["pulse_rate"], "stage": "desktop_execution", "error": "ValueError: No pulse signal"}]}

    monkeypatch.setattr(desktop, "analyze", partial)
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
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0., 1.]})))
    monkeypatch.setattr(desktop, "analyze", lambda *args, **kwargs: {"quantifications": {"tremor": pd.DataFrame()}, "errors": []})
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
    record["warnings"] = ["Quality warning", "ParaDigMa analysis completed with 1 error(s)", "tremor pipeline returned error: Failed aggregation",
                          json.dumps({"pipeline": "tremor", "stage": "pipeline_execution", "error": "Failed aggregation"})]
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
    from paradigma_desktop.history import merge_errors
    errors = [{"pipeline": "tremor", "stage": "pipeline_execution", "file": section, "error": "No windows"}
              for section in ("section_1", "section_2")]
    messages = merge_errors(["tremor pipeline returned error: No windows"], errors)
    assert messages == ["tremor · pipeline_execution · section_1: No windows",
                        "tremor · pipeline_execution · section_2: No windows"]
