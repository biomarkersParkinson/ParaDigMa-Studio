"""Bound rendering work without sampling, changing values or losing intervals."""

from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import PolyCollection
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_studio.plotting import plot_bars, plot_states


@pytest.mark.parametrize("binary", [False, True])
def test_zoom_renders_only_intersecting_intervals_and_restores_all_original_values(
    binary, monkeypatch
):
    figure = Figure()
    canvas = FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    starts = np.arange(5000, dtype=float)
    values = np.ones(len(starts)) if binary else starts * 0.1
    # Include an interval whose start is outside the view but whose end is inside.
    ends = starts + 1.0
    ends[10] = 25.0
    if binary:
        plot_states(axes, starts, values, "#168B82", ends=ends)
    else:
        plot_bars(axes, starts, ends, values, "#168B82")
    collection = axes.collections[0]
    original = [path.vertices.copy() for path in collection.get_paths()]
    drawn = []
    real_draw = PolyCollection.draw

    def record_draw(self, renderer):
        if self is collection:
            drawn.append([path.vertices.copy() for path in self.get_paths()])
        return real_draw(self, renderer)

    monkeypatch.setattr(PolyCollection, "draw", record_draw)
    axes.set_xlim(20.25, 22.75)
    canvas.draw()
    if binary:
        # All these states touch: one opaque rectangle fills exactly the same
        # presence area, with all original intervals retained below.
        assert len(drawn[-1]) == 1
        assert drawn[-1][0][:, 0].min() == 0.0
        assert drawn[-1][0][:, 0].max() == 5000.0
    else:
        assert len(drawn[-1]) == 4  # Three nearby intervals and the straddling interval.
        expected = [
            vertices
            for vertices in original
            if vertices[:, 0].max() >= 20.25 and vertices[:, 0].min() <= 22.75
        ]
        np.testing.assert_array_equal(drawn[-1], expected)
    np.testing.assert_array_equal([path.vertices for path in collection.get_paths()], original)
    axes.set_xlim(-1.0, 5001.0)
    canvas.draw()
    assert len(drawn[-1]) == (1 if binary else len(starts))
    # Rasterized exports must keep working through the optimized draw method.
    destination = BytesIO()
    figure.savefig(destination, format="pdf")
    assert destination.getvalue().startswith(b"%PDF")
    np.testing.assert_array_equal([path.vertices for path in collection.get_paths()], original)


def test_failed_render_does_not_discard_offscreen_data(monkeypatch):
    figure = Figure()
    canvas = FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    starts = np.arange(1000, dtype=float)
    collection = plot_bars(axes, starts, starts + 1.0, starts, "#168B82")
    original = collection.get_paths()
    axes.set_xlim(10.0, 15.0)

    def fail_draw(*_):
        raise RuntimeError("Renderer unavailable")

    monkeypatch.setattr(PolyCollection, "draw", fail_draw)
    with pytest.raises(RuntimeError, match="Renderer unavailable"):
        canvas.draw()
    assert collection.get_paths() is original
    assert len(collection.get_paths()) == len(starts)


def assert_dense_pixels_and_real_gap(canvas, axes):
    rgb = np.asarray(canvas.buffer_rgba())[:, :, :3].astype(int)
    colored = (rgb[:, :, 2] > rgb[:, :, 0] + 20) & (rgb[:, :, 1] > rgb[:, :, 0] + 10)
    left, right = int(np.ceil(axes.bbox.x0)), int(np.floor(axes.bbox.x1))
    top, bottom = rgb.shape[0] - int(axes.bbox.y1), rgb.shape[0] - int(axes.bbox.y0)
    visible = colored[top:bottom]
    assert np.count_nonzero(visible[:, left:right].any(axis=0)) > (right - left) * 0.8
    gap = int(axes.transData.transform((55.0, 0.0))[0])
    assert not visible[:, gap - 2 : gap + 3].any(), "Missing observations remain visibly empty"


