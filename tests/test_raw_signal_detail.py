"""Raw graphs retain source cadence and extrema as the visible time range changes."""

import io
import weakref

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from paradigma_studio.channels import plot_channel_signals
from paradigma_studio.inspection import input_plot_time


def captured_signal(monkeypatch):
    captures = []
    draw = Line2D.draw

    def capture(line, renderer):
        if line.get_label() == "accelerometer_x":
            captures.append(line.get_xydata().copy())
        return draw(line, renderer)

    monkeypatch.setattr(Line2D, "draw", capture)
    return captures


def raw_plot(frame, xs):
    figure = Figure(figsize=(9, 4), dpi=100)
    canvas = FigureCanvasAgg(figure)
    plot_channel_signals(
        figure, frame, ["accelerometer_x"], {"accelerometer_x": "#2864A5"}, xs, "Time"
    )
    canvas.draw()
    return figure, canvas


@pytest.mark.parametrize("unit", ["difference_s", "difference_ms", "calendar"])
def test_zoom_into_long_recording_renders_every_original_sample(monkeypatch, unit):
    seconds = np.arange(300_001) / 100
    values = np.sin(2 * np.pi * 12 * seconds)
    increments = np.r_[0, np.full(len(seconds) - 1, 0.01)]
    frame = pd.DataFrame({"time": increments, "accelerometer_x": values})
    if unit == "calendar":
        xs = pd.Series(
            pd.Timestamp("2026-10-20T12:00:00+02:00") + pd.to_timedelta(seconds, unit="s")
        )
        coordinates = dates.date2num(xs)
    else:
        if unit.endswith("ms"):
            frame["time"] *= 1000
        xs, _, _ = input_plot_time(frame.time, unit)
        coordinates = xs.to_numpy()
    original = frame.copy(deep=True)
    captures = captured_signal(monkeypatch)
    figure, canvas = raw_plot(frame, xs)
    for begin, end in ((100_000, 102_000), (150_000, 152_000)):
        bounds = coordinates[[begin, end]]
        figure.axes[0].set_xlim(*bounds)
        canvas.draw()
        actual = captures[-1]
        visible = actual[(actual[:, 0] >= bounds[0]) & (actual[:, 0] <= bounds[1])]
        np.testing.assert_array_equal(visible[:, 0], coordinates[begin : end + 1])
        np.testing.assert_array_equal(visible[:, 1], values[begin : end + 1])
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


def test_wide_raw_view_keeps_single_sample_extrema_and_the_final_sample(monkeypatch):
    times = np.arange(200_003) / 100
    values = np.zeros(len(times))
    values[10_003], values[50_007], values[-1] = 81.0, -93.0, 17.0
    frame = pd.DataFrame({"time": times, "accelerometer_x": values})
    captures = captured_signal(monkeypatch)
    figure, canvas = raw_plot(frame, frame.time)
    actual = captures[-1]
    for position in (10_003, 50_007, len(times) - 1):
        assert np.any((actual[:, 0] == times[position]) & (actual[:, 1] == values[position]))
    assert figure.axes[0].get_ylim()[0] < -93 and figure.axes[0].get_ylim()[1] > 81
    assert len(actual) < len(times) // 2


def test_missing_sensor_runs_break_the_path_and_exports_keep_original_samples(monkeypatch):
    times = np.arange(200_003) / 100
    values = np.sin(times)
    values[50_003:51_008] = np.nan
    values[90_001] = np.inf
    frame = pd.DataFrame({"time": times, "accelerometer_x": values})
    original = frame.copy(deep=True)
    captures = captured_signal(monkeypatch)
    figure, canvas = raw_plot(frame, frame.time)
    actual = captures[-1]
    positions = np.searchsorted(times, actual[:, 0])
    invalid = np.r_[0, np.cumsum(~np.isfinite(values))]
    connected = np.isfinite(actual[:-1, 1]) & np.isfinite(actual[1:, 1])
    assert np.any(~np.isfinite(actual[:, 1]))
    np.testing.assert_array_equal(
        invalid[positions[1:][connected] + 1] - invalid[positions[:-1][connected]], 0
    )
    output = io.BytesIO()
    canvas.print_figure(output, format="svg")
    np.testing.assert_array_equal(captures[-1][:, 0], times)
    np.testing.assert_array_equal(captures[-1][:, 1], values)
    assert output.getvalue().startswith(b"<?xml")
    assert len(figure.axes[0].lines[0]._xy) < len(times) // 2
    figure.axes[0].set_xlim(600, 620)
    canvas.draw()
    figure.axes[0].relim()
    figure.axes[0].autoscale(enable=True, axis="both")
    canvas.draw()
    assert figure.axes[0].get_xlim()[0] <= times[0]
    assert figure.axes[0].get_xlim()[1] >= times[-1]
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


