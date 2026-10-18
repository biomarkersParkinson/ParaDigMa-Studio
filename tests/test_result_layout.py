"""Results keep one readable Y-axis column regardless of graph selection."""

from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.layout_engine import ConstrainedLayoutEngine
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from paradigma_studio.result_layout import ResultLayoutEngine
from paradigma_studio.theme import style_axes


@pytest.mark.parametrize("view", [0, 1, 2, 3], ids=["detailed", "30-minute", "day", "profile"])
def test_results_y_axis_position_stays_fixed_across_selections_views_and_window_sizes(window, view):
    times = np.r_[np.arange(0, 1800, 4), np.arange(86400, 88200, 4)]
    window.analyzed(
        {
            "classifications": {"tremor": pd.DataFrame({"time": times, "pred_tremor_checked": 1})},
            "quantifications": {
                "tremor": pd.DataFrame(
                    {
                        "time": times,
                        "tremor_power": np.linspace(0, 1000, len(times)),
                        "wide_metric": np.linspace(-20000, 20000, len(times)),
                    }
                )
            },
        }
    )
    window.result_tabs.setCurrentIndex(1)
    QApplication.instance().processEvents()
    window.canvas.draw()
    left = window.figure.axes[0].bbox.x0 / window.canvas.device_pixel_ratio
    window.result_graph_view.setCurrentIndex(view)
    presence = ("classifications/tremor", "pred_tremor_checked")
    power = ("quantifications/tremor", "tremor_power")
    wide = ("quantifications/tremor", "wide_metric")
    for size in ((960, 650), (1450, 920), (960, 650)):
        window.resize(*size)
        for selected in ((presence,), (presence, power, wide), (power,), (wide,), (presence,)):
            window.result_series.blockSignals(True)
            for key, item in window._result_state._series_items.items():
                item.setCheckState(0, Qt.Checked if key in selected else Qt.Unchecked)
            window.result_series.blockSignals(False)
            window.plot()
            QApplication.instance().processEvents()
            window.canvas.draw()
            window.time_axis.draw()
            renderer = window.canvas.get_renderer()
            for axes in window.figure.axes:
                position = axes.bbox.x0 / window.canvas.device_pixel_ratio
                assert position == pytest.approx(left, abs=0.1)
                labels = axes.yaxis.get_tightbbox(renderer)
                assert labels is None or labels.x0 >= 0
            plot_origin = window.canvas.mapToGlobal(QPoint(0, 0)).x()
            ruler_origin = window.time_axis.mapToGlobal(QPoint(0, 0)).x()
            ruler_left = window.time_axis.axes.bbox.x0 / window.time_axis.device_pixel_ratio
            assert ruler_origin + ruler_left == pytest.approx(plot_origin + left, abs=1)


@pytest.mark.parametrize("dpi", [100, 200, 600])
def test_fixed_results_label_column_scales_with_dpi_and_fits_signed_and_multiline_labels(dpi):
    figure = Figure(figsize=(6, 4), layout=ResultLayoutEngine())
    canvas = FigureCanvasAgg(figure)
    for row, ylabel in enumerate(("Range of motion", "Mean epoch median\nlog₁₀(power + 1)"), 1):
        axes = style_axes(figure, position=(2, 1, row))
        axes.plot([0, 1], [-20000, 20000])
        axes.set_ylabel(ylabel, fontsize=9)
    canvas.draw()
    live_positions = [axes.bbox.x0 / figure.dpi for axes in figure.axes]
    measured = []

    def measure(event):
        measured.append([axes.bbox.x0 / figure.dpi for axes in figure.axes])
        for axes in figure.axes:
            assert axes.yaxis.get_tightbbox(event.renderer).x0 >= 0

    canvas.mpl_connect("draw_event", measure)
    image = BytesIO()
    figure.savefig(image, format="png", dpi=dpi)
    assert image.getvalue().startswith(b"\x89PNG")
    assert measured and all(positions == pytest.approx(live_positions) for positions in measured)
    canvas.draw()
    assert [axes.bbox.x0 / figure.dpi for axes in figure.axes] == pytest.approx(live_positions)


