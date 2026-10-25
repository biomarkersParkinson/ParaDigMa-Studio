"""Raw-data plots interpret increment times without changing analysis inputs."""

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_previews

from paradigma_studio import app as desktop
from paradigma_studio.inspection import input_plot_time, inspect_recording, time_descriptives


@pytest.mark.parametrize("unit", ["difference_s", "difference_ms"])
@pytest.mark.parametrize("first", [0.0, 0.1])
def test_difference_plot_timeline_matches_official_conversion(unit, first):
    from paradigma.util import transform_time_array

    scale = 1000 if unit.endswith("ms") else 1
    series = pd.Series(np.array([first, 0.01, 0.03, 0.01]) * scale, index=[4, 5, 6, 7])
    original = series.copy()
    times, label, timezone = input_plot_time(series, unit)
    np.testing.assert_array_equal(
        times, transform_time_array(series.to_numpy(), unit, "relative_s")
    )
    pd.testing.assert_index_equal(times.index, series.index)
    assert label == "Elapsed time (s)" and timezone is None
    pd.testing.assert_series_equal(series, original)


@pytest.mark.parametrize("unit", ["difference_s", "difference_ms"])
def test_data_time_selection_refreshes_visible_and_hidden_graphs(window, unit):
    scale = 1000 if unit.endswith("ms") else 1
    increments = np.array([0.0, 0.01, 0.03, 0.01]) * scale
    frame = pd.DataFrame(
        {
            "device_delta": increments,
            "gyroscope_x": [1.0, 2.0, 3.0, 4.0],
            "accelerometer_x": [4.0, 3.0, 2.0, 1.0],
        }
    )
    original = frame.copy(deep=True)
    window.loaded(("increments.csv", frame))
    window.data_time_channel.setCurrentIndex(window.data_time_channel.findData("device_delta"))
    window.set_input_channels(["gyroscope_x", "accelerometer_x"])
    window.data_tabs.setCurrentIndex(1)
    window.data_time_unit.setCurrentText(unit)
    assert window.time.currentText() == unit
    assert len(window.data_figure.axes) == 2
    for axes in window.data_figure.axes:
        line = axes.lines[0]
        np.testing.assert_allclose(line.get_xdata(), [0.0, 0.01, 0.04, 0.05])
        np.testing.assert_array_equal(line.get_ydata(), frame[line.get_label()])
        assert axes.get_xlabel() == "Elapsed time (s)"
    # Changing formats from Overview must invalidate the already-rendered plot.
    window.data_tabs.setCurrentIndex(0)
    window.data_time_unit.setCurrentText("relative_s")
    assert window._data_state._data_plot_dirty
    window.data_tabs.setCurrentIndex(1)
    for axes in window.data_figure.axes:
        np.testing.assert_array_equal(axes.lines[0].get_xdata(), increments)
    # Edits on Analyze also update the shared format and invalidate Data graphs.
    window.navigate(1)
    window.time.setCurrentText(unit)
    assert window._data_state._data_plot_dirty
    window.navigate(0)
    for axes in window.data_figure.axes:
        np.testing.assert_allclose(axes.lines[0].get_xdata(), [0.0, 0.01, 0.04, 0.05])
    pd.testing.assert_frame_equal(frame, original)
    pd.testing.assert_frame_equal(window.input_table.model().frame, original)


@pytest.mark.parametrize(
    "unit, raw, elapsed",
    [
        ("relative_s", [0, 0.01, 0.02, 0.03], None),
        ("relative_ms", [0, 10, 20, 30], None),
        ("absolute_s", [1600000000 + i / 100 for i in range(4)], None),
        ("absolute_ms", [1600000000000 + i * 10 for i in range(4)], None),
        ("difference_s", [0, 0.01, 0.02, 0.01], [0, 0.01, 0.03, 0.04]),
        ("difference_ms", [0, 10, 20, 10], [0, 0.01, 0.03, 0.04]),
    ],
)
def test_data_time_format_is_shared_by_all_loaded_recordings(window, unit, raw, elapsed):
    raw = np.array(raw, dtype=float)
    frames = {
        key: pd.DataFrame(
            {"time": raw[0] + factor * (raw - raw[0]), "gyroscope_x": np.arange(4) + factor}
        )
        for key, factor in (("first", 1), ("second", 2))
    }
    originals = {key: frame.copy(deep=True) for key, frame in frames.items()}
    descriptions = {key: inspect_recording(frame, "relative_s") for key, frame in frames.items()}
    window.loaded_recordings(({key: f"{key}.csv" for key in frames}, frames, descriptions))
    window.set_input_channels(["gyroscope_x"])
    window.data_time_unit.setCurrentText(unit)
    for index, tab in ((0, 1), (1, 0), (0, 1)):
        window.data_tabs.setCurrentIndex(tab)
        window.input_recording.setCurrentIndex(index)
        assert window.data_time_unit.currentText() == unit
        wait_for_previews(window)
        key = window.input_recording.currentData()
        stats = window.time_table.model().frame
        pd.testing.assert_frame_equal(stats, time_descriptives(originals[key].time, unit))
        rate = stats.set_index("Statistic").loc["Estimated sampling rate (Hz)", "Value"]
        assert rate == pytest.approx(100 / (index + 1), rel=1e-5)
        window.data_tabs.setCurrentIndex(1)
        expected = (
            originals[key].time.to_numpy() if elapsed is None else np.array(elapsed) * (index + 1)
        )
        line = window.data_figure.axes[0].lines[0]
        np.testing.assert_allclose(line.get_xdata(), expected)
        np.testing.assert_array_equal(line.get_ydata(), originals[key].gyroscope_x)
    assert window.time.currentText() == unit
    for key in frames:
        pd.testing.assert_frame_equal(frames[key], originals[key], check_exact=True)
        pd.testing.assert_frame_equal(
            descriptions[key]["time"], time_descriptives(originals[key].time, "relative_s")
        )


