"""A 24-hour profile averages valid daily epochs, never pooled raw samples."""

from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from conftest import select_plot_metric
from PySide6.QtCore import Qt

from paradigma_studio.epoch_profile import (
    format_profile_time,
    mean_epoch_profile,
    parse_profile_time,
)
from paradigma_studio.epochs import availability_epoch_summary, epoch_phase, epoch_summary
from paradigma_studio.gait_presence import gait_epoch_summaries, gait_presence_intervals


def test_continuous_profile_gives_equal_weight_to_daily_epoch_medians_not_samples():
    times = [0, 1, 2, 3, 4, 86400, 172800]
    values = [1, 2, 3, 4, 100, 20, 90]
    epochs = epoch_summary(times, values)
    original = epochs.copy(deep=True)
    profile = mean_epoch_profile(epochs, None)
    assert profile.value.iloc[0] == pytest.approx((3 + 20 + 90) / 3)
    assert profile.n_days.iloc[0] == 3
    assert len(profile) == 48
    assert profile.value.iloc[1:].isna().all()
    assert profile.n_days.iloc[1:].eq(0).all()
    pd.testing.assert_frame_equal(epochs, original, check_exact=True)


def test_binary_profile_averages_percentages_ignoring_unknowns_but_retaining_known_zero():
    epochs = epoch_summary(
        [0, 1, 2, 3, 86400, 172800, 259200],
        [0, 0, 0, 1, 1, np.nan, 0],
        binary=True,
    )
    profile = mean_epoch_profile(epochs, None)
    assert profile.value.iloc[0] == pytest.approx((25 + 100 + 0) / 3)
    assert profile.n_days.iloc[0] == 3


@pytest.mark.parametrize("origin", ["2026-10-14T10:07:15+05:45", "2026-10-14T10:07:15"])
def test_profile_uses_source_local_half_hours_and_retains_partial_epochs(origin):
    stamp = pd.Timestamp(origin)
    clock = {"origin": origin, "timezone": str(stamp.tz) if stamp.tz else None}
    epochs = epoch_summary([0, 86400], [10, 30], phase=epoch_phase(clock))
    profile = mean_epoch_profile(epochs, clock)
    assert profile.value.iloc[20] == 20  # 10:00–10:30, including the first partial epoch.
    assert profile.n_days.iloc[20] == 2
    assert profile.value.notna().sum() == 1
    np.testing.assert_array_equal(profile.start_s, np.arange(48) * 1800)
    assert profile.end_s.iloc[-1] == 86400


def test_dst_repeated_epochs_contribute_once_per_local_day_and_missing_slots_stay_missing():
    clock = {"origin": "2026-10-24T00:00:00+02:00", "timezone": "Europe/Amsterdam"}
    stamps = pd.to_datetime(
        ["2026-10-24T00:00Z", "2026-10-25T00:00Z", "2026-10-25T01:00Z", "2026-10-26T01:00Z"]
    )
    times = (stamps - pd.Timestamp(clock["origin"])).total_seconds()
    profile = mean_epoch_profile(epoch_summary(times, [10, 20, 80, 40]), clock)
    assert profile.value.iloc[4] == pytest.approx((10 + (20 + 80) / 2 + 40) / 3)
    assert profile.n_days.iloc[4] == 3
    assert profile.value.notna().sum() == 1


def test_spring_forward_skips_missing_clock_slots_without_inserting_absence():
    clock = {"origin": "2026-03-28T00:00:00+01:00", "timezone": "Europe/Amsterdam"}
    stamps = pd.to_datetime(["2026-03-28T01:00Z", "2026-03-29T01:00Z", "2026-03-30T00:00Z"])
    times = (stamps - pd.Timestamp(clock["origin"])).total_seconds()
    profile = mean_epoch_profile(epoch_summary(times, [10, 60, 30]), clock)
    assert profile.value.iloc[4] == 20  # 02:00 exists on two days.
    assert profile.n_days.iloc[4] == 2
    assert profile.value.iloc[6] == 60  # 03:00 on the spring-forward day.
    assert profile.n_days.iloc[6] == 1