@pytest.mark.parametrize("persistent", [False, True])
def test_dense_rendering_retains_peaks_gaps_original_intervals_and_export_geometry(
    monkeypatch, persistent
):
    figure = Figure(figsize=(8, 3), dpi=100)
    canvas = FigureCanvasAgg(figure)
    canvas._result_dense_display = persistent
    axes = figure.add_subplot()
    starts = np.arange(16000, dtype=float) / 100
    ends = starts + 0.01
    values = 30 * np.sin(starts)
    values[5000:6000] = np.nan
    values[2000], values[10000] = 900, -700
    ends[0], values[0] = 8.0, 15.0
    collection = plot_bars(axes, starts, ends, values, "#168B82")
    axes.set_xlim(0, 160)
    canvas.draw()
    reference = np.asarray(canvas.buffer_rgba()).copy()
    original = collection.get_paths()
    vertices = np.array([path.vertices.copy() for path in original])
    drawn = []
    real_draw = PolyCollection.draw

    def record_draw(self, renderer):
        if self is collection:
            drawn.append(np.array([path.vertices.copy() for path in self.get_paths()]))
        return real_draw(self, renderer)

    monkeypatch.setattr(PolyCollection, "draw", record_draw)
    canvas.time_scrolling = canvas.panning = True
    canvas.draw()
    preview = drawn[-1]
    if persistent:
        # A settled Results plot must retain the visible peaks/density of the
        # moving plot, rather than rasterizing thin individual bars away.
        np.testing.assert_array_equal(canvas.buffer_rgba(), reference)
        assert_dense_pixels_and_real_gap(canvas, axes)
    assert 0 < len(preview) <= np.ceil(axes.bbox.width) + 1
    assert preview[:, :, 1].max() == 900 and preview[:, :, 1].min() == -700
    assert any(np.array_equal(path, vertices[0]) for path in preview)
    assert not any(path[:, 0].min() < 56 and path[:, 0].max() > 54 for path in preview)
    assert collection.get_paths() is original
    np.testing.assert_array_equal([path.vertices for path in original], vertices)
    destination = BytesIO()
    figure.savefig(destination, format="png")
    assert len(drawn[-1]) == len(original), "Exports retain all original visible bars"
    canvas.time_scrolling = canvas.panning = False
    canvas.draw()
    np.testing.assert_array_equal(canvas.buffer_rgba(), reference)
    axes.set_xlim(40.0, 41.0)
    canvas.draw()
    resolved = [path for path in vertices if path[:, 0].max() >= 40.0 and path[:, 0].min() <= 41.0]
    np.testing.assert_array_equal(drawn[-1], resolved)
    assert collection.get_paths() is original
    axes.set_xlim(0, 160)
    canvas.time_scrolling = canvas.panning = True

    def fail(*_):
        raise RuntimeError("preview render failed")

    monkeypatch.setattr(PolyCollection, "draw", fail)
    with pytest.raises(RuntimeError, match="preview render failed"):
        canvas.draw()
    assert collection.get_paths() is original


@pytest.mark.parametrize("reverse", [False, True])
def test_interval_lookup_preserves_native_pixels_for_sorted_and_unsorted_data(monkeypatch, reverse):
    figure = Figure()
    canvas = FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    starts = np.arange(15000, dtype=float)
    if reverse:
        starts = starts[::-1]
    collection = plot_bars(axes, starts, starts + 0.9, np.sin(starts) * 30, "#168B82")
    axes.set_xlim(400.2, 530.4)
    canvas.draw()
    actual = np.asarray(canvas.buffer_rgba()).copy()
    monkeypatch.setattr(
        collection, "draw", lambda renderer: PolyCollection.draw(collection, renderer)
    )
    canvas.draw()
    np.testing.assert_array_equal(canvas.buffer_rgba(), actual)


def test_changing_active_table_keeps_graph_zoom_settings_and_cached_row_selection(window):
    frame = pd.DataFrame({"time": [0.0, 1.0, 2.0], "metric": [2.0, 3.0, 4.0]})
    window.analyzed({"quantifications": {"tremor": frame, "pulse_rate": frame.copy()}})
    window.result_tabs.setCurrentIndex(1)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.Checked)
    app = QApplication.instance()
    app.processEvents()
    axes = tuple(window.figure.axes)
    axes[0].set_xlim(0.25, 1.75)
    axes[0].set_ylabel("Custom label")
    selection = window._result_state._detail_selections
    for table in ("quantifications/pulse_rate", "quantifications/tremor"):
        window.dataset.setCurrentText(table)
        app.processEvents()
        assert tuple(window.figure.axes) == axes
        assert axes[0].get_xlim() == pytest.approx((0.25, 1.75))
        assert axes[0].get_ylabel() == "Custom label"
        assert window._result_state._detail_selections is selection
        pd.testing.assert_frame_equal(window._result_state.active_frame, frame)
    # New results with identical metric names must invalidate the old plot.
    replacement = frame.assign(metric=[100.0, 200.0, 300.0])
    window.analyzed({"quantifications": {"tremor": replacement}})
    assert window.figure.axes[0] is not axes[0]
    np.testing.assert_array_equal(
        [path.vertices[1, 1] for path in window.figure.axes[0].collections[0].get_paths()],
        replacement.metric,
    )