def test_shared_time_format_only_refreshes_viewed_recordings_and_reuses_cached_statistics(
    window, monkeypatch
):
    frames = {
        key: pd.DataFrame({"time": [0, step, step, step], "gyroscope_x": [1.0, 2.0, 3.0, 4.0]})
        for key, step in (("first", 10), ("second", 20), ("unviewed", 30))
    }
    descriptions = {key: inspect_recording(frame, "relative_s") for key, frame in frames.items()}
    window.loaded_recordings(({key: f"{key}.csv" for key in frames}, frames, descriptions))
    wait_for_previews(window)
    calls = []

    def observed(series, unit):
        calls.append((series.iloc[1], unit))
        return time_descriptives(series, unit)

    monkeypatch.setattr(desktop, "time_descriptives", observed)
    window.data_time_unit.setCurrentText("difference_ms")
    wait_for_previews(window)
    assert calls == [(10, "difference_ms")]
    window.input_recording.setCurrentIndex(1)
    assert window.time_table.model() is None and not window.time_table.isEnabled()
    wait_for_previews(window)
    assert calls == [(10, "difference_ms"), (20, "difference_ms")]
    window.input_recording.setCurrentIndex(0)
    assert not window._time_preview.pending and window.time_table.isEnabled()
    pd.testing.assert_frame_equal(
        window.time_table.model().frame, time_descriptives(frames["first"].time, "difference_ms")
    )
    assert calls == [(10, "difference_ms"), (20, "difference_ms")]


def test_elapsed_times_accumulate_all_increments_before_plot_downsampling(window):
    increments = np.resize([0.0, 10.0, 20.0, 30.0], 60001)
    frame = pd.DataFrame({"time": increments, "gyroscope_x": np.arange(len(increments))})
    window.loaded(("long-increments.csv", frame))
    window.data_time_unit.setCurrentText("difference_ms")
    window.set_input_channels(["gyroscope_x"])
    line = window.data_figure.axes[0].lines[0]
    np.testing.assert_array_equal(line.get_xdata(), np.cumsum(increments) / 1000)
    np.testing.assert_array_equal(line.get_ydata(), frame.gyroscope_x)


@pytest.mark.parametrize("invalid", [np.nan, np.inf, pd.NA])
def test_missing_increments_use_sample_positions_without_inventing_time(window, invalid):
    frame = pd.DataFrame({"time": [0.0, 0.01, invalid, 0.01], "gyroscope_x": [1.0, 2.0, 3.0, 4.0]})
    window.loaded(("missing-increments.csv", frame))
    window.data_time_unit.setCurrentText("difference_s")
    window.set_input_channels(["gyroscope_x"])
    axes = window.data_figure.axes[0]
    np.testing.assert_array_equal(axes.lines[0].get_xdata(), np.arange(4))
    assert axes.get_xlabel() == "Sample position"


@pytest.mark.parametrize(
    "series, expected_label",
    [
        (pd.Series(pd.date_range("2026-10-13", periods=3, tz="Europe/Amsterdam")), "Time"),
        (pd.Series(pd.to_timedelta([0, 10, 20], unit="ms")), "Time (s)"),
    ],
)
def test_datetime_and_timedelta_columns_keep_their_native_interpretation(series, expected_label):
    times, label, timezone = input_plot_time(series, "difference_ms")
    expected = series if expected_label == "Time" else series.dt.total_seconds()
    pd.testing.assert_series_equal(times, expected)
    assert label == expected_label
    assert timezone == (series.dt.tz if expected_label == "Time" else None)
