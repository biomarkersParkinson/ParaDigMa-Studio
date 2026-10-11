"""Display joins must preserve scientific outputs and the gait subset relation."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_studio.app import MainWindow
from paradigma_studio.gait_presence import gait_epoch_summaries, gait_presence_intervals


def states(starts, ends, values, **keys):
    return pd.DataFrame({"start": starts, "end": ends, "state": values, **keys})


def test_conditional_filter_uses_the_full_shared_period_instead_of_its_own_window_count():
    detection = states([0.0, 2.0], [2.0, 10.0], [1.0, 0.0])
    arm = states([0.0], [2.0], [1.0])
    summary = gait_epoch_summaries(gait_presence_intervals(detection, arm))
    for stage in ("gait", "filtered"):
        np.testing.assert_array_equal(summary[stage].observed_s, [10.0])
        np.testing.assert_array_equal(summary[stage].positive_s, [2.0])
        np.testing.assert_array_equal(
            summary[stage].value, [20.0]
        )  # Previously filtering alone gave 100%.


def test_different_cadences_boundary_crossings_and_missing_filtering_share_known_seconds():
    detection = states(
        [1798.0, 1799.0, 1800.0, 1801.0, 1802.0, 1810.0],
        [1799.0, 1800.0, 1801.0, 1802.0, 1803.0, 1811.0],
        [0.0, 1.0, 1.0, 1.0, 0.0, 1.0],
    )
    arm = states(
        [1799.25, 1800.0, 1800.75, 1810.0],
        [1800.0, 1800.75, 1801.5, 1810.75],
        [1.0, 0.0, 1.0, np.nan],
    )
    summary = gait_epoch_summaries(gait_presence_intervals(detection, arm))
    np.testing.assert_array_equal(summary["gait"].observed_s, [1.75, 2.5])
    np.testing.assert_array_equal(summary["filtered"].observed_s, [1.75, 2.5])
    np.testing.assert_array_equal(summary["gait"].positive_s, [0.75, 1.5])
    np.testing.assert_array_equal(summary["filtered"].positive_s, [0.75, 0.75])
    np.testing.assert_allclose(summary["gait"].value, [100 * 0.75 / 1.75, 60.0])
    np.testing.assert_allclose(summary["filtered"].value, [100 * 0.75 / 1.75, 30.0])


@pytest.mark.parametrize("key", ["file_key", "participant_id", "patient_id"])
def test_filtering_never_borrows_gait_from_another_recording_or_subject(key):
    detection = states([0.0, 0.0], [10.0, 10.0], [1.0, 0.0], **{key: ["a", "b"]})
    arm = states([0.0], [10.0], [1.0], **{key: ["b"]})
    intervals = gait_presence_intervals(detection, arm)
    assert not len(intervals["filtered"])
    summary = gait_epoch_summaries(intervals)
    np.testing.assert_array_equal(summary["filtered"].value, [0.0])


def test_missing_identifiers_match_and_missing_classification_remains_unknown():
    detection = states([0.0, 2.0], [2.0, 3.0], [1.0, np.nan], file_key=[np.nan, np.nan])
    arm = states([0.0], [2.0], [1.0], file_key=[np.nan])
    summary = gait_epoch_summaries(gait_presence_intervals(detection, arm))
    np.testing.assert_array_equal(summary["filtered"].value, [100.0])
    np.testing.assert_array_equal(summary["filtered"].observed_s, [2.0])
    missing = gait_epoch_summaries(
        gait_presence_intervals(states([0.0], [1.0], [1.0]), states([], [], []))
    )
    assert missing["gait"].value.isna().all()
    assert missing["filtered"].value.isna().all()
    standalone = gait_epoch_summaries(
        gait_presence_intervals(states([0.0, 1.0], [1.0, 2.0], [1.0, 0.0]), None)
    )
    np.testing.assert_array_equal(standalone["gait"].value, [50.0])


def test_overlapping_recordings_are_not_counted_twice_and_filtering_cannot_invent_gait():
    detection = states(
        [0.0, 1.0, 0.0, 1.0],
        [1.0, 10.0, 1.0, 10.0],
        [1.0, 0.0, 1.0, 0.0],
        file_key=["a", "a", "b", "b"],
    )
    arm = states([0.0, 0.0], [10.0, 10.0], [1.0, 1.0], file_key=["a", "b"])
    summary = gait_epoch_summaries(gait_presence_intervals(detection, arm))
    np.testing.assert_array_equal(summary["gait"].observed_s, [10.0])
    np.testing.assert_array_equal(summary["filtered"].positive_s, [1.0])
    np.testing.assert_array_equal(summary["filtered"].value, [10.0])


def test_displayed_gait_predictions_share_epoch_denominator_and_preserve_raw_tables(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    output = {
        "classifications": {
            "gait": {
                "detection": pd.DataFrame(
                    {"time": np.arange(10.0), "pred_gait_proba": [1.0, 1.0] + [0.0] * 8}
                ),
                "arm_activity": pd.DataFrame(
                    {"time": [0.0, 0.75, 1.5, 2.25], "pred_no_other_arm_activity_proba": [1.0] * 4}
                ),
            }
        }
    }
    original = deepcopy(output)
    try:
        window.analyzed(output)
        window.result_tabs.setCurrentIndex(1)
        window.result_series.blockSignals(True)
        for (_name, metric), item in window._series_items.items():
            item.setCheckState(0, Qt.Checked if metric.endswith("_window") else Qt.Unchecked)
        window.result_series.blockSignals(False)
        window.plot()
        filtered = next(
            ax
            for ax in window.figure.axes
            if ax._paradigma_metric == "pred_no_other_arm_activity_window"
        )
        # Arm-positive windows extend to 3 s, but detected gait stops at 2 s.
        paths = filtered.collections[0].get_paths()
        assert len(paths) == 1
        assert paths[0].vertices[:, 0].min() == 0.0
        assert paths[0].vertices[:, 0].max() == 2.0
        window.result_graph_view.setCurrentIndex(1)
        summaries = {ax._paradigma_metric: ax._paradigma_epoch_data for ax in window.figure.axes}
        np.testing.assert_array_equal(summaries["pred_gait_window"].value, [20.0])
        np.testing.assert_array_equal(summaries["pred_no_other_arm_activity_window"].value, [20.0])
        for stage, frame in original["classifications"]["gait"].items():
            pd.testing.assert_frame_equal(
                output["classifications"]["gait"][stage], frame, check_exact=True
            )
            pd.testing.assert_frame_equal(
                window.tables["classifications/gait/" + stage], frame, check_exact=True
            )
    finally:
        window.close()
        app.processEvents()