def test_hidden_graphs_defer_paint_then_display_and_export_fresh_results(window, monkeypatch):
    frame = pd.DataFrame({"time": [0.0, 1.0, 2.0], "metric": [2.0, 3.0, 4.0]})
    paints = []
    real_draw = window.canvas.draw

    def record_draw():
        paints.append(True)
        return real_draw()

    monkeypatch.setattr(window.canvas, "draw", record_draw)
    window.analyzed({"quantifications": {"tremor": frame}})
    QApplication.instance().processEvents()
    assert window.result_tabs.currentIndex() == 0
    assert not window.canvas.isVisible() and not paints
    # Explicit export remains available from Overview before Graphs is visited.
    destination = BytesIO()
    window.figure.savefig(destination, format="png")
    assert destination.getvalue().startswith(b"\x89PNG")
    paints.clear()
    window.result_tabs.setCurrentIndex(1)
    QApplication.instance().processEvents()
    assert window.canvas.isVisible() and paints
    np.testing.assert_array_equal(
        [path.vertices[1, 1] for path in window.figure.axes[0].collections[0].get_paths()],
        frame.metric,
    )
    paints.clear()
    window.result_tabs.setCurrentIndex(0)
    QApplication.instance().processEvents()
    window.canvas.draw_idle()
    QApplication.instance().processEvents()
    assert not paints


def test_repeated_axis_sync_and_selection_do_not_repaint_unchanged_ruler(window, monkeypatch):
    frame = pd.DataFrame({"time": [0.0, 1.0, 2.0], "metric": [2.0, 3.0, 4.0]})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    QApplication.instance().processEvents()
    window.canvas.draw()
    ruler = window.time_axis
    ruler.synchronize()
    ruler.set_selection(1.0, "Selected row")
    redraws = []
    monkeypatch.setattr(ruler, "draw_idle", lambda: redraws.append(True))
    for _ in range(20):
        ruler.synchronize()
        ruler.set_selection(1.0, "Selected row")
    assert not redraws
    old_axes = window.figure.axes[0]
    old_axes.set_xlim(0.5, 1.5)
    assert redraws and ruler.axes.get_xlim() == pytest.approx((0.5, 1.5))
    redraws.clear()
    new_axes = Figure().add_subplot()
    ruler.bind(new_axes)
    redraws.clear()
    old_axes.set_xlim(0.0, 2.0)
    assert not redraws  # Old graph callbacks were disconnected.
    new_axes.set_xlim(10.0, 20.0)
    assert ruler.axes.get_xlim() == pytest.approx((10.0, 20.0)) and redraws


@pytest.mark.parametrize("mode", [0, 1])
def test_adding_series_reuses_existing_paths_settings_and_shared_clock(window, mode):
    tremor = pd.DataFrame({"time": np.arange(2000.0), "metric": np.arange(2000.0) + 2.0})
    gait = pd.DataFrame({"time": [0.0, 1000.0, 2000.0], "metric": [20.0, 30.0, 40.0]})
    window.analyzed(
        {"quantifications": {"tremor": tremor, "gait": {"unfiltered": gait}, "pulse_rate": gait}}
    )
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for (name, _metric), item in window._result_state._series_items.items():
        item.setCheckState(0, Qt.Checked if name == "quantifications/tremor" else Qt.Unchecked)
    window.result_series.blockSignals(False)
    window.result_graph_view.setCurrentIndex(mode)
    window.plot()
    app = QApplication.instance()
    app.processEvents()
    original = window.figure.axes[0]
    paths = original.collections[0].get_paths()
    original.set_ylabel("Custom label")
    original.set_ylim(0.0, 2500.0)
    original.set_xlim(100.0, 500.0)
    # Add before and after the retained axis in module order. Paths stay exact
    # and sharing still works after axes are removed/re-added to the Figure.
    for name in ("quantifications/gait/unfiltered", "quantifications/pulse_rate"):
        window._result_state._series_items[name, "metric"].setCheckState(0, Qt.Checked)
        app.processEvents()
        retained = next(
            ax for ax in window.figure.axes if ax._paradigma_dataset == "quantifications/tremor"
        )
        assert retained is original
        assert retained.collections[0].get_paths() is paths
        assert retained.get_ylabel() == "Custom label"
        assert retained.get_ylim() == (0.0, 2500.0)
        assert all(ax.get_xlim() == (100.0, 500.0) for ax in window.figure.axes)
        assert [
            (ax._paradigma_dataset, ax._paradigma_metric) for ax in window.figure.axes
        ] == window.selected_result_series()
    original.set_xlim(200.0, 400.0)
    assert all(ax.get_xlim() == (200.0, 400.0) for ax in window.figure.axes)
    assert window.time_axis.axes.get_xlim() == (200.0, 400.0)
    output = BytesIO()
    window.figure.savefig(output, format="png")
    assert output.getvalue().startswith(b"\x89PNG")
    assert original.collections[0].get_paths() is paths
    window.plot_toolbar.home()
    assert window.figure.axes[0].get_xlim()[0] <= 0.0
    assert window.figure.axes[0].get_xlim()[1] >= 2000.0
    window._result_state._series_items["quantifications/gait/unfiltered", "metric"].setCheckState(
        0, Qt.Unchecked
    )
    original.set_xlim(250.0, 450.0)
    assert all(ax.get_xlim() == (250.0, 450.0) for ax in window.figure.axes)


