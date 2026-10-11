"""Descriptives from known raw observations; independent of scientific pipelines."""

import numpy as np
import pandas as pd
import pytest

from paradigma_studio.inspection import inspect_recording, sensor_descriptives, time_descriptives


def values(series, unit="relative_s"):
    return time_descriptives(series, unit).set_index("Statistic")["Value"]


def test_sensor_statistics_separate_time_and_handle_missing_and_infinite_samples():
    frame = pd.DataFrame(
        {
            "time": np.arange(7),
            "time_dt": pd.date_range("2026-10-07", periods=7),
            "accelerometer_x": [0.0, 2.0, 4.0, 6.0, 8.0, np.nan, np.inf],
            "empty_sensor": [np.nan] * 7,
        }
    )
    original = frame.copy(deep=True)
    report = inspect_recording(frame, "relative_s")
    table = report["sensors"].set_index("Channel")
    assert table.index.tolist() == ["accelerometer_x", "empty_sensor"]
    assert table.loc["accelerometer_x", "Range"] == "0 – 8"
    assert table.loc["accelerometer_x", "Median"] == 4
    assert table.loc["accelerometer_x", "IQR"] == 4
    assert table.loc["accelerometer_x", "Missing"] == 1
    assert table.loc["accelerometer_x", "Infinite"] == 1
    assert pd.isna(table.loc["empty_sensor", "Median"])
    assert report["missing"] == 8
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize(
    "unit",
    ["relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"],
)
def test_time_encodings_report_the_same_cadence_and_gap(unit):
    times = np.array([0.0, 0.01, 0.02, 0.03, 0.06, 0.07, 0.08])
    if unit.startswith("difference"):
        times = np.r_[0.0, np.diff(times)]
    if unit.startswith("absolute"):
        times += 1_700_000_000
    if unit.endswith("ms"):
        times *= 1000
    result = values(pd.Series(times), unit)
    assert result["Estimated sampling rate (Hz)"] == pytest.approx(100, rel=2e-5)
    assert result["Time span (s)"] == pytest.approx(0.08, rel=2e-5)
    assert result["Gaps (>1.5 × median interval)"] == 1
    assert result["Longest gap interval (s)"] == pytest.approx(0.03, rel=2e-5)
    assert result["Missing / invalid time samples"] == 0


def test_datetime_precision_and_timezone_do_not_change_sampling_rate():
    series = pd.Series(
        pd.to_datetime(
            [
                "2026-10-07T01:00:00Z",
                "2026-10-07T01:00:00.01Z",
                "2026-10-07T01:00:00.02Z",
                "2026-10-07T01:00:00.06Z",
            ],
            format="ISO8601",
        )
    ).dt.tz_convert("Europe/Amsterdam")
    result = values(series)
    assert result["Time span (s)"] == pytest.approx(0.06)
    assert result["Estimated sampling rate (Hz)"] == pytest.approx(100)
    assert result["Gaps (>1.5 × median interval)"] == 1


def test_invalid_timestamps_do_not_create_a_gap_across_unknown_intervals():
    result = values(pd.Series([0.0, 0.01, np.nan, 0.1, 0.11, 0.11, 0.09, np.inf]))
    assert result["Missing / invalid time samples"] == 2
    assert result["Zero-length intervals"] == 1
    assert result["Backward intervals"] == 1
    assert result["Gaps (>1.5 × median interval)"] == 0
    assert result["Estimated sampling rate (Hz)"] == pytest.approx(100)
    delta = values(pd.Series([0.0, 0.01, np.nan, 0.01]), "difference_s")
    assert pd.isna(delta["Time span (s)"])
    assert delta["Estimated sampling rate (Hz)"] == pytest.approx(100)


@pytest.mark.parametrize(
    "series", [pd.Series([], dtype=float), pd.Series([np.nan, np.inf]), pd.Series([1.0])]
)
def test_no_intervals_produces_unknown_cadence_not_an_invented_rate(series):
    result = values(series)
    assert pd.isna(result["Estimated sampling rate (Hz)"])
    assert pd.isna(result["Gaps (>1.5 × median interval)"])


def test_custom_time_channel_is_not_counted_as_a_sensor():
    frame = pd.DataFrame({"device_ticks": [0, 10, 20], "gyroscope_x": [1.0, 2.0, 3.0]})
    assert sensor_descriptives(frame, "device_ticks")["Channel"].tolist() == ["gyroscope_x"]
