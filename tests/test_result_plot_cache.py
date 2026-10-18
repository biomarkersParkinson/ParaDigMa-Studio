"""Deselected bar geometry is exact, bounded and independent of detached Axes."""

import gc
import weakref
from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def prepare(window, mode=0, pixel_ratio=1):
    times = np.arange(0, 3 * 86400, 60.0)
    values = 2 + np.sin(times / 2000)
    values[100:120] = np.nan
    values[400:450] = 0
    frame = pd.DataFrame(
        {"time": times, "metric_a": values, "metric_b": -values, "metric_c": values * 3}
    )
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.result_graph_view.setCurrentIndex(mode)
    window.plot()
    window.canvas._set_device_pixel_ratio(pixel_ratio)
    QApplication.instance().processEvents()
    return frame


@pytest.mark.parametrize("mode", range(4))
@pytest.mark.parametrize("pixel_ratio", [1, 2])
def test_reselected_bars_reuse_every_path_and_match_uncached_pixels(window, mode, pixel_ratio):
    frame = prepare(window, mode, pixel_ratio)
    original = frame.copy(deep=True)
    ax = window.figure.axes[-1]
    paths = ax.collections[0].get_paths()
    vertices = [path.vertices.copy() for path in paths]
    item = window._result_state._series_items[ax._paradigma_dataset, ax._paradigma_metric]
    cache = window._graph_state._result_plot_cache
    item.setCheckState(0, Qt.Unchecked)
    QApplication.instance().processEvents()
    assert 0 < cache.memory_bytes <= cache.MAX_BYTES
    item.setCheckState(0, Qt.Checked)
    QApplication.instance().processEvents()
    restored = window.figure.axes[-1]
    assert restored is not ax and restored.collections[0].get_paths() is paths
    assert cache.memory_bytes == 0
    pixels = np.asarray(window.canvas.buffer_rgba()).copy()
    cache.MAX_BYTES = 0
    item.setCheckState(0, Qt.Unchecked)
    item.setCheckState(0, Qt.Checked)
    QApplication.instance().processEvents()
    np.testing.assert_array_equal(window.canvas.buffer_rgba(), pixels)
    for actual, expected in zip(paths, vertices, strict=True):
        np.testing.assert_array_equal(actual.vertices, expected)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


def test_deselected_geometry_releases_axes_and_is_released_when_results_are_discarded(window):
    prepare(window)
    ax = window.figure.axes[-1]
    axes = weakref.ref(ax)
    data = weakref.ref(ax.collections[0]._starts)
    item = window._result_state._series_items[ax._paradigma_dataset, ax._paradigma_metric]
    del ax
    item.setCheckState(0, Qt.Unchecked)
    QApplication.instance().processEvents()
    gc.collect()
    assert axes() is None and data() is not None
    window.clear_results()
    gc.collect()
    assert data() is None
    assert window._graph_state._result_plot_cache.memory_bytes == 0


def test_cache_evicts_old_entries_and_rejects_geometry_over_its_byte_budget(window):
    prepare(window)
    cache = window._graph_state._result_plot_cache
    cache.MAX_ENTRIES = 1
    items = list(window._result_state._series_items.values())
    first = weakref.ref(window.figure.axes[1].collections[0]._starts)
    items[1].setCheckState(0, Qt.Unchecked)
    QApplication.instance().processEvents()
    assert first() is not None
    items[2].setCheckState(0, Qt.Unchecked)
    QApplication.instance().processEvents()
    gc.collect()
    assert first() is None and len(cache._entries) == 1
    cache.clear()
    cache.MAX_BYTES = 1
    items[0].setCheckState(0, Qt.Unchecked)
    QApplication.instance().processEvents()
    assert cache.memory_bytes == 0 and not cache._entries


@pytest.mark.parametrize("change", ["run", "view", "clock"])
def test_cached_geometry_is_invalidated_before_results_context_changes(window, change):
    frame = prepare(window)
    item = list(window._result_state._series_items.values())[-1]
    item.setCheckState(0, Qt.Unchecked)
    QApplication.instance().processEvents()
    cache = window._graph_state._result_plot_cache
    assert cache.memory_bytes
    if change == "view":
        window.result_graph_view.setCurrentIndex(1)
    elif change == "clock":
        window._result_state.display_clock = {"origin": "2026-10-10T00:00Z", "timezone": "UTC"}
        cache.bind(
            window._result_state._plot_tables, 0, window._result_state.display_clock, reset=False
        )
    else:
        window.analyzed({"quantifications": {"tremor": frame.assign(metric_c=100)}})
    assert cache.memory_bytes == 0


@pytest.mark.parametrize("format", ["png", "pdf", "svg"])
def test_reselected_plot_exports_all_original_bars_without_deselected_graphs(window, format):
    prepare(window)
    item = list(window._result_state._series_items.values())[-1]
    paths = window.figure.axes[-1].collections[0].get_paths()
    item.setCheckState(0, Qt.Unchecked)
    item.setCheckState(0, Qt.Checked)
    QApplication.instance().processEvents()
    assert window.figure.axes[-1].collections[0].get_paths() is paths
    output = BytesIO()
    window.figure.savefig(output, format=format, dpi=600)
    assert len(output.getvalue()) > 1000
    assert window.figure.axes[-1].collections[0].get_paths() is paths
    assert len(window.figure.axes) == 3
