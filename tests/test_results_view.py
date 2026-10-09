"""Overview provenance, estimated gait timing and shared scientific selections."""

from conftest import bar_values, bar_starts, bar_centers
import os
from copy import deepcopy
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from paradigma_desktop.time_axis import RecordingTimeFormatter
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from paradigma_desktop.app import MainWindow
from paradigma_desktop.core import export_results
from paradigma_desktop.history import load_result_export
from paradigma_desktop.results_view import (
    aggregation_tables,
    analysis_alignment,
    clock_times,
    detail_tables,
    detail_timing,
    normalise_clock,
    recording_clock,
    segment_summary,
    time_bound,
)


@pytest.mark.parametrize("missing", ["green", "gyroscope_x"])
def test_independent_module_origins_align_to_source_clock_and_survive_reopening(
    window, tmp_path, missing
):
    window.timing_toggle.setChecked(True)
    start = pd.Timestamp("2026-10-07T10:00:00Z")
    raw = pd.DataFrame(
        {
            "time": start.timestamp() + np.arange(10),
            "green": np.ones(10),
            **{
                f"{sensor}_{axis}": np.ones(10)
                for sensor in ("accelerometer", "gyroscope")
                for axis in "xyz"
            },
        }
    )
    raw.loc[:1, missing] = np.nan
    settings = {
        "pipelines": ["tremor", "pulse_rate"],
        "time_input_unit": "absolute_s",
        "drop_missing_samples": True,
    }
    output = {
        "quantifications": {
            "tremor": pd.DataFrame(
                {"time": [0.0, 1.0, 2.0, 3.0], "tremor_power": [1.0, 2.0, 3.0, 4.0]}
            ),
            "pulse_rate": pd.DataFrame(
                {"time": [0.0, 1.0, 2.0, 3.0], "pulse_rate": [60.0, 61.0, 62.0, 63.0]}
            ),
        },
        "aggregations": {},
        "classifications": {},
        "errors": [],
        "metadata": {"desktop_preparation": {"analysis_groups": [["tremor"], ["pulse_rate"]]}},
    }
    common, timelines, offsets = analysis_alignment(raw, settings, output)
    early = "tremor" if missing == "green" else "pulse_rate"
    late = "pulse_rate" if missing == "green" else "tremor"
    np.testing.assert_array_equal(common, np.arange(10) - 2)
    assert offsets == {early: -2.0, late: 0.0}
    window.loaded(("sensor.csv", raw))
    window.provenance = {"source": "sensor.csv", "settings": settings}
    window.analyzed(output)
    assert pd.Timestamp(window.display_clock["origin"]) == start + pd.Timedelta(seconds=2)
    window.dataset.setCurrentText(f"quantifications/{early}")
    np.testing.assert_array_equal(window.display_frame["Analysis time (s)"], [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_array_equal(window.display_frame["Timeline time (s)"], [-2.0, -1.0, 0.0, 1.0])
    assert window.display_frame["Recording date/time"].iloc[0] == start
    for axes in window.figure.axes:
        module = axes._paradigma_dataset.split("/")[1]
        expected_start = start if module == early else start + pd.Timedelta(seconds=2)
        assert bar_starts(axes)[0] == pytest.approx(dates.date2num(expected_start.to_pydatetime()))
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
    return {
        "aggregations": {
            "gait": {"unfiltered": {"all": {"median_range_of_motion": 25.0}}},
            "tremor": {"perc_windows_tremor": 42.0},
        },
        "metadata": {
            "gait": {
                "unfiltered": {
                    "per_segment": {
                        1: {"start_s": 0.0, "end_s": 4.0, "duration_s": 4.0},
                        2: {"start_s": 10.0, "end_s": 14.0, "duration_s": 4.0},
                    }
                }
            },
            "tremor": {"nr_windows_total": 4, "nr_windows_rest": 2},
        },
        "classifications": {
            "tremor": pd.DataFrame(
                {"time": [0.0, 4.0, 8.0, 12.0], "pred_tremor_proba": [0.1, 0.8, 0.4, 0.9]}
            )
        },
        "quantifications": {
            "gait": {
                "unfiltered": pd.DataFrame(
                    {"gait_segment_nr": [1, 1, 2, 2], "range_of_motion": [10.0, 20.0, 30.0, 40.0]}
                )
            },
            "tremor": pd.DataFrame(
                {"time": [0.0, 4.0, 8.0, 12.0], "tremor_power": [1.0, 2.0, 3.0, 4.0]}
            ),
        },
        "errors": [],
    }


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
        raw["time_dt"] = pd.Timestamp("2026-10-07T23:59:55+02:00") + pd.to_timedelta(
            raw.time, unit="s"
        )
    window.loaded(("sensor.csv", raw))
    window.provenance = {"source": "sensor.csv", "settings": {"skip_preparation": True}}
    window.analyzed(results)
    return raw


def test_overview_only_contains_official_aggregates_metadata_and_segment_summaries(window, results):
    original = deepcopy(results)
    setup(window, results)
    assert window.result_tabs.currentIndex() == 0
    assert window.detail_controls.isHidden() and not window.export_button.isHidden()
    assert window.overview_gait_charts["median_range_of_motion"]["values"].tolist() == [25.0]
    assert (
        window.overview_values[("tremor", "Aggregates", ("perc_windows_tremor",))].text() == "42.00"
    )
    assert (
        window.overview_values[("tremor", "Metadata", ("percentage_arm_at_rest",))].text()
        == "50.00"
    )
    assert ("tremor", "Metadata", ("nr_windows_total",)) not in window.overview_values
    assert not any("per_segment" in path for module, group, path in window.overview_values)
    np.testing.assert_array_equal(
        window.overview_gait_charts["segment_count"]["values"], [np.nan, np.nan, 2, 0]
    )
    assert not any(
        "gait segments" in group.lower() for module, group, path in window.overview_values
    )
    assert all(key.startswith(("classifications/", "quantifications/")) for key in window.tables)
    assert set(window.tables) == set(detail_tables(results))
    window.result_tabs.setCurrentIndex(1)
    assert window.detail_controls.isHidden()
    window.figure.axes[0].set_xlim(10.0, 14.0)
    assert window.overview_gait_charts["median_range_of_motion"]["values"].tolist() == [25.0]
    for module, table in results["quantifications"].items():
        if isinstance(table, pd.DataFrame):
            pd.testing.assert_frame_equal(table, original["quantifications"][module])
        else:
            pd.testing.assert_frame_equal(
                table["unfiltered"], original["quantifications"][module]["unfiltered"]
            )


def test_tremor_overview_shows_only_requested_measures_with_two_decimals_without_changing_outputs(
    window,
):
    results = {
        "aggregations": {
            "tremor": {
                "perc_windows_tremor": 42.123456,
                "median_tremor_power": 1.234567,
                "modal_tremor_power": 2.0,
                "90p_tremor_power": np.nan,
                "custom_count": 123,
            }
        },
        "metadata": {"tremor": {"nr_windows_total": 30, "nr_windows_rest": 7, "nr_valid_days": 2}},
    }
    original = deepcopy(results)
    window.analyzed(results)
    texts = [
        widget.text() for widget in window.overview_module_cards["tremor"].findChildren(QLabel)
    ]
    assert "Aggregates" not in texts and "Metadata" not in texts
    assert {
        "Percentage tremor during rest (%)",
        "Median tremor power",
        "Modal tremor power",
        "90th percentile tremor power",
        "Percentage arm at rest (%)",
    }.issubset(texts)
    assert set(window.overview_values) == {
        ("tremor", "Aggregates", (key,))
        for key in (
            "perc_windows_tremor",
            "median_tremor_power",
            "modal_tremor_power",
            "90p_tremor_power",
        )
    } | {("tremor", "Metadata", ("percentage_arm_at_rest",))}
    assert {widget.text() for widget in window.overview_values.values()} == {
        "42.12",
        "1.23",
        "2.00",
        "—",
        "23.33",
    }
    for key, value in original["aggregations"]["tremor"].items():
        if np.isfinite(value):
            assert results["aggregations"]["tremor"][key] == value
        else:
            assert np.isnan(results["aggregations"]["tremor"][key])
    assert results["metadata"] == original["metadata"]
    assert (
        float(window.overview_values["tremor", "Aggregates", ("median_tremor_power",)].toolTip())
        == 1.234567
    )
    assert "percentage_arm_at_rest" not in results["metadata"]["tremor"]


@pytest.mark.parametrize(
    "metadata, quantification, expected",
    [
        ({"nr_windows_rest": 2, "nr_windows_total": 5}, None, 40.0),
        ({"nr_windows_rest": 0, "nr_windows_total": 0}, None, None),
        ({"nr_windows_rest": 3, "nr_windows_total": 2}, None, None),
        ({"nr_windows_rest": np.nan, "nr_windows_total": 5}, None, None),
        ({}, pd.DataFrame({"pred_arm_at_rest": [0.0, 1.0, 1.0, np.nan]}), 50.0),
    ],
)
def test_arm_at_rest_overview_uses_official_counts_or_original_quantification_and_unknown_stays_unknown(
    metadata, quantification, expected
):
    from paradigma_desktop.results_view import tremor_overview_entries

    results = {"metadata": {"tremor": metadata}, "quantifications": {"tremor": quantification}}
    entry = tremor_overview_entries(results)[-1]
    assert entry[3] == expected
    assert "percentage_arm_at_rest" not in metadata


def test_module_tabs_select_original_outputs_and_export_full_run_aggregates(
    window, results, tmp_path, monkeypatch
):
    original = deepcopy(results)
    setup(window, results)
    window.show()
    window.result_tabs.setCurrentIndex(2)
    assert [window.table_module_tabs.tabText(i) for i in range(3)] == [
        "Gait",
        "Tremor",
        "Pulse rate",
    ]
    assert not window.table_module_tabs.isTabEnabled(2)
    assert not window.timing_toggle.isChecked()
    assert window.table_module_tabs.currentIndex() == 0
    pd.testing.assert_frame_equal(
        window.result_table.model().frame, results["quantifications"]["gait"]["unfiltered"]
    )
    window.table_module_tabs.setCurrentIndex(1)
    names = [window.table_dataset.itemData(i) for i in range(window.table_dataset.count())]
    assert names == ["classifications/tremor", "quantifications/tremor", "aggregations/tremor"]
    assert [window.table_dataset.itemText(i) for i in range(3)] == [
        "Classification",
        "Quantification",
        "Aggregation",
    ]
    window.table_dataset.setCurrentIndex(window.table_dataset.findData("classifications/tremor"))
    pd.testing.assert_frame_equal(
        window.result_table.model().frame, results["classifications"]["tremor"]
    )
    pd.testing.assert_frame_equal(
        window.result_table.model().frame, results["classifications"]["tremor"]
    )
    window.table_dataset.setCurrentIndex(window.table_dataset.findData("aggregations/tremor"))
    assert window.table_stack.currentWidget() is window.aggregation_table
    expected = pd.DataFrame(
        {"measure": ["perc_windows_tremor"], "value": pd.Series([42.0], dtype=object)}
    )
    pd.testing.assert_frame_equal(window.aggregation_table.model().frame, expected)
    assert window.context_controls.isHidden() and window.timing_toggle.isHidden()
    assert window.export_button.isEnabled() and window.export_button.isVisible()
    path = tmp_path / "aggregates.csv"
    from paradigma_desktop import app as desktop

    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.export_csv()
    pd.testing.assert_frame_equal(pd.read_csv(path), expected.astype({"value": float}))
    window.table_module_tabs.setCurrentIndex(0)
    assert window.table_dataset.currentData() == "quantifications/gait/unfiltered"
    pd.testing.assert_frame_equal(
        window.result_table.model().frame, results["quantifications"]["gait"]["unfiltered"]
    )
    window.table_module_tabs.setCurrentIndex(1)
    assert window.table_dataset.currentData() == "aggregations/tremor"
    pd.testing.assert_frame_equal(window.aggregation_table.model().frame, expected)
    window.result_tabs.setCurrentIndex(1)
    gait_axes = next(
        ax
        for ax in window.figure.axes
        if ax._paradigma_dataset == "quantifications/gait/unfiltered"
    )
    anchor = dates.date2num(clock_times([11.0], window.display_clock))[0]
    window.graph_clicked(SimpleNamespace(inaxes=gait_axes, xdata=anchor))
    assert window.table_module_tabs.currentIndex() == 0
    assert window.table_dataset.currentData() == "quantifications/gait/unfiltered"
    for category in ("classifications", "quantifications"):
        for name, frame in results[category].items():
            if isinstance(frame, pd.DataFrame):
                pd.testing.assert_frame_equal(frame, original[category][name])
    assert results["aggregations"] == original["aggregations"]


def test_module_tabs_support_aggregation_only_modules(window):
    classification = pd.DataFrame({"time": [0.0, 1.0], "pred_gait": [1, 0]})
    window.analyzed(
        {
            "classifications": {"gait": classification},
            "aggregations": {"pulse_rate": {"median_pulse_rate": 72.0}},
        }
    )
    window.result_tabs.setCurrentIndex(2)
    assert window.table_module_tabs.isTabEnabled(0)
    assert not window.table_module_tabs.isTabEnabled(1)
    assert window.table_module_tabs.isTabEnabled(2)
    window.table_module_tabs.setCurrentIndex(2)
    assert window.table_dataset.count() == 1
    assert window.table_dataset.currentText() == "Aggregation"
    assert window.table_dataset.currentData() == "aggregations/pulse_rate"
    assert window.aggregation_table.model().frame.value.tolist() == [72.0]
    assert window.selected_export_table()[0] == "aggregations/pulse_rate"
    assert not hasattr(window, "filters_toggle")
    window.table_module_tabs.setCurrentIndex(0)
    pd.testing.assert_frame_equal(window.result_table.model().frame, classification)


def test_optional_timing_columns_preserve_original_data_and_linked_selection(window, results):
    setup(window, results)
    window.result_table.setCurrentIndex(window.result_table.model().index(1, 0))
    assert window.context_button.isEnabled()
    window.timing_toggle.setChecked(True)
    frame = window.result_table.model().frame
    assert frame["Time basis"].eq("Estimated within gait segment").all()
    pd.testing.assert_frame_equal(
        frame[results["quantifications"]["gait"]["unfiltered"].columns],
        results["quantifications"]["gait"]["unfiltered"],
    )
    assert window.result_table.currentIndex().row() == 1 and window.context_button.isEnabled()
    window.timing_toggle.setChecked(False)
    pd.testing.assert_frame_equal(
        window.result_table.model().frame, results["quantifications"]["gait"]["unfiltered"]
    )
    assert window.result_table.currentIndex().row() == 1
    assert window.time_axis.selection_marker.get_visible()


def test_aggregate_tables_preserve_large_integer_precision_empty_branches_and_key_order():
    values = {"count": 2**60 + 1, "percent": 1.25, "missing": None, "not_finite": float("nan")}
    tables = aggregation_tables(
        {"aggregations": {"gait": {"unfiltered": {"all": values}, "filtered": {}}}}
    )
    frame = tables["aggregations/gait/unfiltered/all"]
    assert frame.measure.tolist() == list(values)
    assert isinstance(frame.value.iloc[0], int) and frame.value.iloc[0] == 2**60 + 1
    assert frame.value.iloc[2] is None and np.isnan(frame.value.iloc[3])
    assert tables["aggregations/gait/filtered"].empty


def test_multiple_modules_share_absolute_time_axes_and_preserve_full_tables_and_csv(
    window, results, tmp_path, monkeypatch
):
    window.timing_toggle.setChecked(True)
    setup(window, results)
    assert set(window.selected_result_series()) == {
        ("quantifications/gait/unfiltered", "range_of_motion"),
        ("quantifications/tremor", "tremor_power"),
    }
    axes = window.figure.axes
    assert len(axes) == 2 and axes[0].get_shared_x_axes().joined(*axes)
    assert all(isinstance(ax.xaxis.get_major_formatter(), RecordingTimeFormatter) for ax in axes)
    assert all("Recording time" in ax.get_xlabel() for ax in axes)
    np.testing.assert_allclose(
        bar_centers(axes[0]),
        dates.date2num(clock_times([1.0, 3.0, 11.0, 13.0], window.display_clock)),
    )
    np.testing.assert_array_equal(bar_values(axes[0]), [10.0, 20.0, 30.0, 40.0])
    low = dates.date2num(clock_times([5.0], window.display_clock))[0]
    axes[0].set_xlim(low, low + 8.0 / 86400)
    assert window.active_positions.tolist() == [0, 1, 2, 3]
    assert window._detail_selections["quantifications/tremor"][1].tolist() == [0, 1, 2, 3]
    np.testing.assert_array_equal(bar_values(window.figure.axes[0]), [10.0, 20.0, 30.0, 40.0])
    np.testing.assert_array_equal(bar_values(window.figure.axes[1]), [1.0, 2.0, 3.0, 4.0])
    path = tmp_path / "selection.csv"
    from paradigma_desktop import app as desktop

    monkeypatch.setattr(desktop.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.export_csv()
    exported = pd.read_csv(path)
    assert exported.range_of_motion.tolist() == [10.0, 20.0, 30.0, 40.0]
    assert exported["Analysis time (s)"].tolist() == [1.0, 3.0, 11.0, 13.0]
    assert exported["Time basis"].eq("Estimated within gait segment").all()


def test_classifications_can_plot_alongside_quantifications_and_click_selects_correct_table(
    window, results
):
    results["classifications"]["tremor"]["pred_tremor_checked"] = [0, 1, 1, 0]
    setup(window, results)
    key = ("classifications/tremor", "pred_tremor_checked")
    window._series_items[key].setCheckState(0, Qt.Checked)
    assert len(window.figure.axes) == 3
    ax = next(ax for ax in window.figure.axes if ax._paradigma_dataset == key[0])
    assert ax._paradigma_binary
    assert len(ax.collections[0].get_paths()) == 2
    np.testing.assert_array_equal(
        [bar.vertices[:, 0].min() for bar in ax.collections[0].get_paths()],
        dates.date2num(clock_times([4.0, 8.0], window.display_clock)),
    )
    click = dates.date2num(clock_times([8.0], window.display_clock))[0]
    window.graph_clicked(SimpleNamespace(inaxes=ax, xdata=click))
    assert window.dataset.currentText() == key[0]
    assert (
        window.active_frame.iloc[window.result_table.currentIndex().row()].pred_tremor_proba == 0.4
    )
    assert len(window.selected_result_series()) == 3
    assert window.context_button.isEnabled()


def test_gait_estimates_remain_stable_for_row_subsets_and_unknown_intervals_are_not_invented(
    results,
):
    frame = results["quantifications"]["gait"]["unfiltered"]
    original = frame.copy()
    timing = detail_timing(results, "quantifications/gait/unfiltered", frame)
    assert timing["Analysis time (s)"].tolist() == [1.0, 3.0, 11.0, 13.0]
    assert timing["Segment start (s)"].tolist() == [0.0, 0.0, 10.0, 10.0]
    assert timing["Segment end (s)"].tolist() == [4.0, 4.0, 14.0, 14.0]
    assert timing.iloc[[1, 3]]["Analysis time (s)"].tolist() == [3.0, 13.0]
    missing = detail_timing({}, "quantifications/gait/unfiltered", frame)
    assert missing["Analysis time (s)"].isna().all()
    pd.testing.assert_frame_equal(frame, original)


def test_relative_only_recordings_keep_elapsed_time_until_user_sets_clock_and_json_reopens_it(
    window, results, tmp_path
):
    setup(window, results, clock=False)
    assert window.display_clock is None
    assert "Elapsed" in window.figure.axes[0].get_xlabel()
    assert "Recording date/time" not in window.result_table.model().frame
    window.timing_toggle.setChecked(True)
    window.clock_input.setText("2026-10-07T12:00:00+02:00")
    window.origin_edited()
    window.provenance["settings"]["plot_time_origin"] = window.origin_setting()
    window.analyzed(results)
    assert window.display_clock["source"] == "User supplied"
    assert "Recording date/time" in window.result_table.model().frame
    path = tmp_path / "results.json"
    export_results(path, results, window.provenance)
    provenance, restored = load_result_export(path)
    window.result_source_frame = window.frame = None
    window.provenance = provenance
    window.analyzed(restored)
    assert window.display_clock["origin"] == "2026-10-07T12:00:00+02:00"
    assert window.result_table.model().frame["Recording date/time"].iloc[0] == pd.Timestamp(
        "2026-10-07T12:00:01+02:00"
    )
    pd.testing.assert_frame_equal(
        restored["quantifications"]["gait"]["unfiltered"],
        results["quantifications"]["gait"]["unfiltered"],
    )


def test_invalid_analyze_clock_does_not_change_existing_results(window, results):
    setup(window, results)
    original = window.active_frame.copy()
    provenance = deepcopy(window.provenance)
    window.clock_input.setText("invalid")
    window.origin_edited()
    with pytest.raises(ValueError):
        window.origin_setting()
    pd.testing.assert_frame_equal(window.active_frame, original)
    assert window.provenance == provenance


@pytest.mark.parametrize("unit", ["absolute_s", "absolute_ms"])
def test_absolute_clock_matches_preparation_after_excluding_first_sensor_sample(unit):
    seconds = np.array([1_700_000_000.0, 1_700_000_000.01, 1_700_000_000.02])
    frame = pd.DataFrame(
        {
            "time": seconds * (1000 if unit.endswith("ms") else 1),
            "gyroscope_x": [np.nan, 1.0, 2.0],
            "gyroscope_y": [0.0, 0.0, 0.0],
            "gyroscope_z": [0.0, 0.0, 0.0],
        }
    )
    clock = recording_clock(
        frame, {"pipelines": ["tremor"], "time_input_unit": unit, "drop_missing_samples": True}
    )
    assert pd.Timestamp(clock["origin"]).timestamp() == pytest.approx(seconds[1], abs=1e-6)
    assert clock["timezone"] == "UTC"


def test_named_timezone_survives_json_and_daylight_saving_transition():
    clock = normalise_clock({"origin": "2026-10-25T02:59:00+02:00", "timezone": "Europe/Amsterdam"})
    stamps = clock_times([0.0, 60.0, 120.0], clock)
    assert stamps[0].hour == 2 and stamps[0].minute == 59
    assert stamps[1].hour == 2 and stamps[1].minute == 0
    assert (
        stamps[0].utcoffset().total_seconds() == 7200
        and stamps[1].utcoffset().total_seconds() == 3600
    )
    assert time_bound("2026-10-25T02:00:00+01:00", clock) == 60
    with pytest.raises(ValueError, match="offset"):
        time_bound("2026-10-25T02:00:00", clock)


def test_segment_duration_summary_preserves_branch_counts_and_distribution():
    summary = segment_summary(
        {
            "unfiltered": {
                "per_segment": {
                    1: {"duration_s": 2.0},
                    2: {"start_s": 10.0, "end_s": 16.0},
                    3: {"duration_s": np.nan},
                }
            }
        }
    )["unfiltered"]
    assert summary == {
        "Segment count": 3,
        "Segments with valid duration": 2,
        "Total duration (s)": 8.0,
        "Median duration (s)": 4.0,
        "Duration IQR (s)": 2.0,
        "Duration range (s)": "2 – 6",
    }
