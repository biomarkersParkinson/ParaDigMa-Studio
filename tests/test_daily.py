"""Daily graphs require metric-specific coverage and preserve official outputs."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from conftest import select_plot_metric
from PySide6.QtCore import Qt

from paradigma_studio.daily import (
    DAY_SECONDS,
    MIN_DAY_DATA_SECONDS,
    daily_availability_summary,
    daily_summary,
    day_coverage,
    day_edges,
    gait_daily_summaries,
)
from paradigma_studio.results_view import clock_times


@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("duration", [863.99, 864.0, 864.01])
def test_daily_threshold_uses_valid_duration_and_includes_exactly_one_percent(binary, duration):
    times = np.array([0.0, duration / 2])
    values = [0, 1] if binary else [10, 20]
    frame = daily_summary(times, values, times, [duration / 2, duration], None, binary=binary)
    assert frame.data_s.iloc[0] == pytest.approx(duration)
    if duration < 864:
        assert np.isnan(frame.value.iloc[0])
    else:
        assert frame.value.iloc[0] == (50 if binary else 15)
    assert MIN_DAY_DATA_SECONDS == 864


@pytest.mark.parametrize("binary", [False, True])
def test_daily_missing_values_and_overlaps_cannot_inflate_metric_coverage(binary):
    frame = daily_summary(
        [0, 0, 500], [1, 1, np.nan], [0, 0, 500], [500, 500, 10000], None, binary=binary
    )
    assert frame.data_s.tolist() == [500]
    assert frame.value.isna().all()
    assert frame.n_observations.tolist() == [2]


def test_daily_binary_absence_is_valid_data_and_invalid_states_are_not():
    zeros = daily_summary([0, 500], [0, 0], [0, 500], [500, 1000], None, binary=True)
    assert zeros.value.tolist() == [0]
    invalid = daily_summary([0, 500], [0, 2], [0, 500], [500, 1000], None, binary=True)
    assert invalid.data_s.tolist() == [500]
    assert invalid.value.isna().all()


def test_daily_continuous_uses_median_and_keeps_missing_days_and_gaps_blank():
    times = [0, 300, 600, DAY_SECONDS + 1, 2 * DAY_SECONDS]
    ends = [300, 600, 900, DAY_SECONDS + 2, 2 * DAY_SECONDS + 1000]
    values = [1, 99, 10, np.nan, 5]
    original = list(values)
    frame = daily_summary(times, values, times, ends, None)
    np.testing.assert_array_equal(frame.value, [10, np.nan, 5])
    np.testing.assert_array_equal(frame.data_s, [900, 0, 1000])
    assert values == original


def test_midnight_splits_available_intervals_and_partial_days_keep_the_full_threshold():
    starts = [DAY_SECONDS - 500, DAY_SECONDS]
    frame = daily_summary(starts, [10, 20], starts, [DAY_SECONDS, DAY_SECONDS + 864], None)
    np.testing.assert_array_equal(frame.data_s, [500, 864])
    np.testing.assert_array_equal(frame.value, [np.nan, 20])
    np.testing.assert_array_equal(
        day_coverage([0, DAY_SECONDS, 2 * DAY_SECONDS], [DAY_SECONDS - 300], [DAY_SECONDS + 400]),
        [300, 400],
    )
    np.testing.assert_array_equal(
        day_coverage(
            np.arange(5) * DAY_SECONDS, [0, DAY_SECONDS], [4 * DAY_SECONDS, 3 * DAY_SECONDS]
        ),
        np.full(4, DAY_SECONDS),
    )


@pytest.mark.parametrize(
    "timezone,expected_edges",
    [
        ("Europe/Amsterdam", [-43_635, 42_765, 129_165, 215_565]),
        ("Asia/Kathmandu", [-57_135, 29_265, 115_665, 202_065]),
        (None, [-36_435, 49_965, 136_365, 222_765]),
    ],
)
def test_day_edges_cover_the_full_recording_at_each_local_midnight(timezone, expected_edges):
    clock = {"origin": "2026-10-13T10:07:15Z", "timezone": timezone}
    edges = day_edges(clock, [0], [2 * DAY_SECONDS])
    np.testing.assert_array_equal(edges, expected_edges)
    stamps = clock_times(edges, clock)
    assert stamps.strftime("%Y-%m-%d %H:%M:%S").tolist() == [
        "2026-10-13 00:00:00",
        "2026-10-14 00:00:00",
        "2026-10-15 00:00:00",
        "2026-10-16 00:00:00",
    ]


@pytest.mark.parametrize(
    "origin, hours", [("2026-03-29T00:00:00+01:00", 23), ("2026-10-25T00:00:00+02:00", 25)]
)
def test_calendar_days_handle_dst_and_keep_864_second_threshold(origin, hours):
    clock = {"origin": origin, "timezone": "Europe/Amsterdam"}
    edges = day_edges(clock, [0], [hours * 3600])
    np.testing.assert_array_equal(edges, [0, hours * 3600])
    assert clock_times(edges, clock).strftime("%H:%M").tolist() == ["00:00", "00:00"]
    assert daily_availability_summary([0], [hours * 3600], clock).value.tolist() == [100]
    assert daily_summary([0], [42], [0], [864], clock).value.tolist() == [42]


def test_daily_gait_percentages_use_one_observed_denominator_and_allow_sparse_presence():
    intervals = {
        "domain": np.array([[0, 3600]]),
        "observed": np.array([[0, 1000]]),
        "gait": np.array([[100, 200]]),
        "filtered": np.array([[100, 150]]),
    }
    summaries = gait_daily_summaries(intervals, None)
    assert summaries["gait"].value.tolist() == [10]
    assert summaries["filtered"].value.tolist() == [5]
    assert summaries["filtered"].data_s.tolist() == [1000]


def test_daily_empty_outputs_and_unknown_cadence_do_not_invent_available_data():
    assert daily_summary([], [], [], [], None).empty
    assert daily_availability_summary([], [], None).empty
    frame = daily_summary([0, DAY_SECONDS], [1, 2], [0, DAY_SECONDS], [0, DAY_SECONDS], None)
    assert frame.data_s.eq(0).all() and frame.value.isna().all()


def _series_axis(window, name, metric):
    return next(
        ax
        for ax in window.figure.axes
        if ax._paradigma_dataset == name and ax._paradigma_metric == metric
    )


def test_day_switches_all_modules_uses_metric_data_and_keeps_caches_and_tables(window):
    times = np.arange(0.0, 1800.0, 4.0)
    tremor = pd.DataFrame({"time": times, "pred_tremor_checked": 0, "pred_arm_at_rest": 1})
    power = pd.DataFrame({"time": times, "tremor_power": np.where(times < 864, 3.0, np.nan)})
    pulse = pd.DataFrame({"time": np.arange(0.0, 1000.0), "pulse_rate": 60.0})
    output = {
        "classifications": {"tremor": tremor},
        "quantifications": {"tremor": power, "pulse_rate": pulse},
        "metadata": {"desktop_availability": {"tremor": {"df_1": {"intervals": [[0.0, 1800.0]]}}}},
    }
    original = deepcopy(output)
    window.analyzed(output)
    window.result_tabs.setCurrentIndex(1)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_graph_view.setCurrentIndex(1)
    thirty = _series_axis(window, "quantifications/tremor", "tremor_power")._paradigma_epoch_data
    assert thirty.value.isna().all()  # No checked tremor presence under the existing 30-min rule.
    window.result_graph_view.setCurrentIndex(2)
    axes = tuple(window.figure.axes)
    assert all(ax._paradigma_epoch and ax._paradigma_bars for ax in axes)
    assert len({ax.get_xlim() for ax in axes}) == 1
    power_axis = _series_axis(window, "quantifications/tremor", "tremor_power")
    daily = power_axis._paradigma_epoch_data
    assert daily.data_s.tolist() == [864]
    np.testing.assert_allclose(daily.value, [np.log10(4)])
    assert power_axis.get_ylabel() == "Median log₁₀(power + 1)"
    assert _series_axis(
        window, "classifications/tremor", "pred_tremor_checked"
    )._paradigma_epoch_data.value.tolist() == [0]
    assert _series_axis(
        window, "quantifications/pulse_rate", "pulse_rate"
    )._paradigma_epoch_data.value.tolist() == [60]
    coverage = next(ax for ax in axes if ax._paradigma_dataset.startswith("preparation/"))
    np.testing.assert_allclose(coverage._paradigma_epoch_data.value, [1800 / DAY_SECONDS * 100])
    window.graph_clicked(SimpleNamespace(inaxes=power_axis, xdata=432.0))
    assert window.result_table.currentIndex().row() >= 0
    window.result_graph_view.setCurrentIndex(0)
    assert not any(ax._paradigma_epoch for ax in window.figure.axes)
    window.result_graph_view.setCurrentIndex(1)
    assert (
        _series_axis(window, "quantifications/tremor", "tremor_power")._paradigma_epoch_data
        is thirty
    )
    window.result_graph_view.setCurrentIndex(2)
    assert (
        _series_axis(window, "quantifications/tremor", "tremor_power")._paradigma_epoch_data
        is daily
    )
    for stage in ("classifications", "quantifications"):
        for module in output[stage]:
            pd.testing.assert_frame_equal(output[stage][module], original[stage][module])
            pd.testing.assert_frame_equal(
                window._result_state.tables[f"{stage}/{module}"], original[stage][module]
            )
    window.analyzed({"quantifications": {"tremor": power.assign(tremor_power=np.nan)}})
    select_plot_metric(window, "quantifications/tremor", "tremor_power")
    assert (
        _series_axis(window, "quantifications/tremor", "tremor_power")
        ._paradigma_epoch_data.value.isna()
        .all()
    )


def test_day_gait_quantification_coverage_uses_valid_estimated_swing_intervals(window):
    gait = pd.DataFrame(
        {
            "gait_segment_nr": [1, 1, 1],
            "range_of_motion": [10.0, 20.0, 30.0],
            "peak_velocity": [100.0, np.nan, np.nan],
        }
    )
    output = {
        "quantifications": {"gait": {"filtered": gait, "unfiltered": gait.copy()}},
        "metadata": {
            "gait": {
                branch: {"per_segment": {1: {"start_s": 0.0, "end_s": 1800.0}}}
                for branch in ("filtered", "unfiltered")
            }
        },
    }
    window.analyzed(output)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_graph_view.setCurrentIndex(2)
    for branch in ("filtered", "unfiltered"):
        rom = _series_axis(window, f"quantifications/gait/{branch}", "range_of_motion")
        velocity = _series_axis(window, f"quantifications/gait/{branch}", "peak_velocity")
        assert rom._paradigma_epoch_data.value.tolist() == [20]
        assert rom._paradigma_epoch_data.data_s.tolist() == [1800]
        assert velocity._paradigma_epoch_data.data_s.tolist() == [600]
        assert velocity._paradigma_epoch_data.value.isna().all()


def test_day_gait_graphs_share_denominator_and_count_known_absence_as_available(window):
    times = np.arange(0.0, 1800.0, 0.75)
    detection = pd.DataFrame({"time": times, "pred_gait_proba": (times < 150).astype(float)})
    arm = pd.DataFrame(
        {"time": times, "pred_no_other_arm_activity_proba": (times < 75).astype(float)}
    )
    window.analyzed({"classifications": {"gait": {"detection": detection, "arm_activity": arm}}})
    select_plot_metric(window, "classifications/gait/detection", "pred_gait_window")
    select_plot_metric(
        window, "classifications/gait/arm_activity", "pred_no_other_arm_activity_window"
    )
    window.result_graph_view.setCurrentIndex(2)
    gait = _series_axis(
        window, "classifications/gait/detection", "pred_gait_window"
    )._paradigma_epoch_data
    filtered = _series_axis(
        window, "classifications/gait/arm_activity", "pred_no_other_arm_activity_window"
    )._paradigma_epoch_data
    np.testing.assert_allclose(gait.value, [150 / 1800 * 100])
    np.testing.assert_allclose(filtered.value, [75 / 1800 * 100])
    np.testing.assert_array_equal(gait.data_s, filtered.data_s)
    assert gait.data_s.tolist() == [1800]


def test_day_graph_calendar_boundaries_and_zoom_use_saved_display_clock(window):
    times = np.arange(0.0, 1800.0, 4.0)
    frame = pd.DataFrame({"time": times, "pred_tremor_checked": 0})
    window.analyzed({"classifications": {"tremor": frame}})
    clock = {"origin": "2026-10-13T23:50:00+02:00", "timezone": "Europe/Amsterdam"}
    window._result_state.display_clock = clock
    select_plot_metric(window, "classifications/tremor", "pred_tremor_checked")
    window.result_graph_view.setCurrentIndex(2)
    axes = _series_axis(window, "classifications/tremor", "pred_tremor_checked")
    daily = axes._paradigma_epoch_data
    np.testing.assert_array_equal(daily.data_s, [600, 1200])
    np.testing.assert_array_equal(daily.value, [np.nan, 0])
    assert clock_times(daily.start_s, clock).strftime("%Y-%m-%d %H:%M").tolist() == [
        "2026-10-13 00:00",
        "2026-10-14 00:00",
    ]
    limits = axes.get_xlim()
    custom = limits[0] + (limits[1] - limits[0]) * 0.2, limits[1] - (limits[1] - limits[0]) * 0.2
    axes.set_xlim(*custom)
    window.result_graph_view.setCurrentIndex(1)
    # Each view opens at its full extent, including when returning from a
    # shorter epoch range. Cached daily values remain unchanged.
    epoch_range = window.figure.axes[0].get_xlim()
    assert epoch_range == pytest.approx(window.result_time_scroll._full_limits)
    assert custom[0] < epoch_range[0] < epoch_range[1] < custom[1]
    window.result_graph_view.setCurrentIndex(2)
    assert window.figure.axes[0].get_xlim() == pytest.approx(limits)
    assert window.result_time_scroll.isHidden()
    assert window.figure.axes[0]._paradigma_epoch_data is daily
