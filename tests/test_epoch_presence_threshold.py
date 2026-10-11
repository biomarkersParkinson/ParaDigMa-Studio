"""Display medians require 90 seconds, without altering official outputs."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_studio.app import MainWindow
from paradigma_studio.epochs import (
    availability_epoch_summary,
    epoch_summary,
    require_epoch_presence,
)


def test_threshold_unions_overlaps_splits_boundaries_and_keeps_partial_epoch_rule():
    summary = epoch_summary([100, 1900, 3700, 5500, 7300], [10, 20, 30, 40, 50])
    original = summary.copy(deep=True)
    # 89 s duplicated is still 89 s. A crossing interval contributes only its
    # portion to each half hour, not its complete length to both.
    presence = availability_epoch_summary(
        [100, 100, 1750, 3650, 5400], [139, 139, 1890, 3739.99, 5490]
    )
    qualified = require_epoch_presence(summary, presence)
    np.testing.assert_allclose(qualified.presence_s, [89, 90, 89.99, 90, 0])
    np.testing.assert_array_equal(qualified.value, [np.nan, 20, np.nan, 40, np.nan])
    pd.testing.assert_frame_equal(summary, original)


def test_clock_phase_and_missing_presence_do_not_invent_coverage():
    summary = epoch_summary([0, 1700], [1, 2], phase=-435)
    presence = availability_epoch_summary([100, 1400], [190, 1489], phase=-435)
    np.testing.assert_array_equal(require_epoch_presence(summary, presence).value, [1, np.nan])
    assert require_epoch_presence(summary, availability_epoch_summary([], [])).value.isna().all()
    assert require_epoch_presence(epoch_summary([], []), presence).empty


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = MainWindow(tmp_path)
    yield widget
    widget.close()
    app.processEvents()


def epoch_values(window):
    return {
        (ax._paradigma_dataset, ax._paradigma_metric): ax._paradigma_epoch_data.value.to_numpy()
        for ax in window.figure.axes
    }


def test_tremor_power_requires_presence_time_not_median_sample_count_and_keeps_raw_results(window):
    times = np.arange(5400.0)
    positive = ((times >= 100) & (times < 189)) | ((times >= 1900) & (times < 1990))
    classifications = pd.DataFrame({"time": times, "pred_tremor_checked": positive.astype(int)})
    quantifications = pd.DataFrame(
        {
            "time": [200.0, 201.0, 2000.0, 2001.0, 4000.0],
            "tremor_power": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )
    output = {
        "classifications": {"tremor": classifications},
        "quantifications": {"tremor": quantifications},
    }
    original = deepcopy(output)
    window.analyzed(output)
    window.result_graph_view.setCurrentIndex(1)
    values = epoch_values(window)["quantifications/tremor", "tremor_power"]
    np.testing.assert_array_equal(values, [np.nan, 35, np.nan])
    window.result_graph_view.setCurrentIndex(0)
    np.testing.assert_array_equal(
        window.figure.axes[0]._paradigma_bar_data[2], quantifications.tremor_power
    )
    for stage in output:
        pd.testing.assert_frame_equal(output[stage]["tremor"], original[stage]["tremor"])
        pd.testing.assert_frame_equal(window.tables[stage + "/tremor"], original[stage]["tremor"])
    window.result_graph_view.setCurrentIndex(1)
    # A new result with the same names must replace the old duration cache.
    window.analyzed(
        {
            "classifications": {"tremor": classifications.assign(pred_tremor_checked=0)},
            "quantifications": {"tremor": quantifications},
        }
    )
    assert np.isnan(epoch_values(window)["quantifications/tremor", "tremor_power"]).all()


def test_gait_filtered_and_unfiltered_use_their_own_presence_and_keep_medians(window):
    times = np.arange(5400.0)
    gait = (
        ((times >= 100) & (times < 189))
        | ((times >= 1900) & (times < 1990))
        | ((times >= 3700) & (times < 3800))
    )
    arm_times = np.arange(0.0, 5400.0, 0.75)
    arm = ((arm_times >= 1900.5) & (arm_times < 1989.75)) | (
        (arm_times >= 3700.5) & (arm_times < 3795.0)
    )
    metrics = pd.DataFrame(
        {
            "time": [200.0, 201.0, 2000.0, 2001.0, 4000.0, 4001.0],
            "range_of_motion": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            "peak_velocity": [100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
        }
    )
    output = {
        "classifications": {
            "gait": {
                "detection": pd.DataFrame({"time": times, "pred_gait_proba": gait.astype(float)}),
                "arm_activity": pd.DataFrame(
                    {"time": arm_times, "pred_no_other_arm_activity_proba": arm.astype(float)}
                ),
            }
        },
        "quantifications": {"gait": {"unfiltered": metrics, "filtered": metrics.copy()}},
    }
    original = deepcopy(output)
    window.analyzed(output)
    window.result_series.blockSignals(True)
    for (name, _metric), item in window._series_items.items():
        item.setCheckState(0, Qt.Checked if name.startswith("quantifications/") else Qt.Unchecked)
    window.result_series.blockSignals(False)
    window.result_graph_view.setCurrentIndex(1)
    values = epoch_values(window)
    for metric, scale in (("range_of_motion", 1), ("peak_velocity", 10)):
        np.testing.assert_array_equal(
            values["quantifications/gait/unfiltered", metric], [np.nan, 35 * scale, 55 * scale]
        )
        np.testing.assert_array_equal(
            values["quantifications/gait/filtered", metric], [np.nan, np.nan, 55 * scale]
        )
    for branch in ("filtered", "unfiltered"):
        pd.testing.assert_frame_equal(
            output["quantifications"]["gait"][branch], original["quantifications"]["gait"][branch]
        )


def test_saved_gait_segment_bounds_work_without_classifications_and_do_not_count_swings(window):
    metrics = pd.DataFrame(
        {"gait_segment_nr": [1] * 100 + [2], "range_of_motion": [20.0] * 100 + [40.0]}
    )
    output = {
        "quantifications": {"gait": {"unfiltered": metrics}},
        "metadata": {
            "gait": {
                "unfiltered": {
                    "per_segment": {
                        1: {"start_s": 100.0, "end_s": 189.0},
                        2: {"start_s": 1800.0, "end_s": 1890.0},
                    }
                }
            }
        },
    }
    window.analyzed(output)
    window.result_graph_view.setCurrentIndex(1)
    np.testing.assert_array_equal(
        epoch_values(window)["quantifications/gait/unfiltered", "range_of_motion"], [np.nan, 40.0]
    )
