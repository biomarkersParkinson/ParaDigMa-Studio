"""Descriptives from known raw observations; independent of scientific pipelines."""

from threading import Barrier, Event, enumerate as active_threads, get_ident

import numpy as np
import pandas as pd
import pytest

from paradigma_studio import analysis_limits, inspection
from paradigma_studio.inspection import (
    inspect_recording,
    inspect_recordings,
    sensor_descriptives,
    time_descriptives,
)


@pytest.mark.parametrize(
    "count,rows,cpus,available_gib,expected",
    [
        (7, 8_640_000, 4, 32, 2),
        (1, 8_640_000, 4, 32, 1),
        (7, 100, 4, 32, 1),
        (7, 8_640_000, 1, 32, 1),
        (7, 8_640_000, 2, 32, 1),
        (7, 8_640_000, 4, 1, 1),
        (7, 8_640_000, 4, None, 1),
        (7, 100_000_000, 4, 8, 1),
    ],
)
def test_inspection_workers_reserve_cpu_and_temporary_array_ram(
    monkeypatch, count, rows, cpus, available_gib, expected
):
    monkeypatch.setattr(analysis_limits, "_available_cpu_count", lambda: cpus)
    monkeypatch.setattr(
        analysis_limits,
        "available_memory",
        lambda: available_gib * analysis_limits.GIB if available_gib is not None else None,
    )
    # RangeIndex represents the real row count without allocating sensor arrays.
    frames = {str(index): pd.DataFrame(index=pd.RangeIndex(rows)) for index in range(count)}
    assert analysis_limits.inspection_worker_count(frames) == expected
    assert analysis_limits.inspection_worker_count({}) == 1


@pytest.mark.parametrize(
    "unit",
    ["relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"],
)
def test_batch_statistics_are_exact_and_keep_read_only_recordings_unchanged(monkeypatch, unit):
    frames = {}
    for index, key in enumerate(("third", "first", "second")):
        frame = pd.DataFrame(
            {
                "time": [0.0, 10.0, 20.0, np.nan, 10.0, 0.0],
                "sensor": [np.nextafter(1.0, 2.0), -0.0, 1e-200, np.inf, np.nan, index],
                "quality": pd.Series([1, 0, pd.NA, 1, 1, 0], dtype="Int64"),
                "label": pd.Series(["a", None, "b", "a", "b", "a"], dtype="string"),
            }
        )
        frame.attrs["desktop_recording_start"] = "2026-10-19T00:00:00+02:00"
        frames[key] = frame
    originals = {key: frame.copy(deep=True) for key, frame in frames.items()}
    expected = {key: inspect_recording(frame, unit) for key, frame in frames.items()}
    for frame in frames.values():
        for column in ("time", "sensor"):
            frame[column].to_numpy().flags.writeable = False
    monkeypatch.setattr(inspection, "inspection_worker_count", lambda _: 2)
    actual = inspect_recordings(frames, unit)
    assert list(actual) == list(frames)
    for key, report in actual.items():
        for name in ("missing", "time_column", "time_unit"):
            assert report[name] == expected[key][name]
        for name in ("sensors", "time"):
            pd.testing.assert_frame_equal(report[name], expected[key][name], check_exact=True)
        pd.testing.assert_frame_equal(frames[key], originals[key], check_exact=True)
        for column in ("time", "sensor"):
            np.testing.assert_array_equal(
                frames[key][column].to_numpy().view(np.uint64),
                originals[key][column].to_numpy().view(np.uint64),
            )
        assert frames[key].attrs == originals[key].attrs


def test_single_worker_statistics_use_the_calling_worker_without_a_pool(monkeypatch):
    monkeypatch.setattr(inspection, "inspection_worker_count", lambda _: 1)
    monkeypatch.setattr(
        inspection,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("A single-worker batch created an additional pool"),
    )
    frames = {"only": pd.DataFrame({"time": [0, 10], "sensor": [0.0, 1.0]})}
    reports = inspect_recordings(frames, "difference_ms")
    expected = inspect_recording(frames["only"], "difference_ms")
    pd.testing.assert_frame_equal(reports["only"]["sensors"], expected["sensors"], check_exact=True)
    pd.testing.assert_frame_equal(reports["only"]["time"], expected["time"], check_exact=True)


