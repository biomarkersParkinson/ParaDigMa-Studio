"""Gait overview uses exact official aggregate values and keeps native tables."""

from copy import deepcopy

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QFrame

from paradigma_desktop.app import MainWindow
from paradigma_desktop.gait_overview import aggregate_rows, duration_label, segment_count_rows


def aggregates():
    output = {}
    for branch_index, branch in enumerate(("unfiltered", "filtered")):
        output[branch] = {}
        for duration_index, duration in enumerate(("20_inf", "0_20", "0_inf")):
            values = {"duration_s": 10.0 * (duration_index + 1)}
            for metric in ("range_of_motion", "peak_velocity"):
                for index, statistic in enumerate(("median", "95p", "median_cov", "mean_cov")):
                    values[f"{statistic}_{metric}"] = (
                        branch_index * 10 + duration_index + index / 10
                    )
            output[branch][duration] = values
    output["filtered"]["0_20"]["95p_range_of_motion"] = np.nan
    output["unfiltered"]["20_inf"]["median_cov_peak_velocity"] = None
    return output


def test_overview_three_cards_with_all_statistics_and_ordered_exact_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    source = aggregates()
    original = deepcopy(source)
    window.show()
    window.analyzed({"aggregations": {"gait": source}})
    app.processEvents()
    try:
        cards = [
            widget for widget in window.findChildren(QFrame) if widget.property("gaitOverviewGroup")
        ]
        assert {widget.property("gaitOverviewGroup") for widget in cards} == {
            "quantity",
            "range_of_motion",
            "peak_velocity",
        }
        assert len(window.overview_gait_charts) == 10
        assert np.isnan(window.overview_gait_charts["segment_count"]["values"]).all()
        ordered = aggregate_rows(source)
        assert [(branch, duration) for branch, duration, _ in ordered] == [
            (branch, duration)
            for branch in ("filtered", "unfiltered")
            for duration in ("0_inf", "0_20", "20_inf")
        ]
        for metric, chart in window.overview_gait_charts.items():
            if metric == "segment_count":
                continue
            expected = np.asarray(
                [
                    np.nan if values.get(metric) is None else values[metric]
                    for _, _, values in ordered
                ]
            )
            np.testing.assert_array_equal(chart["values"], expected)
            displayed = expected / 60 if metric == "duration_s" else expected
            np.testing.assert_array_equal(chart["display_values"], displayed)
            np.testing.assert_array_equal(
                [bar.get_width() for bar in chart["axis"].patches],
                displayed[np.isfinite(displayed)],
            )
            if metric == "duration_s":
                assert chart["axis"].get_xlabel() == "Minutes"
            chart["canvas"].draw()
        assert not any(
            module == "gait" and group == "Aggregates"
            for module, group, path in window.overview_values
        )
        assert source == original  # No derived statistics or edits to aggregate dictionaries.
        assert window.aggregation_tables
        scroll = window._result_view_scrolls[0].verticalScrollBar()
        scroll.setValue(0)
        canvas = window.overview_gait_charts["duration_s"]["canvas"]
        event = QWheelEvent(
            QPointF(50, 50),
            QPointF(canvas.mapToGlobal(QPoint(50, 50))),
            QPoint(),
            QPoint(0, -120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        app.sendEvent(canvas, event)
        assert scroll.value() > 0  # Scrolling works while the pointer is over a chart.
    finally:
        window.close()
        app.processEvents()


def test_missing_statistics_and_unknown_aggregate_fields_are_retained(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.analyzed(
        {
            "aggregations": {
                "gait": {
                    "unfiltered": {
                        "all": {
                            "duration_s": 0.0,
                            "median_range_of_motion": None,
                            "custom_measure": 123,
                        }
                    }
                }
            }
        }
    )
    try:
        assert window.overview_gait_charts["duration_s"]["values"].tolist() == [0.0]
        assert np.isnan(window.overview_gait_charts["median_range_of_motion"]["values"][0])
        assert (
            window.overview_values[
                ("gait", "Aggregates", ("unfiltered", "all", "custom_measure"))
            ].text()
            == "123"
        )
        assert duration_label("0_inf") == "All durations"
        assert duration_label("20_inf") == "≥ 20 s"
    finally:
        window.close()
        app.processEvents()


def test_charts_match_official_gait_aggregation_output(tmp_path):
    import pandas as pd
    from paradigma.pipelines.gait_pipeline import aggregate_arm_swing_params

    frame = pd.DataFrame(
        {
            "gait_segment_nr": [1, 1, 1, 2, 2, 2],
            "range_of_motion": [10.0, 12.0, 14.0, 20.0, 22.0, 24.0],
            "peak_velocity": [30.0, 40.0, 50.0, 60.0, 70.0, 80.0],
        }
    )
    metadata = {"per_segment": {1: {"duration_s": 10.0}, 2: {"duration_s": 30.0}}}
    official = aggregate_arm_swing_params(
        frame,
        segment_meta=metadata,
        gait_segment_categories=[(0, float("inf")), (0, 20), (20, float("inf"))],
        aggregates=["median", "95p", "cov"],
    )
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.analyzed(
        {
            "aggregations": {"gait": {"unfiltered": official}},
            "metadata": {"gait": {"unfiltered": metadata}},
        }
    )
    try:
        assert len(window.overview_gait_charts) == 10
        np.testing.assert_array_equal(
            window.overview_gait_charts["segment_count"]["values"], [np.nan, np.nan, 1, 1]
        )
        assert [
            text.get_text() for text in window.overview_gait_charts["segment_count"]["axis"].texts
        ] == ["—", "—", "1", "1"]
        for metric, chart in window.overview_gait_charts.items():
            if metric == "segment_count":
                continue
            expected = [official[duration][metric] for branch, duration in chart["categories"]]
            np.testing.assert_array_equal(chart["values"], expected)
    finally:
        window.close()
        app.processEvents()


def test_segment_counts_match_official_categories_and_twenty_second_boundary():
    metadata = {
        "filtered": {
            "per_segment": {
                "a": {"duration_s": 2.0, "unfiltered_duration_s": 19.9},
                "b": {"duration_s": 3.0, "unfiltered_duration_s": 20.0},
                "c": {"duration_s": 4.0, "unfiltered_duration_s": 30.0},
            }
        },
        "unfiltered": {
            "per_segment": {
                "a": {"duration_s": 19.9},
                "b": {"duration_s": 20.0},
                "c": {"start_s": 10.0, "end_s": 40.0},
            }
        },
    }
    original = deepcopy(metadata)
    rows = segment_count_rows(metadata)
    assert [(branch, duration, values["segment_count"]) for branch, duration, values in rows] == [
        ("filtered", "0_20", 1),
        ("filtered", "20_inf", 2),
        ("unfiltered", "0_20", 1),
        ("unfiltered", "20_inf", 2),
    ]
    assert metadata == original


def test_missing_invalid_and_empty_segment_metadata_do_not_invent_counts():
    assert all(np.isnan(values["segment_count"]) for _, _, values in segment_count_rows({}))
    rows = segment_count_rows(
        {
            "filtered": {"per_segment": {}},
            "unfiltered": {"per_segment": {"a": {"duration_s": np.nan}}},
        }
    )
    np.testing.assert_array_equal(
        [values["segment_count"] for _, _, values in rows], [0, 0, np.nan, np.nan]
    )