def test_coverage_includes_known_empty_epochs_and_gait_profile_preserves_filtered_subset():
    coverage = availability_epoch_summary([0], [1800], bounds=(0, 86400 + 1800))
    profile = mean_epoch_profile(coverage, None)
    assert profile.value.iloc[0] == 50 and profile.n_days.iloc[0] == 2
    detection = pd.DataFrame({"start": [0, 86400], "end": [1800, 88200], "state": [1, 0]})
    arm = pd.DataFrame({"start": [0], "end": [900], "state": [1]})
    summaries = gait_epoch_summaries(gait_presence_intervals(detection, arm))
    gait = mean_epoch_profile(summaries["gait"], None)
    filtered = mean_epoch_profile(summaries["filtered"], None)
    assert gait.value.iloc[0] == filtered.value.iloc[0] == 50
    np.testing.assert_array_equal(gait.n_days, filtered.n_days)
    valid = gait.value.notna()
    assert filtered.value[valid].le(gait.value[valid]).all()


@pytest.mark.parametrize("clock", [None, {"origin": "2026-10-14T00:00Z", "timezone": "UTC"}])
def test_empty_and_invalid_profiles_keep_a_blank_24_hour_domain(clock):
    for summary in (
        epoch_summary([], []),
        pd.DataFrame({"start_s": [0, 1800, np.nan], "value": [np.nan, np.inf, 100]}),
    ):
        profile = mean_epoch_profile(summary, clock)
        assert len(profile) == 48
        assert profile.value.isna().all() and profile.n_days.eq(0).all()


@pytest.mark.parametrize(
    "seconds,text",
    [(0, "00:00"), (86400, "24:00"), (5400, "01:30"), (5415.5, "01:30:15.5"), (-1800, "-00:30")],
)
def test_profile_time_limits_round_trip_including_24_hour_endpoint(seconds, text):
    assert format_profile_time(seconds) == text
    assert parse_profile_time(text) == seconds
    assert parse_profile_time(str(seconds)) == seconds


@pytest.mark.parametrize(
    "text", ["00:60", "12:30:60", "x:30", "10:20:30:40", "01:nan", "12:00:nan"]
)
def test_invalid_profile_time_limits_are_rejected(text):
    with pytest.raises(ValueError):
        parse_profile_time(text)


def profile_results():
    times = np.concatenate([np.arange(day * 86400, day * 86400 + 1800, 4) for day in range(3)])
    presence = np.concatenate([np.arange(0, 1800, 4) < seconds for seconds in (100, 80, 120)])
    return {
        "classifications": {
            "tremor": pd.DataFrame({"time": times, "pred_tremor_checked": presence.astype(int)})
        },
        "quantifications": {
            "tremor": pd.DataFrame(
                {"time": [0, 4, 8, 86400, 172800], "tremor_power": [0, 9, 99, 999, 9999]}
            ),
            "pulse_rate": pd.DataFrame(
                {"time": [0, 60, 120, 86400, 172800], "pulse_rate": [50, 60, 200, 90, 120]}
            ),
        },
        "metadata": {
            "desktop_availability": {
                "tremor": {
                    "df_1": {"intervals": [[day * 86400, day * 86400 + 1800] for day in range(3)]}
                }
            }
        },
    }


def select_profile_graphs(window):
    window.result_series.blockSignals(True)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.result_tabs.setCurrentIndex(1)
    window.result_graph_view.setCurrentIndex(3)
    window.plot()
    return {(ax._paradigma_dataset, ax._paradigma_metric): ax for ax in window.figure.axes}