@pytest.mark.parametrize("dpi", [100, 200])
def test_repeated_results_layout_reuses_geometry_and_matches_native_pixels(dpi, monkeypatch):
    from matplotlib.layout_engine import ConstrainedLayoutEngine

    figure = Figure(figsize=(7, 6), dpi=dpi, layout=ResultLayoutEngine())
    canvas = FigureCanvasAgg(figure)
    for row in range(1, 4):
        ax = style_axes(figure, position=(3, 1, row))
        ax.plot([0, 1], [-20000, 20000])
        ax.set_ylabel("Range of motion" if row == 1 else "Mean epoch\nmedian")
        ax.set_title(f"Metric {row}", loc="left")
    canvas.draw()
    solves = []
    original = ConstrainedLayoutEngine.execute

    def solve(self, fig):
        solves.append(fig)
        return original(self, fig)

    monkeypatch.setattr(ConstrainedLayoutEngine, "execute", solve)
    canvas.draw()
    actual = np.asarray(canvas.buffer_rgba()).copy()
    assert not solves
    figure.set_layout_engine(ResultLayoutEngine())
    canvas.draw()
    np.testing.assert_array_equal(canvas.buffer_rgba(), actual)
    assert solves == [figure]


@pytest.mark.parametrize("change", ["size", "dpi", "label", "ticks", "font", "export"])
def test_layout_recalculates_for_changed_geometry_and_exports(change, monkeypatch):
    from matplotlib.layout_engine import ConstrainedLayoutEngine

    figure = Figure(figsize=(7, 4), layout=ResultLayoutEngine())
    canvas = FigureCanvasAgg(figure)
    ax = style_axes(figure)
    ax.plot([0, 1], [0, 1])
    canvas.draw()
    solves = []
    original = ConstrainedLayoutEngine.execute
    monkeypatch.setattr(
        ConstrainedLayoutEngine,
        "execute",
        lambda self, fig: (solves.append(fig), original(self, fig))[1],
    )
    if change == "size":
        figure.set_size_inches(8, 5)
    elif change == "dpi":
        figure.set_dpi(200)
    elif change == "label":
        ax.set_ylabel("Changed\nlabel")
    elif change == "ticks":
        ax.set_ylim(-20000, 20000)
    elif change == "font":
        ax.yaxis.label.set_fontsize(18)
    else:
        figure.savefig(BytesIO(), format="png", dpi=600)
    if change != "export":
        canvas.draw()
    assert solves


@pytest.mark.parametrize("view", range(4))
@pytest.mark.parametrize("pixel_ratio", [1, 2])
def test_compatible_bar_rows_keep_native_pixels_when_different_metrics_are_selected(
    window, view, pixel_ratio
):
    times = np.arange(0, 3 * 86400, 60.0)
    frame = pd.DataFrame(
        {"time": times, **{f"metric_{i}": (2 + np.sin(times / 2000)) * (i + 1) for i in range(6)}}
    )
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    window.result_graph_view.setCurrentIndex(view)
    window.canvas._set_device_pixel_ratio(pixel_ratio)
    engine = window.figure.get_layout_engine()
    items = list(window._result_state._series_items.values())
    for selected in ((0, 1), (2, 3), (4, 5), (0, 5)):
        window.result_series.blockSignals(True)
        for index, item in enumerate(items):
            item.setCheckState(0, Qt.Checked if index in selected else Qt.Unchecked)
        window.result_series.blockSignals(False)
        window.plot()
        QApplication.instance().processEvents()
        actual = np.asarray(window.canvas.buffer_rgba()).copy()
        window.figure.set_layout_engine(ResultLayoutEngine())
        window.canvas.draw()
        np.testing.assert_array_equal(window.canvas.buffer_rgba(), actual)
        window.figure.set_layout_engine(engine)


def test_layout_and_text_caches_evict_old_geometry_and_release_all_entries():
    engine = ResultLayoutEngine()
    engine.MAX_LAYOUTS = 3
    engine.MAX_TEXT_SIZES = 16
    figure = Figure(figsize=(7, 4), layout=engine)
    canvas = FigureCanvasAgg(figure)
    axes = style_axes(figure)
    axes.plot([0, 1], [0, 1])
    for index in range(10):
        figure.set_size_inches(7 + index / 10, 4)
        axes.set_title(f"Heading {index}")
        canvas.draw()
        assert len(engine._positions) <= 3
        assert len(engine._text_sizes) <= 16
    engine.clear()
    assert not engine._positions and not engine._text_sizes
    canvas.draw()
    pixels = np.asarray(canvas.buffer_rgba()).copy()
    figure.set_layout_engine(ResultLayoutEngine())
    canvas.draw()
    np.testing.assert_array_equal(canvas.buffer_rgba(), pixels)


