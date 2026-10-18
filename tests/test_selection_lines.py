"""The linked Results selector keeps one dash pattern through every graph gap."""

from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.transforms import Bbox, TransformedBbox
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_studio.plotting import time_selection_line
from paradigma_studio.selection_lines import TimeSelectionBridges


def assert_gap_is_marked(window):
    upper, lower = sorted(window.figure.axes, key=lambda ax: ax.bbox.y0, reverse=True)[:2]
    line = next(line for line in upper.lines if line.get_gid() == "selected-result-time")
    x = round(upper.get_xaxis_transform().transform((line.get_xdata()[0], 0))[0])
    pixels = np.asarray(window.canvas.buffer_rgba())
    top = pixels.shape[0] - int(upper.bbox.y0) + 2
    bottom = pixels.shape[0] - int(lower.bbox.y1) - 2
    gap = pixels[top:bottom, x - 2 : x + 3, :3]
    # A dashed line has empty pixels within each dash cycle, but cannot leave
    # the entire gutter blank as independent, Axes-clipped selectors did.
    assert bottom - top > 10
    assert np.count_nonzero(np.any(gap < 200, axis=(1, 2))) > (bottom - top) / 5


@pytest.mark.parametrize("view", range(4))
@pytest.mark.parametrize("pixel_ratio", [1, 2])
def test_results_time_selector_connects_graphs_without_changing_values_or_limits(
    window, view, pixel_ratio
):
    times = np.arange(0, 3 * 86400, 60.0)
    frame = pd.DataFrame(
        {"time": times, "metric_a": 2 + np.sin(times / 500), "metric_b": times / 10000}
    )
    original = frame.copy(deep=True)
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.result_graph_view.setCurrentIndex(view)
    window.plot()
    window.canvas._set_device_pixel_ratio(pixel_ratio)
    app = QApplication.instance()
    app.processEvents()
    axes = window.figure.axes
    limits = [(ax.get_xlim(), ax.get_ylim()) for ax in axes]
    if view == 3:
        window._result_state._profile_selection = (
            axes[0]._paradigma_dataset,
            axes[0]._paradigma_metric,
            12 * 3600 + 900,
        )
    else:
        model = window.result_table.model()
        window.result_table.setCurrentIndex(model.index(model.rowCount() // 2, 0))
    window.highlight_result_row()
    window.canvas.draw()
    assert len(axes) >= 2
    assert_gap_is_marked(window)
    assert [(ax.get_xlim(), ax.get_ylim()) for ax in axes] == limits
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


def selector_stack(*, linked, dpi):
    figure = Figure(figsize=(4, 5), dpi=dpi)
    FigureCanvasAgg(figure)
    for bottom, height in ((0.08, 0.21), (0.4, 0.21), (0.72, 0.2)):
        ax = figure.add_axes((0.12, bottom, 0.8, height))
        ax._paradigma_dataset = "quantifications/tremor"
        ax.set_axis_off()
        ax.set_xlim(0, 10)
        if linked:
            time_selection_line(ax, 5.0, linked=True)
    if linked:
        TimeSelectionBridges(figure, figure.axes[0].lines[0])
    else:
        # A single native stroke is the independent reference for dash phase
        # throughout the entire stack, including plot/gutter boundaries.
        line = Line2D(
            [0.52, 0.52],
            [0.08, 0.92],
            transform=figure.transFigure,
            color="#465B73",
            linewidth=1.1,
            linestyle=(0, (3, 3)),
            alpha=0.75,
        )
        line.set_clip_box(
            TransformedBbox(Bbox.from_extents(0.12, 0.08, 0.92, 0.92), figure.transFigure)
        )
        figure.add_artist(line)
    return figure


@pytest.mark.parametrize("dpi", [100, 200])
@pytest.mark.parametrize("changed", ["initial", "resize", "pan"])
def test_linked_dash_phase_matches_one_native_stroke_across_plots_and_gaps(dpi, changed):
    actual, expected = (selector_stack(linked=linked, dpi=dpi) for linked in (True, False))
    if changed == "resize":
        for figure in (actual, expected):
            figure.set_size_inches(5.3, 6.2)
    elif changed == "pan":
        for figure in (actual, expected):
            for ax in figure.axes:
                ax.set_xlim(1, 11)
        expected.artists[0].set_xdata([0.44, 0.44])
    for figure in (actual, expected):
        figure.canvas.draw()
    np.testing.assert_array_equal(actual.canvas.buffer_rgba(), expected.canvas.buffer_rgba())
    for ax in actual.axes:
        np.testing.assert_array_equal(ax.lines[0].get_xdata(), [5, 5])
        np.testing.assert_array_equal(ax.lines[0].get_ydata(), [0, 1])
        np.testing.assert_array_equal(
            ax.dataLim.get_points(), [[np.inf, np.inf], [-np.inf, -np.inf]]
        )


def test_export_keeps_the_shared_dash_pattern_at_600_dpi_and_preserves_markers():
    actual, expected = (selector_stack(linked=linked, dpi=100) for linked in (True, False))
    images = []
    for figure in (actual, expected):
        destination = BytesIO()
        figure.savefig(destination, format="png", dpi=600)
        destination.seek(0)
        images.append(np.asarray(Image.open(destination)))
    np.testing.assert_array_equal(*images)
    # The gap artist must stay outside the Axes so its later figure-level draw
    # cannot cover selected-value points inside the plots, including exports.
    point = Line2D([5], [0.5], marker="o", markersize=14, markerfacecolor="white", zorder=8)
    actual.axes[1].add_artist(point)
    for dpi in (100, 600):
        destination = BytesIO()
        actual.savefig(destination, format="png", dpi=dpi)
        destination.seek(0)
        pixels = np.asarray(Image.open(destination))
        y, x = round(pixels.shape[0] * (1 - 0.505)), round(pixels.shape[1] * 0.52)
        np.testing.assert_array_equal(pixels[y, x, :3], [255, 255, 255])


def test_hidden_offscreen_and_single_graph_selectors_do_not_leave_gutter_pixels():
    figure = selector_stack(linked=True, dpi=100)
    for ax in figure.axes:
        ax.set_xlim(6, 10)
    figure.canvas.draw()
    assert np.asarray(figure.canvas.buffer_rgba()).min() == 255
    for ax in figure.axes:
        ax.set_xlim(0, 10)
        ax.lines[0].set_visible(False)
    figure.canvas.draw()
    assert np.asarray(figure.canvas.buffer_rgba()).min() == 255
    for ax in figure.axes[1:]:
        ax.remove()
    figure.axes[0].lines[0].set_visible(True)
    figure.canvas.draw()
    pixels = np.asarray(figure.canvas.buffer_rgba())
    assert pixels[: round(figure.bbox.height * 0.7), :, :3].min() == 255
    assert pixels.min() < 200