def select_shared_owner(window, owner_index):
    items = list(window._result_state._series_items.values())
    for item in items:
        item.setCheckState(0, Qt.Unchecked)
    items[owner_index].setCheckState(0, Qt.Checked)
    for item in items:
        item.setCheckState(0, Qt.Checked)
    QApplication.instance().processEvents()


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
@pytest.mark.parametrize("owner_index", [0, -1])
def test_removing_shared_axis_owner_retains_artists_settings_and_navigation(
    window, mode, owner_index
):
    times = np.arange(0.0, 3 * 86400, 60.0)
    frame = pd.DataFrame(
        {"time": times, **{f"metric_{i}": 2 + np.sin(times / 100) for i in range(3)}}
    )
    unchanged = frame.copy(deep=True)
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_graph_view.setCurrentIndex(mode)
    app = QApplication.instance()
    app.processEvents()
    select_shared_owner(window, owner_index)
    # Remove successive owners, including the final axis, to cover singleton
    # sharing, new owners, empty selections and subsequent reconstruction.
    while window.selected_result_series():
        owner = window._graph_state._result_shared_axes
        survivors = [ax for ax in window.figure.axes if ax is not owner]
        paths = [ax.collections[0].get_paths() for ax in survivors]
        full = tuple(window.result_time_scroll._full_limits)
        low, high = owner.get_xlim()
        zoom = low + (high - low) * 0.2, low + (high - low) * 0.7
        owner.set_xlim(*zoom)
        for ax in survivors:
            ax.set_ylim(-2.0, 5.0)
            ax.set_ylabel("Custom label")
        key = owner._paradigma_dataset, owner._paradigma_metric
        window._result_state._series_items[key].setCheckState(0, Qt.Unchecked)
        app.processEvents()
        if not survivors:
            assert window._graph_state._result_shared_axes is None
            continue
        assert window.figure.axes == survivors
        assert window._graph_state._result_shared_axes in survivors
        assert all(not ax.get_shared_x_axes().joined(ax, owner) for ax in survivors)
        for axis in ("major", "minor"):
            assert getattr(survivors[0].xaxis, axis).locator.axis.axes in survivors
            assert getattr(survivors[0].xaxis, axis).formatter.axis.axes in survivors
        for ax, original in zip(survivors, paths, strict=True):
            assert ax.collections[0].get_paths() is original
            assert ax.get_ylabel() == "Custom label" and ax.get_ylim() == (-2.0, 5.0)
            assert not ax.get_autoscaley_on()
            np.testing.assert_allclose(ax.get_xlim(), zoom)
        survivors[-1].set_xlim(zoom[0], zoom[0] + (zoom[1] - zoom[0]) / 2)
        assert all(ax.get_xlim() == survivors[-1].get_xlim() for ax in survivors)
        np.testing.assert_allclose(window.time_axis.axes.get_xlim(), survivors[-1].get_xlim())
        window.plot_toolbar.home()
        np.testing.assert_allclose(survivors[0].get_xlim(), full)
        window.plot_toolbar.back()
        np.testing.assert_allclose(survivors[0].get_xlim(), zoom)
    next(iter(window._result_state._series_items.values())).setCheckState(0, Qt.Checked)
    app.processEvents()
    assert (
        len(window.figure.axes) == 1
        and window._graph_state._result_shared_axes in window.figure.axes
    )
    pd.testing.assert_frame_equal(frame, unchanged)