@pytest.mark.parametrize("view", range(4))
@pytest.mark.parametrize("pixel_ratio", [1, 2])
def test_first_layout_tick_reuse_matches_unmodified_native_solver(
    window, view, pixel_ratio, monkeypatch
):
    from matplotlib.axis import Axis

    class NativeResultsLayout(ResultLayoutEngine):
        def _native_layout(self, figure):
            return ConstrainedLayoutEngine.execute(self, figure)

    times = np.arange(0, 3 * 86400, 60.0)
    window._result_state.provenance = {
        "display_clock": {"origin": "2026-10-24T00:00+02:00", "timezone": "Europe/Amsterdam"}
    }
    window.analyzed(
        {
            "classifications": {
                "tremor": pd.DataFrame({"time": times, "pred_tremor_checked": times % 120 == 0})
            },
            "quantifications": {
                "tremor": pd.DataFrame(
                    {
                        "time": times,
                        "positive": 2 + np.sin(times / 2000),
                        "signed": np.linspace(-20000, 20000, len(times)),
                        "missing": np.nan,
                    }
                )
            },
        }
    )
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.result_graph_view.setCurrentIndex(view)
    window.plot()
    window.canvas._set_device_pixel_ratio(pixel_ratio)
    window.figure.axes[1].set_ylim(-1e8, 1e8)
    window.figure.axes[1].set_ylabel("Manual\nmultiline label")
    calls = {"x": [], "y": []}
    original = Axis._update_ticks

    def update(axis):
        if axis.axes.figure is window.figure:
            calls[axis.axis_name].append(axis)
        return original(axis)

    monkeypatch.setattr(Axis, "_update_ticks", update)
    window.figure.set_layout_engine(ResultLayoutEngine())
    window.canvas.draw()
    pixels = np.asarray(window.canvas.buffer_rgba()).copy()
    positions = [ax.get_position().bounds for ax in window.figure.axes]
    optimized = {name: len(values) for name, values in calls.items()}
    calls = {"x": [], "y": []}
    window.figure.set_layout_engine(NativeResultsLayout())
    window.canvas.draw()
    np.testing.assert_array_equal(window.canvas.buffer_rgba(), pixels)
    np.testing.assert_allclose(
        [ax.get_position().bounds for ax in window.figure.axes], positions, atol=1e-12
    )
    assert all(optimized[name] < len(calls[name]) for name in ("x", "y"))
    assert all(
        "_update_ticks" not in vars(axis)
        for ax in window.figure.axes
        for axis in (ax.xaxis, ax.yaxis)
    )


def test_impossible_layout_cache_shape_skips_preflight_measurements(monkeypatch):
    engine = ResultLayoutEngine()
    figure = Figure(figsize=(7, 4), layout=engine)
    canvas = FigureCanvasAgg(figure)
    figure.add_subplot().plot([0, 1], [0, 1])
    events = []
    key = engine._layout_key
    solve = ConstrainedLayoutEngine.execute
    monkeypatch.setattr(engine, "_layout_key", lambda fig: (events.append("key"), key(fig))[1])
    monkeypatch.setattr(
        ConstrainedLayoutEngine,
        "execute",
        lambda self, fig: (events.append("native"), solve(self, fig))[1],
    )
    canvas.draw()
    assert events == ["native", "key"]
    events.clear()
    canvas.draw()
    assert events == ["key"]
    events.clear()
    figure.set_size_inches(8, 5)
    canvas.draw()
    assert events == ["native", "key"]


def test_layout_tick_adapter_restores_original_override_after_failure(monkeypatch):
    engine = ResultLayoutEngine()
    figure = Figure(figsize=(7, 4), layout=engine)
    FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    axes._paradigma_dataset = "dataset"
    axes.tick_params(axis="x", which="both", labelbottom=False, labeltop=False)
    axes.xaxis.label.set_visible(False)
    axes.xaxis.offsetText.set_visible(False)
    original = axes.xaxis._update_ticks
    calls = []

    def override():
        calls.append(True)
        return original()

    axes.xaxis._update_ticks = override

    def fail(self, fig):
        assert axes.xaxis._update_ticks() is axes.xaxis._update_ticks()
        raise RuntimeError("layout failed")

    monkeypatch.setattr(ConstrainedLayoutEngine, "execute", fail)
    with pytest.raises(RuntimeError, match="layout failed"):
        canvas = figure.canvas
        canvas.draw()
    assert axes.xaxis._update_ticks is override and len(calls) == 1


def test_export_uses_unmodified_native_layout_even_for_hidden_results_ticks(monkeypatch):
    import paradigma_studio.result_layout as layout

    figure = Figure(figsize=(4, 3), layout=ResultLayoutEngine())
    FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    axes._paradigma_dataset = "dataset"
    axes.tick_params(axis="x", which="both", labelbottom=False, labeltop=False)
    axes.xaxis.label.set_visible(False)
    axes.xaxis.offsetText.set_visible(False)
    monkeypatch.setattr(
        layout, "_layout_tick_update", lambda axis: pytest.fail("Export memoized ticks")
    )
    figure.savefig(BytesIO(), format="png", dpi=600)
