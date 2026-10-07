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

from paradigma_desktop.app import MainWindow
from paradigma_desktop.plotting import plot_bars, plot_states


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = MainWindow(history_dir=tmp_path)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    app.processEvents()


@pytest.mark.parametrize("binary", [False, True])
def test_zoom_renders_only_intersecting_intervals_and_restores_all_original_values(binary, monkeypatch):
    figure = Figure()
    canvas = FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    starts = np.arange(5000, dtype=float)
    values = np.ones(len(starts)) if binary else starts * .1
    # Include an interval whose start is outside the view but whose end is inside.
    ends = starts + 1.
    ends[10] = 25.
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
    assert len(drawn[-1]) == 4  # Three nearby intervals and the straddling interval.
    expected = [vertices for vertices in original
                if vertices[:, 0].max() >= 20.25 and vertices[:, 0].min() <= 22.75]
    np.testing.assert_array_equal(drawn[-1], expected)
    np.testing.assert_array_equal([path.vertices for path in collection.get_paths()], original)
    axes.set_xlim(-1., 5001.)
    canvas.draw()
    assert len(drawn[-1]) == len(starts)
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
    collection = plot_bars(axes, starts, starts + 1., starts, "#168B82")
    original = collection.get_paths()
    axes.set_xlim(10., 15.)

    def fail_draw(*_):
        raise RuntimeError("Renderer unavailable")

    monkeypatch.setattr(PolyCollection, "draw", fail_draw)
    with pytest.raises(RuntimeError, match="Renderer unavailable"):
        canvas.draw()
    assert collection.get_paths() is original
    assert len(collection.get_paths()) == len(starts)


def test_changing_active_table_keeps_graph_zoom_settings_and_cached_row_selection(window):
    frame = pd.DataFrame({"time": [0., 1., 2.], "metric": [2., 3., 4.]})
    window.analyzed({"quantifications": {"tremor": frame, "pulse_rate": frame.copy()}})
    window.result_tabs.setCurrentIndex(1)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    app = QApplication.instance()
    app.processEvents()
    axes = tuple(window.figure.axes)
    axes[0].set_xlim(.25, 1.75)
    axes[0].set_ylabel("Custom label")
    selection = window._detail_selections
    for table in ("quantifications/pulse_rate", "quantifications/tremor"):
        window.dataset.setCurrentText(table)
        app.processEvents()
        assert tuple(window.figure.axes) == axes
        assert axes[0].get_xlim() == pytest.approx((.25, 1.75))
        assert axes[0].get_ylabel() == "Custom label"
        assert window._detail_selections is selection
        pd.testing.assert_frame_equal(window.active_frame, frame)
    # New results with identical metric names must invalidate the old plot.
    replacement = frame.assign(metric=[100., 200., 300.])
    window.analyzed({"quantifications": {"tremor": replacement}})
    assert window.figure.axes[0] is not axes[0]
    np.testing.assert_array_equal([path.vertices[1, 1] for path in window.figure.axes[0].collections[0].get_paths()], replacement.metric)


def test_hidden_graphs_defer_paint_then_display_and_export_fresh_results(window, monkeypatch):
    frame = pd.DataFrame({"time": [0., 1., 2.], "metric": [2., 3., 4.]})
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
    np.testing.assert_array_equal([path.vertices[1, 1] for path in window.figure.axes[0].collections[0].get_paths()], frame.metric)
    paints.clear()
    window.result_tabs.setCurrentIndex(0)
    QApplication.instance().processEvents()
    window.canvas.draw_idle()
    QApplication.instance().processEvents()
    assert not paints


def test_repeated_axis_sync_and_selection_do_not_repaint_unchanged_ruler(window, monkeypatch):
    frame = pd.DataFrame({"time": [0., 1., 2.], "metric": [2., 3., 4.]})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    QApplication.instance().processEvents()
    window.canvas.draw()
    ruler = window.time_axis
    ruler.synchronize()
    ruler.set_selection(1., "Selected row")
    redraws = []
    monkeypatch.setattr(ruler, "draw_idle", lambda: redraws.append(True))
    for _ in range(20):
        ruler.synchronize()
        ruler.set_selection(1., "Selected row")
    assert not redraws
    old_axes = window.figure.axes[0]
    old_axes.set_xlim(.5, 1.5)
    assert redraws and ruler.axes.get_xlim() == pytest.approx((.5, 1.5))
    redraws.clear()
    new_axes = Figure().add_subplot()
    ruler.bind(new_axes)
    redraws.clear()
    old_axes.set_xlim(0., 2.)
    assert not redraws  # Old graph callbacks were disconnected.
    new_axes.set_xlim(10., 20.)
    assert ruler.axes.get_xlim() == pytest.approx((10., 20.)) and redraws
