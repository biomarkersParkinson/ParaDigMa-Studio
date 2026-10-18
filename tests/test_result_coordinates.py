"""Shared display coordinates preserve timestamps, sources and cache lifetimes."""

import gc
import weakref

import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_studio.plotting import plot_bars, time_coordinates
from paradigma_studio.result_plot_cache import ResultPlotCache
from paradigma_studio.results_view import clock_times
from paradigma_studio.ui.result_plot_data import ResultPlotData
from paradigma_studio.workspace_state import ResultState


def prepared(clock=None):
    times = np.array([0, 0.123456789, 1, 10000, np.nan, 86400, 250000])
    name = "quantifications/tremor"
    frame = pd.DataFrame({"time": times, "metric_a": times + 1, "metric_b": times + 2})
    state = ResultState()
    state._plot_tables = {name: frame}
    state._timings = {name: pd.DataFrame({"Timeline time (s)": times})}
    state._bar_bounds = {name: (times.copy(), times + 0.987654321)}
    state.display_clock = clock
    cache = ResultPlotCache()
    cache.bind(state._plot_tables, 0, clock, reset=True)
    return ResultPlotData(state, cache), name, np.arange(len(times))


@pytest.mark.parametrize(
    "clock",
    [
        None,
        {"origin": "2026-10-10T00:00:00.123456789", "timezone": None},
        {"origin": "2026-10-10T00:00:00.123456789Z", "timezone": "UTC"},
        {"origin": "2026-03-29T00:30:00+01:00", "timezone": "Europe/Amsterdam"},
        {"origin": "2026-10-25T00:30:00+02:00", "timezone": "Europe/Amsterdam"},
    ],
)
@pytest.mark.parametrize("subset", [False, True])
def test_shared_coordinates_match_previous_conversion_bit_for_bit(clock, subset):
    data, name, positions = prepared(clock)
    if subset:
        positions = positions[[5, 1, 4, 1, 0]]
    original = data.results._plot_tables[name].copy(deep=True)
    expected = [
        time_coordinates(clock_times(array[positions], clock))
        for array in data.results._bar_bounds[name]
    ]
    actual = data.bar_coordinates(name, positions)
    for result, reference in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(result.view(np.uint64), reference.view(np.uint64))
    repeated = data.bar_coordinates(name, positions)
    assert all(a is b for a, b in zip(actual, repeated, strict=True))
    points = data.point_coordinates(name, positions)
    expected_points = time_coordinates(clock_times(original.time.to_numpy()[positions], clock))
    np.testing.assert_array_equal(points.view(np.uint64), expected_points.view(np.uint64))
    assert data.point_coordinates(name, positions) is points
    pd.testing.assert_frame_equal(data.results._plot_tables[name], original, check_exact=True)


@pytest.mark.parametrize("change", ["positions", "table", "bounds", "clock", "run", "view"])
def test_changed_coordinate_sources_are_not_reused(change):
    data, name, positions = prepared({"origin": "2026-10-10T00:00Z", "timezone": "UTC"})
    previous = data.bar_coordinates(name, positions)
    if change == "positions":
        positions = positions.copy()
    elif change == "table":
        data.results._plot_tables[name] = data.results._plot_tables[name].copy()
    elif change == "bounds":
        start, end = data.results._bar_bounds[name]
        data.results._bar_bounds[name] = start.copy(), end + 1
    elif change == "clock":
        data.results.display_clock = {"origin": "2026-10-11T00:00Z", "timezone": "UTC"}
    else:
        data.cache.bind(
            data.results._plot_tables,
            int(change == "view"),
            data.results.display_clock,
            reset=change == "run",
        )
    actual = data.bar_coordinates(name, positions)
    assert actual[0] is not previous[0] and actual[1] is not previous[1]
    for result, bounds in zip(actual, data.results._bar_bounds[name], strict=True):
        expected = time_coordinates(clock_times(bounds[positions], data.results.display_clock))
        np.testing.assert_array_equal(result.view(np.uint64), expected.view(np.uint64))


def test_coordinates_share_the_geometry_budget_and_evict_old_arrays():
    cache = ResultPlotCache()
    source = np.arange(8.0)
    axes = Figure().add_subplot()
    plot_bars(axes, source, source + 1, source + 2, "blue")
    cache.capture(("dataset", "metric"), axes)
    assert cache.memory_bytes > 0
    cache.MAX_BYTES = cache.memory_bytes + 128
    cache.MAX_COORDINATE_ENTRIES = 1
    arrays = cache.coordinates(("first",), (source,), None, lambda: (np.arange(64.0),))
    old = weakref.ref(arrays[0])
    assert cache.memory_bytes == 0  # Make room inside the existing total budget.
    assert 0 < cache.coordinate_bytes <= cache.MAX_BYTES
    del arrays
    cache.coordinates(("second",), (source,), None, lambda: (np.arange(64.0),))
    gc.collect()
    assert old() is None
    cache.MAX_COORDINATE_BYTES = 1
    cache.coordinates(("large",), (source,), None, lambda: (np.arange(64.0),))
    assert cache.coordinate_bytes == 0
    cache.MAX_BYTES = 0
    cache.coordinates(("disabled",), (source,), None, lambda: (np.arange(64.0),))
    assert cache.memory_bytes == cache.coordinate_bytes == 0


def test_coordinates_do_not_keep_source_frames_alive_and_clear_releases_arrays():
    data, name, positions = prepared()
    cache = data.cache
    frame = weakref.ref(data.results._plot_tables[name])
    start, end = data.bar_coordinates(name, positions)
    result = weakref.ref(start)
    del data, positions, start, end
    gc.collect()
    assert frame() is None and result() is not None
    cache.clear()
    assert result() is None and cache.coordinate_bytes == 0


def test_new_continuous_metrics_share_conversion_and_keep_uncached_pixels(window, monkeypatch):
    from paradigma_studio.ui import result_plot_data

    times = np.arange(4000.0)
    window._result_state.provenance = {
        "display_clock": {"origin": "2026-10-10T00:00Z", "timezone": "Europe/Amsterdam"}
    }
    frame = pd.DataFrame({"time": times, **{f"metric_{i}": times + i + 2 for i in range(3)}})
    original = frame.copy(deep=True)
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    conversions = []

    def convert(values, clock):
        conversions.append(len(values))
        return clock_times(values, clock)

    monkeypatch.setattr(result_plot_data, "clock_times", convert)
    window.result_series.blockSignals(True)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window._result_state._plot_signature = None
    window.plot()
    QApplication.instance().processEvents()
    assert conversions == [len(frame), len(frame)]
    cache = window._graph_state._result_plot_cache
    assert 0 < cache.coordinate_bytes <= cache.MAX_COORDINATE_BYTES
    assert cache.coordinate_bytes + cache.memory_bytes <= cache.MAX_BYTES
    pixels = np.asarray(window.canvas.buffer_rgba()).copy()
    cache.MAX_BYTES = 0
    window._result_state._plot_signature = None
    window.plot()
    QApplication.instance().processEvents()
    assert conversions == [len(frame)] * 8  # Two conversions per uncached metric.
    np.testing.assert_array_equal(window.canvas.buffer_rgba(), pixels)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    window.clear_results()
    assert cache.coordinate_bytes == 0
