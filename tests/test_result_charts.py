"""Continuous result bars, autoscaling and module chart headings."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from conftest import bar_starts, bar_values, select_plot_metric
from matplotlib.backend_bases import MouseEvent
from matplotlib.figure import Figure
from PySide6.QtCore import Qt

from paradigma_studio.plotting import plot_bars


def test_continuous_bars_show_exact_values_leave_missing_gaps_and_retain_zero(
    window, tremor_outputs
):
    result = tremor_outputs
    original = deepcopy(result)
    window.analyzed(result)
    select_plot_metric(window, "quantifications/tremor", "tremor_power")
    axis = next(ax for ax in window.figure.axes if ax._paradigma_metric == "tremor_power")
    assert not axis.lines
    np.testing.assert_allclose(bar_values(axis), np.log10([3.0, 6.0]), rtol=1e-12)
    np.testing.assert_allclose(bar_starts(axis), [0.0, 8.0], atol=1e-12)
    assert not any(path.contains_point((6.0, 0.5)) for path in axis.collections[0].get_paths())
    axis.set_xlim(8.5, 9.5)
    window.canvas.draw()
    assert axis.collections[0].get_paths()[1].contains_point((9.0, 0.5))
    assert axis.get_ylabel() == "log₁₀(power + 1)"
    pd.testing.assert_frame_equal(
        result["quantifications"]["tremor"], original["quantifications"]["tremor"]
    )
    figure = Figure()
    axes = figure.add_subplot()
    plot_bars(axes, [0.0, 1.0, 2.0], [1.0, 2.0, 3.0], [-2.0, 0.0, np.nan], "#477DA3")
    np.testing.assert_array_equal(bar_values(axes), [-2.0, 0.0])
    assert (
        len(axes.collections[1].get_segments()) == 1
    )  # Actual zero stays distinguishable from missing.


def test_automatic_bar_scaling_follows_visible_values_without_hiding_extremes_or_overriding_manual_limits(
    window,
):
    frame = pd.DataFrame({"time": [0.0, 4.0, 8.0, 12.0], "tremor_power": [2.0, 3.0, 200.0, np.nan]})
    window.analyzed({"quantifications": {"tremor": frame}})
    axes = window.figure.axes[0]
    assert axes.get_ylim() == pytest.approx((0.0, np.log10(201.0) * 1.08))
    axes.set_xlim(0.5, 7.5)
    assert axes.get_ylim() == pytest.approx((0.0, np.log10(4.0) * 1.08))
    axes.set_xlim(8.5, 9.0)
    assert axes.get_ylim() == pytest.approx((0.0, np.log10(201.0) * 1.08))
    axes.set_ylim(-10.0, 500.0)
    axes.set_xlim(0.5, 7.5)
    assert axes.get_ylim() == (-10.0, 500.0)
    panel = window.plot_toolbar.settings
    panel.read_axes()
    panel.bounds["y"][0].setChecked(True)
    panel.apply()
    assert axes.get_ylim() == pytest.approx((0.0, np.log10(4.0) * 1.08))
    axes.set_xlim(12.0, 14.0)
    assert axes.get_ylim() == (0.0, 1.0)  # A missing bar never retains the preceding extreme.
    np.testing.assert_allclose(bar_values(axes), np.log10([3.0, 4.0, 201.0]), rtol=1e-12)
    pd.testing.assert_frame_equal(window._result_state.tables["quantifications/tremor"], frame)


def test_detailed_power_keeps_narrow_peaks_visible_and_marks_transformed_selected_value(window):
    from types import SimpleNamespace

    frame = pd.DataFrame({"time": [0.0, 100000.0, 200000.0], "tremor_power": [0.0, 3500.0, 1100.0]})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    window.canvas.draw()
    axes = window.figure.axes[0]
    peak = np.log10(3501.0)
    assert axes.get_ylim() == pytest.approx((0, peak * 1.08))
    assert len(axes.collections[0].get_paths()) == 3  # Zero is retained too.
    x, y = axes.transData.transform((100002.0, peak * 0.8))
    image = np.asarray(window.canvas.buffer_rgba())
    row, column = round(image.shape[0] - y), round(x)
    assert image[row - 2 : row + 3, column - 2 : column + 3, :3].min() < 190
    limits = axes.get_ylim()
    window.graph_clicked(SimpleNamespace(inaxes=axes, xdata=100002.0))
    marker = next(
        artist
        for artist in window._graph_state._result_selection_artists
        if artist.get_gid() == "selected-result-point"
    )
    assert marker.get_ydata()[0] == pytest.approx(peak)
    assert axes.get_ylim() == limits
    pd.testing.assert_frame_equal(
        window._result_state.tables["quantifications/tremor"], frame, check_exact=True
    )


@pytest.mark.parametrize("automatic", [True, False])
@pytest.mark.parametrize("action", ["zoom", "scroll"])
def test_toolbar_navigation_preserves_y_scaling_choice_for_result_bars(window, automatic, action):
    frame = pd.DataFrame({"time": [0.0, 4.0, 8.0], "tremor_power": [2.0, 3.0, 200.0]})
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    window.canvas.draw()
    axes = window.figure.axes[0]
    if not automatic:
        axes.set_ylim(0.0, 500.0)
    toolbar = window.plot_toolbar
    if action == "zoom":
        toolbar.zoom()
        first = axes.transData.transform((0.5, axes.get_ylim()[1] * 0.1))
        last = axes.transData.transform((7.5, axes.get_ylim()[1] * 0.9))
        toolbar.press_zoom(MouseEvent("button_press_event", window.canvas, *first, button=1))
        toolbar.release_zoom(MouseEvent("button_release_event", window.canvas, *last, button=1))
    else:
        axes.set_xlim(0.5, 7.5)
        window.result_time_scroll.setValue(0)
    assert axes.get_autoscaley_on() == automatic
    assert axes.get_ylim()[1] < 1 if automatic else axes.get_ylim()[1] > 100, (
        axes.get_xlim(),
        axes.get_ylim(),
    )
    limits = axes.get_ylim()
    toolbar.back()
    assert axes.get_autoscaley_on() == automatic
    toolbar.forward()
    assert axes.get_autoscaley_on() == automatic
    assert axes.get_ylim() == pytest.approx(limits)


def test_result_titles_and_compact_presence_tracks_keep_scientific_timing_metadata(
    window, tremor_outputs
):
    result = tremor_outputs
    result["quantifications"]["gait"] = {
        "unfiltered": pd.DataFrame(
            {
                "gait_segment_nr": [1, 1],
                "range_of_motion": [5.0, 8.0],
                "peak_velocity": [25.0, 40.0],
            }
        )
    }
    result["metadata"]["gait"] = {
        "unfiltered": {"per_segment": {1: {"start_s": 0.0, "end_s": 4.0, "duration_s": 4.0}}}
    }
    window.analyzed(result)
    chosen = {
        ("quantifications/gait/unfiltered", "range_of_motion"),
        ("quantifications/gait/unfiltered", "peak_velocity"),
        ("classifications/tremor", "pred_tremor_checked"),
    }
    window.result_series.blockSignals(True)
    for key, item in window._series_items.items():
        item.setCheckState(0, Qt.Checked if key in chosen else Qt.Unchecked)
    window.result_series.blockSignals(False)
    window.plot()
    window.canvas.draw()
    axes = {axis._paradigma_metric: axis for axis in window.figure.axes}
    assert axes["range_of_motion"].get_title(loc="left") == "Range of motion (unfiltered gait)"
    assert axes["peak_velocity"].get_title(loc="left") == "Peak velocity (unfiltered gait)"
    assert axes["peak_velocity"].get_title(loc="right") == "Gait"
    indicator = axes["pred_tremor_checked"]
    assert not indicator.texts and not indicator.get_yticks().size
    assert indicator.get_position().height < axes["range_of_motion"].get_position().height * 0.5
    assert np.ptp(indicator.collections[0].get_paths()[0].vertices[:, 1]) == pytest.approx(0.48)
    assert (
        window._result_state._timings["quantifications/gait/unfiltered"]["Time basis"]
        .str.contains("Estimated")
        .all()
    )