def test_two_inspection_workers_overlap_and_retain_file_order(monkeypatch):
    frames = {str(i): pd.DataFrame({"time": [0, 1], "sensor": [i, i + 1]}) for i in range(3)}
    monkeypatch.setattr(inspection, "inspection_worker_count", lambda _: 2)
    gate, second_finished = Barrier(2), Event()
    threads, completions = set(), []
    caller = get_ident()

    def describe(frame, unit):
        number = int(frame.sensor.iloc[0])
        threads.add(get_ident())
        if number < 2:
            gate.wait(timeout=5)
        report = inspect_recording(frame, unit)
        if number == 0:
            assert second_finished.wait(5)
        completions.append(number)
        if number == 1:
            second_finished.set()
        return report

    reports = inspect_recordings(frames, "relative_s", describe=describe)
    assert len(threads) == 2 and caller not in threads
    assert completions[0] == 1
    assert list(reports) == list(frames)
    assert [report["sensors"].Median.iloc[0] for report in reports.values()] == [0.5, 1.5, 2.5]
    assert not any(thread.name.startswith("paradigma-inspection") for thread in active_threads())


@pytest.mark.parametrize("workers", [1, 2])
def test_failed_batch_inspection_raises_and_releases_its_workers(monkeypatch, workers):
    monkeypatch.setattr(inspection, "inspection_worker_count", lambda _: workers)
    frames = {str(i): pd.DataFrame({"time": [0, 1]}) for i in range(2)}

    def describe(frame, unit):
        raise ValueError("Cannot inspect the selected recording")

    with pytest.raises(ValueError, match="Cannot inspect the selected recording"):
        inspect_recordings(frames, "relative_s", describe=describe)
    assert not any(thread.name.startswith("paradigma-inspection") for thread in active_threads())


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


def test_inspection_counts_all_missing_values_and_preserves_mixed_source_types():
    frame = pd.DataFrame(
        {
            "time": [0.0, 0.01, np.nan, 0.03, 0.04, 0.05],
            "time_dt": pd.to_datetime(["2026-10-14"] * 5 + [None], utc=True),
            "gyroscope_x": pd.Series([0, 2, 4, 6, pd.NA, pd.NA], dtype="Int64"),
            "gyroscope_y": [0.0, 2.0, 4.0, 6.0, np.inf, -np.inf],
            "quality": pd.Series([True, False, True, False, pd.NA, pd.NA], dtype="boolean"),
            "label": pd.Series(["a", None, "b", "c", "d", "e"], dtype="string"),
            "category": pd.Categorical(["a", "b", None, "a", "b", "a"]),
            "complex": [1j, 2j, 3j, 4j, complex(np.nan, 0), 6j],
        }
    )
    frame.attrs["desktop_recording_start"] = "2026-10-14T00:00:00+00:00"
    original = frame.copy(deep=True)
    report = inspect_recording(frame, "relative_s")
    sensors = report["sensors"].set_index("Channel")
    assert report["missing"] == 9
    assert sensors["Missing"].to_dict() == {
        "gyroscope_x": 2,
        "gyroscope_y": 0,
        "quality": 2,
        "label": 1,
        "category": 1,
        "complex": 1,
    }
    for channel in ("gyroscope_x", "gyroscope_y"):
        assert sensors.loc[channel, "Median"] == 3
        assert sensors.loc[channel, "IQR"] == 3
        assert sensors.loc[channel, "Range"] == "0 – 6"
    assert sensors.loc["gyroscope_y", "Infinite"] == 2
    pd.testing.assert_frame_equal(
        report["sensors"], sensor_descriptives(frame, "time"), check_exact=True
    )
    pd.testing.assert_frame_equal(report["time"], time_descriptives(frame.time), check_exact=True)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert frame.attrs == original.attrs


@pytest.mark.parametrize("dtype", ["float32", "float64", "Int64"])
@pytest.mark.parametrize("missing", [False, True])
def test_exact_sensor_quantiles_and_source_samples_remain_unchanged(dtype, missing):
    observations = [8, -4, 6, 0, 2, 10, -2, 4]
    series = pd.Series(observations, dtype=dtype)
    if missing:
        series.iloc[2] = pd.NA if dtype == "Int64" else np.nan
    frame = pd.DataFrame({"time": np.arange(len(series)) * 0.01, "sensor": series})
    original = frame.copy(deep=True)
    expected = series.dropna().astype(float).describe(percentiles=[0.25, 0.5, 0.75])
    report = inspect_recording(frame, "relative_s")
    sensor = report["sensors"].iloc[0]
    assert sensor["Median"] == expected["50%"]
    assert sensor["IQR"] == expected["75%"] - expected["25%"]
    assert sensor["Range"] == f"{expected['min']:.5g} – {expected['max']:.5g}"
    assert report["missing"] == int(missing)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