def test_presence_draw_union_preserves_pixels_real_gaps_and_every_original_interval():
    figure = Figure(figsize=(8, 2), dpi=100)
    canvas = FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    starts = np.array([0.0, 0.25, 1.0, 1.5, 5.0, 5.75, 10.0])
    ends = np.array([0.25, 1.0, 1.5, 2.0, 5.75, 7.0, 10.5])
    plot_states(axes, starts, np.ones(len(starts)), "#168B82", ends=ends)
    collection = axes.collections[0]
    paths = collection.get_paths()
    merged = collection._render_paths
    assert len(paths) == 7 and len(merged) == 3
    np.testing.assert_array_equal(
        [[p.vertices[:, 0].min(), p.vertices[:, 0].max()] for p in merged],
        [[0.0, 2.0], [5.0, 7.0], [10.0, 10.5]],
    )
    canvas.draw()
    union_pixels = np.asarray(canvas.buffer_rgba()).copy()
    collection._render_paths = paths
    canvas.draw()
    np.testing.assert_array_equal(canvas.buffer_rgba(), union_pixels)
    assert collection.get_paths() is paths


def test_row_markers_reuse_pixels_but_changed_limits_redraw(window, monkeypatch):
    frame = pd.DataFrame({"time": np.arange(1000.0), "metric": np.arange(1000.0) / 10})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    app = QApplication.instance()
    app.processEvents()
    window.canvas.draw()
    draws = []
    original = PolyCollection.draw

    def record(collection, renderer):
        draws.append(collection)
        return original(collection, renderer)

    monkeypatch.setattr(PolyCollection, "draw", record)
    for row in (10, 30, 50):
        window.result_table.setCurrentIndex(window.result_table.model().index(row, 0))
        app.processEvents()
    assert not draws
    assert window._graph_state._result_selection_artists
    optimized = np.asarray(window.canvas.buffer_rgba()).copy()
    window.canvas.draw()
    np.testing.assert_array_equal(np.asarray(window.canvas.buffer_rgba()), optimized)
    draws.clear()
    window.figure.axes[0].set_xlim(5, 20)
    window.highlight_result_row()
    app.processEvents()
    assert draws
    stream = BytesIO()
    window.figure.savefig(stream, format="png")
    assert stream.getvalue().startswith(b"\x89PNG")
    assert window._graph_state._result_selection_artists  # Export does not discard selection.


def test_discarding_hidden_results_releases_previously_painted_axes(window):
    import gc
    import weakref

    frame = pd.DataFrame({"time": np.arange(2000.0), "metric": 2 + np.arange(2000.0)})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    QApplication.instance().processEvents()
    assert window.canvas._painted_axes
    references = [weakref.ref(ax) for ax in window.figure.axes]
    window.result_tabs.setCurrentIndex(0)
    QApplication.instance().processEvents()
    window.clear_results()
    gc.collect()
    assert all(reference() is None for reference in references)
    assert not window.canvas._painted_axes


def test_discarded_results_release_render_and_sensor_context_views(window):
    from conftest import wait_for_previews

    frame = pd.DataFrame({"time": np.arange(800.0) / 100.0, "gyroscope_x": np.ones(800)})
    window.loaded(("sensor.csv", frame))
    wait_for_previews(window)
    window._result_state.provenance = {"settings": {"skip_preparation": True}}
    output = pd.DataFrame({"time": [0.0, 4.0], "tremor_power": [1.0, 2.0]})
    window.analyzed({"quantifications": {"tremor": output}})
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    window.inspect_sensor_context()
    assert window._sensor_state.sensor_frame is not None
    assert window._result_state._bar_bounds and window._graph_state._result_shared_axes is not None
    window.clear_results()
    assert window._sensor_state.sensor_frame is None and window._result_state.display_frame is None
    assert window.sensor_table.model() is None
    assert not window.sensor_figure.axes and not window.figure.axes
    assert (
        not window._result_state._bar_bounds and not window._graph_state._result_selection_artists
    )
    assert window._graph_state._result_shared_axes is None
    # Clearing outputs preserves the loaded source for subsequent analyses.
    assert window._input_state.frame is frame