@pytest.mark.parametrize("clock", [None, {"origin": "2026-10-14T00:00+05:45", "timezone": None}])
def test_live_profile_reuses_epoch_rules_and_preserves_all_original_values(window, clock):
    window.provenance = {"display_clock": clock} if clock else {}
    output = profile_results()
    original = deepcopy(output)
    window.analyzed(output)
    axes = select_profile_graphs(window)
    power = axes["quantifications/tremor", "tremor_power"]
    assert power._paradigma_epoch_data.value.iloc[0] == 2.5  # Mean of gated medians 1 and 4.
    assert power._paradigma_epoch_data.n_days.iloc[0] == 2
    pulse = axes["quantifications/pulse_rate", "pulse_rate"]
    assert pulse._paradigma_epoch_data.value.iloc[0] == 90  # Medians 60, 90, 120.
    presence = axes["classifications/tremor", "pred_tremor_checked"]
    assert presence._paradigma_epoch_data.value.iloc[0] == pytest.approx(100 / 18)
    assert all(ax._paradigma_profile and ax._paradigma_bars for ax in axes.values())
    assert all(ax.get_xlim() == (0, 86400) for ax in axes.values())
    assert all(ax.get_autoscaley_on() for ax in axes.values())
    assert not window.context_button.isEnabled()
    for stage in ("classifications", "quantifications"):
        for module, frame in output[stage].items():
            pd.testing.assert_frame_equal(frame, original[stage][module], check_exact=True)
            pd.testing.assert_frame_equal(
                window.tables[f"{stage}/{module}"], frame, check_exact=True
            )
    window.canvas.draw()
    window.time_axis.draw()
    labels = [label.get_text() for label in window.time_axis.axes.get_xticklabels()]
    assert "00:00" in labels and "24:00" in labels
    renderer = window.time_axis.get_renderer()
    for label in window.time_axis.axes.get_xticklabels():
        box = label.get_window_extent(renderer)
        assert 0 <= box.x0 <= box.x1 <= window.time_axis.figure.bbox.x1
    assert not window.time_axis.axes.get_xticklabels(minor=True)
    destination = BytesIO()
    window.figure.savefig(destination, format="png", dpi=150)
    assert destination.getvalue().startswith(b"\x89PNG")
    for mode in (0, 1, 2):
        window.result_graph_view.setCurrentIndex(mode)
        assert not any(ax._paradigma_profile for ax in window.figure.axes)


def test_profile_click_selects_a_clock_slot_without_fabricating_a_dated_sample(window, monkeypatch):
    window.analyzed(profile_results())
    axes = select_profile_graphs(window)
    power = axes["quantifications/tremor", "tremor_power"]
    window.dataset.setCurrentText("quantifications/pulse_rate")
    window.result_table.selectRow(0)
    selected = window.result_table.currentIndex()
    window.graph_clicked(SimpleNamespace(inaxes=power, xdata=300))
    assert window.dataset.currentText() == "quantifications/pulse_rate"
    assert window.result_table.currentIndex() == selected
    assert window.time_axis._selected_x == 900
    assert window.time_axis.selection_label.get_text() == "00:00–00:30 · 2 days"
    point = next(
        artist
        for artist in window._graph_state._result_selection_artists
        if artist.get_gid() == "selected-result-point"
    )
    assert point.get_xdata()[0] == 900 and point.get_ydata()[0] == 2.5
    window.graph_clicked(SimpleNamespace(inaxes=power, xdata=3600))
    assert window.time_axis._selected_x == 900  # Empty slots cannot create a result selection.
    cached = power._paradigma_epoch_data
    coverage_key = next(key for key in window._series_items if key[0].startswith("preparation/"))
    window._series_items[coverage_key].setCheckState(0, Qt.Unchecked)
    power = next(ax for ax in window.figure.axes if ax._paradigma_metric == "tremor_power")
    assert power._paradigma_epoch_data is cached and window.time_axis._selected_x == 900
    reads = []
    original_values = window._graph_controller.data._result_plot_values

    def read_values(*args):
        reads.append(args)
        return original_values(*args)

    with monkeypatch.context() as patch:
        patch.setattr(
            window._graph_controller.data,
            "_result_plot_values",
            read_values,
        )
        window._series_items[coverage_key].setCheckState(0, Qt.Checked)
    assert not reads, "A cached aggregate view reread the raw sample values"
    replacement = profile_results()
    replacement["quantifications"]["pulse_rate"]["pulse_rate"] *= 2
    window.analyzed(replacement)
    assert window._result_state._profile_selection is None
    assert window.time_axis._selected_x is None
    refreshed = select_profile_graphs(window)
    assert (
        refreshed["quantifications/pulse_rate", "pulse_rate"]._paradigma_epoch_data.value.iloc[0]
        == 180
    )


