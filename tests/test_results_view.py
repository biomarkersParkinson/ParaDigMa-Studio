"""Overview provenance, estimated gait timing and shared scientific selections."""
import os
from copy import deepcopy
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_desktop.app import MainWindow
from paradigma_desktop.core import export_results
from paradigma_desktop.history import load_result_export
from paradigma_desktop.results_view import (
    analysis_alignment, clock_times, detail_tables, detail_timing, normalise_clock, recording_clock,
    segment_summary, time_bound,
)


@pytest.mark.parametrize("missing", ["green", "gyroscope_x"])
def test_independent_module_origins_align_to_source_clock_and_survive_reopening(window, tmp_path, missing):
    start = pd.Timestamp("2026-10-07T10:00:00Z")
    raw = pd.DataFrame({"time": start.timestamp() + np.arange(10), "green": np.ones(10),
                       **{f"{sensor}_{axis}": np.ones(10) for sensor in ("accelerometer", "gyroscope") for axis in "xyz"}})
    raw.loc[:1, missing] = np.nan
    settings = {"pipelines": ["tremor", "pulse_rate"], "time_input_unit": "absolute_s", "drop_missing_samples": True}
    output = {"quantifications": {"tremor": pd.DataFrame({"time": [0., 1., 2., 3.], "tremor_power": [1., 2., 3., 4.]}),
                                  "pulse_rate": pd.DataFrame({"time": [0., 1., 2., 3.], "pulse_rate": [60., 61., 62., 63.]})},
              "aggregations": {}, "classifications": {}, "errors": [],
              "metadata": {"desktop_preparation": {"analysis_groups": [["tremor"], ["pulse_rate"]]}}}
    common, timelines, offsets = analysis_alignment(raw, settings, output)
    early = "tremor" if missing == "green" else "pulse_rate"
    late = "pulse_rate" if missing == "green" else "tremor"
    np.testing.assert_array_equal(common, np.arange(10) - 2)
    assert offsets == {early: -2., late: 0.}
    window.loaded(("sensor.csv", raw))
    window.provenance = {"source": "sensor.csv", "settings": settings}
    window.analyzed(output)
    assert pd.Timestamp(window.display_clock["origin"]) == start + pd.Timedelta(seconds=2)
    window.dataset.setCurrentText(f"quantifications/{early}")
    np.testing.assert_array_equal(window.display_frame["Analysis time (s)"], [0., 1., 2., 3.])
    np.testing.assert_array_equal(window.display_frame["Timeline time (s)"], [-2., -1., 0., 1.])
    assert window.display_frame["Recording date/time"].iloc[0] == start
    for axes in window.figure.axes:
        module = axes._paradigma_dataset.split("/")[1]
        expected_start = start if module == early else start + pd.Timedelta(seconds=2)
        assert axes.lines[0].get_xdata()[0] == pytest.approx(dates.date2num(expected_start.to_pydatetime()))
    exported = tmp_path / "aligned.json"
    export_results(exported, output, window.provenance)
    provenance, saved = load_result_export(exported)
    window.frame = None
    window.provenance = provenance
    window.analyzed(saved)
    window.dataset.setCurrentText(f"quantifications/{early}")
    assert window.display_frame["Recording date/time"].iloc[0] == start
    assert window._display_offsets == offsets


@pytest.fixture
def results():
    return {"aggregations": {"gait": {"unfiltered": {"all": {"median_range_of_motion": 25.}}},
                             "tremor": {"tremor_time_percent": 42.}},
            "metadata": {"gait": {"unfiltered": {"per_segment": {
                1: {"start_s": 0., "end_s": 4., "duration_s": 4.},
                2: {"start_s": 10., "end_s": 14., "duration_s": 4.}}}},
                         "tremor": {"recorded_windows": 4}},
            "classifications": {"tremor": pd.DataFrame({"time": [0., 4., 8., 12.],
                                                         "pred_tremor_proba": [.1, .8, .4, .9]})},
            "quantifications": {"gait": {"unfiltered": pd.DataFrame({"gait_segment_nr": [1, 1, 2, 2],
                                                                       "range_of_motion": [10., 20., 30., 40.]})},
                                 "tremor": pd.DataFrame({"time": [0., 4., 8., 12.], "tremor_power": [1., 2., 3., 4.]})},
            "errors": []}


@pytest.fixture
def window(tmp_path):
    application = QApplication.instance() or QApplication([])
    widget = MainWindow(history_dir=tmp_path / "runs")
    yield widget
    widget.close()
    application.processEvents()


