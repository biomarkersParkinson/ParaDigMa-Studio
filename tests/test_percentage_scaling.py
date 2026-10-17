"""Percentage bars use the same visible-data scaling and controls as other results."""

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import Qt

from paradigma_studio.daily import DAY_SECONDS


def percentage_results(first, second):
    times = np.r_[np.arange(0, 1800, 4), np.arange(DAY_SECONDS, DAY_SECONDS + 1800, 4)]
    predictions = np.r_[np.arange(450) < first * 4.5, np.arange(450) < second * 4.5]
    return {
        "classifications": {
            "tremor": pd.DataFrame({"time": times, "pred_tremor_checked": predictions.astype(int)})
        },
        "metadata": {
            "desktop_availability": {
                "tremor": {"df_1": {"intervals": [[0, 1800], [DAY_SECONDS, DAY_SECONDS + 1800]]}}
            }
        },
    }


def presence_axis(window):
    return next(
        ax for ax in window.figure.axes if ax._paradigma_dataset == "classifications/tremor"
    )


@pytest.mark.parametrize("view", [1, 2, 3], ids=["30-minute", "day", "profile"])
@pytest.mark.parametrize("percentage", [0, 10, 100])
def test_percentage_and_coverage_bars_start_with_automatic_limits(window, view, percentage):
    results = percentage_results(percentage, percentage)
    original = results["classifications"]["tremor"].copy(deep=True)
    window.analyzed(results)
    window.result_tabs.setCurrentIndex(1)
    coverage_key = next(key for key in window._series_items if key[0].startswith("preparation/"))
    window._series_items[coverage_key].setCheckState(0, Qt.Checked)
    window.result_graph_view.setCurrentIndex(view)
    for ax in window.figure.axes:
        assert ax.get_autoscaley_on()
        peak = ax._paradigma_epoch_data.value.max()
        assert ax.get_ylim()[0] == 0
        assert ax.get_ylim()[1] > peak
        if peak < 100:
            assert ax.get_ylim()[1] < 100
    assert presence_axis(window)._paradigma_epoch_data.value.dropna().eq(percentage).all()
    pd.testing.assert_frame_equal(window._result_state.tables["classifications/tremor"], original)


@pytest.mark.parametrize("view", [1, 2], ids=["30-minute", "day"])
def test_percentage_autoscaling_follows_time_zoom_and_respects_manual_limits_and_reset(
    window, view
):
    window.analyzed(percentage_results(10, 80))
    window.result_tabs.setCurrentIndex(1)
    window.result_graph_view.setCurrentIndex(view)
    ax = presence_axis(window)
    width = DAY_SECONDS if view == 2 else 1800
    ax.set_xlim(0, width)
    assert ax.get_autoscaley_on() and 10 < ax.get_ylim()[1] < 20
    ax.set_xlim(DAY_SECONDS, DAY_SECONDS + width)
    assert 80 < ax.get_ylim()[1] < 100
    toolbar = window.plot_toolbar
    toolbar.active_axes = ax
    toolbar.settings_action.setChecked(True)
    panel = toolbar.settings
    automatic, lower, upper = panel.bounds["y"]
    automatic.setChecked(False)
    lower.setText("0")
    upper.setText("50")
    upper.editingFinished.emit()
    assert not ax.get_autoscaley_on() and ax.get_ylim() == (0, 50)
    ax.set_xlim(0, width)
    assert ax.get_ylim() == (0, 50)
    coverage_key = next(key for key in window._series_items if key[0].startswith("preparation/"))
    window._series_items[coverage_key].setCheckState(0, Qt.Checked)
    ax = presence_axis(window)
    assert not ax.get_autoscaley_on() and ax.get_ylim() == (0, 50)
    toolbar.active_axes = ax
    panel.read_axes()
    panel.reset_button.click()
    assert ax.get_autoscaley_on() and 80 < ax.get_ylim()[1] < 100