def test_gait_profile_gates_each_daily_epoch_before_averaging_filtered_and_unfiltered_metrics(
    window,
):
    times = np.concatenate([day * 86400 + np.arange(1800) for day in range(3)])
    gait = np.concatenate([np.arange(1800) < seconds for seconds in (89, 90, 180)])
    # Match the filtering model's 0.75 s update cadence, so 90 s is real
    # jointly observed presence rather than 90 sparsely spaced filter windows.
    arm_times = np.concatenate([day * 86400 + np.arange(0, 1800, 0.75) for day in range(3)])
    filtered = np.concatenate([np.arange(0, 1800, 0.75) < seconds for seconds in (89, 90, 80)])
    swings = pd.DataFrame(
        {
            "time": [100, 86500, 172900],
            "range_of_motion": [100, 20, 40],
            "peak_velocity": [1000, 10, 30],
        }
    )
    window.analyzed(
        {
            "classifications": {
                "gait": {
                    "detection": pd.DataFrame(
                        {"time": times, "pred_gait_proba": gait.astype(float)}
                    ),
                    "arm_activity": pd.DataFrame(
                        {
                            "time": arm_times,
                            "pred_no_other_arm_activity_proba": filtered.astype(float),
                        }
                    ),
                }
            },
            "quantifications": {"gait": {"filtered": swings.copy(), "unfiltered": swings}},
        }
    )
    axes = select_profile_graphs(window)
    for kind, range_of_motion, peak_velocity, days in (
        ("unfiltered", 30, 20, 2),
        ("filtered", 20, 10, 1),
    ):
        name = f"quantifications/gait/{kind}"
        for metric, expected in (
            ("range_of_motion", range_of_motion),
            ("peak_velocity", peak_velocity),
        ):
            summary = axes[name, metric]._paradigma_epoch_data
            assert summary.value.iloc[0] == expected and summary.n_days.iloc[0] == days
    gait_profile = axes["classifications/gait/detection", "pred_gait_window"]._paradigma_epoch_data
    filtered_profile = axes[
        "classifications/gait/arm_activity", "pred_no_other_arm_activity_window"
    ]._paradigma_epoch_data
    assert filtered_profile.value.iloc[0] <= gait_profile.value.iloc[0]


def test_sensor_inspection_is_restored_when_returning_to_a_dated_view(window):
    window.analyzed(profile_results())
    window.result_tabs.setCurrentIndex(1)
    window.result_source_frame = pd.DataFrame({"time": [0.0, 1.0], "gyroscope_x": [1.0, 2.0]})
    window.dataset.setCurrentText("classifications/tremor")
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    assert window.context_button.isEnabled()
    window.result_graph_view.setCurrentIndex(3)
    assert not window.context_button.isEnabled()
    window.result_tabs.setCurrentIndex(2)
    assert window.context_button.isEnabled()
    window.result_tabs.setCurrentIndex(1)
    assert not window.context_button.isEnabled()
    window.result_graph_view.setCurrentIndex(1)
    assert window.context_button.isEnabled()


def test_profile_limits_accept_clock_times_reset_to_24_hours_and_do_not_carry_dates(window):
    window.provenance = {"display_clock": {"origin": "2026-10-14T00:00Z", "timezone": "UTC"}}
    window.analyzed(profile_results())
    select_plot_metric(window, "classifications/tremor", "pred_tremor_checked")
    window.figure.axes[0].set_xlim(
        *window.figure.axes[0].get_xlim()
    )  # A manual recording-time view.
    window.result_graph_view.setCurrentIndex(3)
    ax = window.figure.axes[0]
    assert ax.get_xlim() == (0, 86400)
    toolbar = window.plot_toolbar
    toolbar.active_axes = ax
    toolbar.settings_action.setChecked(True)
    automatic, lower, upper = toolbar.settings.bounds["x"]
    assert lower.text() == "00:00" and upper.text() == "24:00"
    automatic.setChecked(False)
    lower.setText("06:00")
    upper.setText("18:00")
    upper.editingFinished.emit()
    assert ax.get_xlim() == (21600, 64800)
    upper.setText("18:90")
    upper.editingFinished.emit()
    assert toolbar.settings.error.isVisible() and ax.get_xlim() == (21600, 64800)
    toolbar.settings.reset_button.click()
    assert ax.get_xlim() == (0, 86400)
    ax.set_xlim(21600, 64800)
    window.result_graph_view.setCurrentIndex(1)
    assert window.figure.axes[0].get_xlim()[0] > 20000  # Calendar coordinates, not profile seconds.
    window.result_graph_view.setCurrentIndex(3)
    assert window.figure.axes[0].get_xlim() == (0, 86400)