def setup(window, results, clock=True):
    raw = pd.DataFrame({"time": np.arange(150) / 10, "gyroscope_x": np.arange(150, dtype=float)})
    if clock:
        raw["time_dt"] = pd.Timestamp("2026-10-07T23:59:55+02:00") + pd.to_timedelta(raw.time, unit="s")
    window.loaded(("sensor.csv", raw))
    window.provenance = {"source": "sensor.csv", "settings": {"skip_preparation": True}}
    window.analyzed(results)
    return raw


def test_overview_only_contains_official_aggregates_metadata_and_segment_summaries(window, results):
    original = deepcopy(results)
    setup(window, results)
    assert window.result_tabs.currentIndex() == 0
    assert window.detail_controls.isHidden() and window.csv_button.isHidden()
    assert window.overview_values[("gait", "Aggregates", ("unfiltered", "all", "median_range_of_motion"))].text() == "25"
    assert window.overview_values[("tremor", "Aggregates", ("tremor_time_percent",))].text() == "42"
    assert window.overview_values[("tremor", "Metadata", ("recorded_windows",))].text() == "4"
    assert not any("per_segment" in path for module, group, path in window.overview_values)
    assert window.overview_values[("gait", "Unfiltered gait segments", ("Segment count",))].text() == "2"
    assert window.overview_values[("gait", "Unfiltered gait segments", ("Median duration (s)",))].text() == "4"
    assert all(key.startswith(("classifications/", "quantifications/")) for key in window.tables)
    assert set(window.tables) == set(detail_tables(results))
    window.result_tabs.setCurrentIndex(1)
    assert not window.detail_controls.isHidden()
    window.time_from.setText("10")
    window.apply_filters()
    assert window.overview_values[("gait", "Aggregates", ("unfiltered", "all", "median_range_of_motion"))].text() == "25"
    for module, table in results["quantifications"].items():
        if isinstance(table, pd.DataFrame):
            pd.testing.assert_frame_equal(table, original["quantifications"][module])
        else:
            pd.testing.assert_frame_equal(table["unfiltered"], original["quantifications"][module]["unfiltered"])


def test_multiple_modules_share_absolute_time_axes_filters_tables_and_csv(window, results, tmp_path, monkeypatch):
    setup(window, results)
    assert set(window.selected_result_series()) == {("quantifications/gait/unfiltered", "range_of_motion"),
                                                   ("quantifications/tremor", "tremor_power")}
    axes = window.figure.axes
    assert len(axes) == 2 and axes[0].get_shared_x_axes().joined(*axes)
    assert all(isinstance(ax.xaxis.get_major_formatter(), dates.ConciseDateFormatter) for ax in axes)
    assert all("Recording date/time" in ax.get_xlabel() for ax in axes)
    np.testing.assert_allclose(axes[0].lines[0].get_xdata(), dates.date2num(clock_times([1., 3., 11., 13.], window.display_clock)))
    np.testing.assert_array_equal(axes[0].lines[0].get_ydata(), [10., 20., 30., 40.])
    window.time_from.setText("2026-10-08T00:00:00+02:00")
    window.time_to.setText("2026-10-08T00:00:08+02:00")
    window.apply_filters()
    assert window.active_positions.tolist() == [2, 3]
    assert window.result_table.model().frame["Analysis time (s)"].tolist() == [11., 13.]
    assert window.result_table.model().frame["Time basis"].eq("Estimated within gait segment").all()
    assert window._detail_selections["quantifications/tremor"][1].tolist() == [2, 3]
    np.testing.assert_array_equal(window.figure.axes[0].lines[0].get_ydata(), [30., 40.])
    np.testing.assert_array_equal(window.figure.axes[1].lines[0].get_ydata(), [3., 4.])
    assert window.result_table.model().frame["Recording date/time"].iloc[0].day == 8
    path = tmp_path / "selection.csv"
    from paradigma_desktop import app as desktop
    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.export_csv()
    exported = pd.read_csv(path)
    assert exported.range_of_motion.tolist() == [30., 40.]
    assert exported["Analysis time (s)"].tolist() == [11., 13.]
    assert exported["Time basis"].eq("Estimated within gait segment").all()


def test_classifications_can_plot_alongside_quantifications_and_click_selects_correct_table(window, results):
    setup(window, results)
    key = ("classifications/tremor", "pred_tremor_proba")
    window._series_items[key].setCheckState(0, Qt.Checked)
    assert len(window.figure.axes) == 3
    ax = next(ax for ax in window.figure.axes if ax._paradigma_dataset == key[0])
    np.testing.assert_array_equal(ax.lines[0].get_ydata(), [.1, .8, .4, .9])
    click = dates.date2num(clock_times([8.], window.display_clock))[0]
    window.graph_clicked(SimpleNamespace(inaxes=ax, xdata=click))
    assert window.dataset.currentText() == key[0]
    assert window.active_frame.iloc[window.result_table.currentIndex().row()].pred_tremor_proba == .4
    assert len(window.selected_result_series()) == 3
    assert window.context_button.isEnabled()