def test_cached_summaries_preserve_extrema_in_partial_edge_blocks(monkeypatch):
    from paradigma_studio import raw_signals

    times = np.arange(1_024_003, dtype=float)
    values = np.zeros(len(times))
    positions = [100_005, 100_083, 899_921, 899_999]
    values[positions] = [100, -101, 102, -103]
    frame = pd.DataFrame({"time": times, "accelerometer_x": values})
    captures = captured_signal(monkeypatch)
    figure, canvas = raw_plot(frame, frame.time)
    original = raw_signals._block_extrema

    def inspect(values, begin, end, step, all_finite):
        assert end - begin <= 4096, "Scrolling at a cached scale must not rescan the full recording"
        return original(values, begin, end, step, all_finite)

    monkeypatch.setattr(raw_signals, "_block_extrema", inspect)
    for shift in (0, 1, -1):
        figure.axes[0].set_xlim(100_003 + shift, 900_001 + shift)
        canvas.draw()
        actual = captures[-1]
        for position in positions:
            assert np.any((actual[:, 0] == times[position]) & (actual[:, 1] == values[position]))
    assert figure.axes[0].lines[0].summary_bytes <= raw_signals.SUMMARY_BYTES


def test_unsorted_and_missing_timestamps_keep_source_order_and_path_breaks(monkeypatch):
    times = np.array([2, 0, 0, np.nan, 3, 1, 4], dtype=float)
    values = np.array([20, 0, 1, 99, 30, 10, 40], dtype=float)
    frame = pd.DataFrame({"time": times, "accelerometer_x": values})
    captures = captured_signal(monkeypatch)
    figure, canvas = raw_plot(frame, frame.time)
    figure.axes[0].set_xlim(0.5, 2.5)
    canvas.draw()
    np.testing.assert_array_equal(captures[-1][:, 0], times)
    np.testing.assert_array_equal(captures[-1][:, 1], values)


def test_raw_summary_cache_releases_old_levels_and_remains_bounded(monkeypatch):
    from paradigma_studio import raw_signals

    monkeypatch.setattr(raw_signals, "DISPLAY_POINTS", 1024)
    times = np.arange(2_000_003, dtype=float)
    frame = pd.DataFrame({"time": times, "accelerometer_x": np.sin(times)})
    figure, canvas = raw_plot(frame, frame.time)
    line = figure.axes[0].lines[0]
    first = weakref.ref(next(iter(line._summaries.values())))
    for span in (1_000_000, 500_000, 250_000, 125_000, 64_000, 32_000):
        figure.axes[0].set_xlim(10, 10 + span)
        canvas.draw()
        assert line.summary_bytes <= raw_signals.SUMMARY_BYTES
    assert first() is None
    np.testing.assert_array_equal(line.get_xdata(), times)
    np.testing.assert_array_equal(line.get_ydata(), frame.accelerometer_x)


def test_failed_raw_draw_restores_the_full_extent_and_can_be_drawn_again(monkeypatch):
    times = np.arange(200_003) / 100
    frame = pd.DataFrame({"time": times, "accelerometer_x": np.sin(times)})
    figure, canvas = raw_plot(frame, frame.time)
    axes = figure.axes[0]
    original = Line2D.draw

    def fail(line, renderer):
        if line.get_label() == "accelerometer_x":
            raise RuntimeError("Controlled raw-render failure")
        return original(line, renderer)

    axes.set_xlim(1000, 1020)
    with monkeypatch.context() as patch:
        patch.setattr(Line2D, "draw", fail)
        with pytest.raises(RuntimeError, match="Controlled raw-render failure"):
            canvas.draw()
    axes.relim()
    axes.autoscale(enable=True, axis="both")
    canvas.draw()
    assert axes.get_xlim()[0] <= times[0] and axes.get_xlim()[1] >= times[-1]
    np.testing.assert_array_equal(axes.lines[0].get_ydata(), frame.accelerometer_x)


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
def test_long_raw_graph_restores_source_rate_after_toolbar_zoom_and_home(
    window, monkeypatch, context
):
    from paradigma_studio.exploration import SensorContext

    times = np.arange(300_001) / 100
    frame = pd.DataFrame({"time": times, "accelerometer_x": np.sin(times)})
    captures = captured_signal(monkeypatch)
    window.loaded(("long.csv", frame))
    if context:
        window._sensor_state._sensor_context = SensorContext(
            frame, times, times, 0, times[-1], 1500.0
        )
        window._sensor_controller.show_sensor_context()
        figure, canvas, toolbar = window.sensor_figure, window.sensor_canvas, window.sensor_toolbar
    else:
        window.set_input_channels(["accelerometer_x"])
        figure, canvas, toolbar = window.data_figure, window.data_canvas, window.data_toolbar
    axes = figure.axes[0]
    full = axes.get_xlim()
    toolbar.push_current()
    axes.set_xlim(1000, 1020)
    toolbar.push_current()
    canvas.draw()
    actual = captures[-1]
    visible = actual[(actual[:, 0] >= 1000) & (actual[:, 0] <= 1020)]
    np.testing.assert_array_equal(visible[:, 0], times[100_000:102_001])
    np.testing.assert_array_equal(visible[:, 1], frame.accelerometer_x.iloc[100_000:102_001])
    toolbar.home()
    canvas.draw()
    np.testing.assert_allclose(axes.get_xlim(), full)
    np.testing.assert_array_equal(axes.lines[0].get_xdata(), times)
    np.testing.assert_array_equal(axes.lines[0].get_ydata(), frame.accelerometer_x)
    pd.testing.assert_frame_equal(window._input_state.frame, frame, check_exact=True)