def test_gait_estimates_are_stable_under_filtering_and_unknown_intervals_are_not_invented(results):
    frame = results["quantifications"]["gait"]["unfiltered"]
    original = frame.copy()
    timing = detail_timing(results, "quantifications/gait/unfiltered", frame)
    assert timing["Analysis time (s)"].tolist() == [1., 3., 11., 13.]
    assert timing["Segment start (s)"].tolist() == [0., 0., 10., 10.]
    assert timing["Segment end (s)"].tolist() == [4., 4., 14., 14.]
    assert timing.iloc[[1, 3]]["Analysis time (s)"].tolist() == [3., 13.]
    missing = detail_timing({}, "quantifications/gait/unfiltered", frame)
    assert missing["Analysis time (s)"].isna().all()
    pd.testing.assert_frame_equal(frame, original)


def test_relative_only_recordings_keep_elapsed_time_until_user_sets_clock_and_json_reopens_it(window, results, tmp_path):
    setup(window, results, clock=False)
    assert window.display_clock is None
    assert "Elapsed" in window.figure.axes[0].get_xlabel()
    assert "Recording date/time" not in window.result_table.model().frame
    window.clock_input.setText("2026-10-07T12:00:00+02:00")
    window.apply_filters()
    assert window.display_clock["source"] == "User supplied"
    assert "Recording date/time" in window.result_table.model().frame
    path = tmp_path / "results.json"
    export_results(path, results, window.provenance)
    provenance, restored = load_result_export(path)
    window.result_source_frame = window.frame = None
    window.provenance = provenance
    window.analyzed(restored)
    assert window.display_clock["origin"] == "2026-10-07T12:00:00+02:00"
    assert window.result_table.model().frame["Recording date/time"].iloc[0] == pd.Timestamp("2026-10-07T12:00:01+02:00")
    pd.testing.assert_frame_equal(restored["quantifications"]["gait"]["unfiltered"], results["quantifications"]["gait"]["unfiltered"])


def test_invalid_clock_and_time_filters_keep_previous_scientific_selection(window, results):
    setup(window, results)
    original = window.active_frame.copy()
    provenance = deepcopy(window.provenance)
    for origin, lower, upper in (("today", "", ""), ("invalid", "", ""),
                                 (window.display_clock["origin"], "20", "10"),
                                 (window.display_clock["origin"], "nan", "")):
        window.clock_input.setText(origin)
        window.time_from.setText(lower)
        window.time_to.setText(upper)
        window.apply_filters()
        assert window.filter_status.text()
        pd.testing.assert_frame_equal(window.active_frame, original)
        assert window.provenance == provenance


@pytest.mark.parametrize("unit", ["absolute_s", "absolute_ms"])
def test_absolute_clock_matches_preparation_after_excluding_first_sensor_sample(unit):
    seconds = np.array([1_700_000_000., 1_700_000_000.01, 1_700_000_000.02])
    frame = pd.DataFrame({"time": seconds * (1000 if unit.endswith("ms") else 1),
                          "gyroscope_x": [np.nan, 1., 2.], "gyroscope_y": [0., 0., 0.], "gyroscope_z": [0., 0., 0.]})
    clock = recording_clock(frame, {"pipelines": ["tremor"], "time_input_unit": unit, "drop_missing_samples": True})
    assert pd.Timestamp(clock["origin"]).timestamp() == pytest.approx(seconds[1], abs=1e-6)
    assert clock["timezone"] == "UTC"


def test_named_timezone_survives_json_and_daylight_saving_transition():
    clock = normalise_clock({"origin": "2026-10-25T02:59:00+02:00", "timezone": "Europe/Amsterdam"})
    stamps = clock_times([0., 60., 120.], clock)
    assert stamps[0].hour == 2 and stamps[0].minute == 59
    assert stamps[1].hour == 2 and stamps[1].minute == 0
    assert stamps[0].utcoffset().total_seconds() == 7200 and stamps[1].utcoffset().total_seconds() == 3600
    assert time_bound("2026-10-25T02:00:00+01:00", clock) == 60
    with pytest.raises(ValueError, match="offset"):
        time_bound("2026-10-25T02:00:00", clock)


def test_segment_duration_summary_preserves_branch_counts_and_distribution():
    summary = segment_summary({"unfiltered": {"per_segment": {
        1: {"duration_s": 2.}, 2: {"start_s": 10., "end_s": 16.}, 3: {"duration_s": np.nan}}}})["unfiltered"]
    assert summary == {"Segment count": 3, "Segments with valid duration": 2,
                       "Total duration (s)": 8., "Median duration (s)": 4., "Duration IQR (s)": 2.,
                       "Duration range (s)": "2 – 6"}
