"""Pulse estimate availability uses complete epochs in the original timespan."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from conftest import select_plot_metric
from PySide6.QtWidgets import QLabel

from paradigma_studio.core import export_results
from paradigma_studio.history import load_result_export
from paradigma_studio.overview import pulse_estimate_availability, recording_extent


def output(count=277):
    return {"metadata": {"pulse_rate": {"nr_pr_est": count}}}


def provenance(duration=600):
    return {"recording_extent": {"start_s": -20, "end_s": duration - 20}}


@pytest.mark.parametrize("hz", [30, 100])
def test_availability_uses_original_timespan_including_excluded_edges_and_gaps(hz):
    saved = {"recording_extent": recording_extent(np.arange(600 * hz) / hz)}
    results = output()
    results["metadata"]["desktop_availability"] = {
        "pulse_rate": {"a": {"intervals": [[20, 180], [400, 580]], "samples": 340 * hz}}
    }
    original = deepcopy(results)
    count, epochs, percentage = pulse_estimate_availability(results, saved)
    assert (count, epochs) == (277, 300)
    assert percentage == pytest.approx(277 / 300 * 100)
    assert results == original


@pytest.mark.parametrize(
    "duration,epochs",
    [(0, 0), (1.9, 0), (2, 1), (3.9, 1), (4, 2), (600 - 1e-10, 300)],
)
def test_only_complete_two_second_epochs_count_and_roundoff_is_tolerated(duration, epochs):
    count, actual, percentage = pulse_estimate_availability(output(0), provenance(duration))
    assert (count, actual) == (0, epochs)
    assert percentage == (0.0 if epochs else None)


def test_missing_official_count_uses_nonmissing_returned_estimates_including_zero():
    results = {"quantifications": {"pulse_rate": pd.DataFrame({"pulse_rate": [60, np.nan, 0]})}}
    assert pulse_estimate_availability(results, provenance(10)) == (2, 5, 40.0)
    results["quantifications"]["pulse_rate"] = pd.DataFrame(columns=["time", "pulse_rate"])
    assert pulse_estimate_availability(results, provenance(10)) == (0, 5, 0.0)


@pytest.mark.parametrize("count", [-1, 1.5, np.nan, np.inf, "invalid"])
def test_invalid_count_is_unavailable_instead_of_a_fabricated_percentage(count):
    assert pulse_estimate_availability(output(count), provenance()) == (None, 300, None)


def test_unknown_legacy_timespan_is_not_inferred_from_output_or_prepared_coverage():
    results = output()
    results["quantifications"] = {
        "pulse_rate": pd.DataFrame({"time": [23, 575], "pulse_rate": [72, 73]})
    }
    results["metadata"]["desktop_availability"] = {
        "pulse_rate": {"df_1": {"intervals": [[0, 600]]}}
    }
    assert pulse_estimate_availability(results, {}) == (277, None, None)
    assert pulse_estimate_availability({}, provenance()) == (None, 300, None)


def test_counts_across_files_use_full_timespan_and_are_not_clamped():
    # Two recordings with a long between-file gap retain that gap in the
    # timespan denominator, just like the Overview's Recording timespan.
    saved = {
        "recording_extent": recording_extent(
            {"a": np.arange(600), "b": np.arange(600)}, {"a": 0, "b": 3600}
        )
    }
    assert pulse_estimate_availability(output(600), saved) == (600, 2100, 600 / 2100 * 100)
    assert pulse_estimate_availability(output(400), provenance()) == (400, 300, 400 / 300 * 100)


def test_overview_replaces_count_with_percentage_and_reopens_without_source_data(window, tmp_path):
    results = output()
    results["aggregations"] = {"pulse_rate": {"mode_pulse_rate": 72.0}}
    results["quantifications"] = {
        "pulse_rate": pd.DataFrame({"time": 23 + np.arange(277) * 2, "pulse_rate": 72.0})
    }
    original = deepcopy(results)
    raw = pd.DataFrame({"time": np.arange(18000) / 30, "green": 1.0})
    window._input_state.frame = raw
    window._result_state.provenance = {
        "source": "unavailable.csv",
        "settings": {"pipelines": ["pulse_rate"], "skip_preparation": True},
    }
    window.analyzed(results)
    key = ("pulse_rate", "Metadata", ("estimate_availability",))
    display = window._result_state.overview_values[key]
    assert display.text() == "92.33"
    assert "277" in display.toolTip() and "300" in display.toolTip()
    assert "full recording timespan" in display.toolTip()
    texts = [label.text() for label in window._layout.overview_content.findChildren(QLabel)]
    assert "Pulse-rate estimate availability (%)" in texts
    assert "Nr pr est" not in texts
    pulse_panel = window._result_state.overview_module_cards["pulse_rate"]
    pulse_texts = [label.text() for label in pulse_panel.findChildren(QLabel)]
    assert "Aggregates" not in pulse_texts and "Metadata" not in pulse_texts
    assert pulse_panel.layout().itemAt(0).widget().text() == "Pulse rate"
    grid = pulse_panel.layout().itemAt(1).layout()
    assert grid.count() == 2
    assert all(grid.itemAt(index).widget().objectName() == "card" for index in range(grid.count()))
    assert ("pulse_rate", "Metadata", ("nr_pr_est",)) not in window._result_state.overview_values
    window.figure.axes[0].set_xlim(100, 200)
    assert display.text() == "92.33"
    path = tmp_path / "pulse.json"
    export_results(path, results, window._result_state.provenance)
    window._result_state.provenance, restored = load_result_export(path)
    window._input_state.frame = None
    window.analyzed(restored)
    assert window._result_state.overview_values[key].text() == "92.33"
    assert restored["metadata"]["pulse_rate"] == {"nr_pr_est": 277}
    pd.testing.assert_frame_equal(
        results["quantifications"]["pulse_rate"], original["quantifications"]["pulse_rate"]
    )
    assert results["metadata"] == original["metadata"]


def test_legacy_overview_shows_unavailable_percentage_with_original_count_in_tooltip(window):
    window.analyzed(output())
    display = window._result_state.overview_values[
        "pulse_rate", "Metadata", ("estimate_availability",)
    ]
    assert display.text() == "—"
    assert "277" in display.toolTip() and "unavailable" in display.toolTip().lower()


def test_pulse_plot_series_and_titles_use_readable_labels_without_renaming_columns(window):
    results = {
        "quantifications": {
            "pulse_rate": pd.DataFrame({"time": [2.0, 4.0], "pulse_rate": [72.0, 73.0]})
        },
        "classifications": {
            "pulse_rate": pd.DataFrame({"time": [0.0, 1.0], "pred_sqa_proba": [0.8, 0.9]})
        },
    }
    original = deepcopy(results)
    window.analyzed(results)
    for stage, metric, title in (
        ("quantifications", "pulse_rate", "Pulse rate"),
        ("classifications", "pred_sqa_proba", "High-quality PPG (probability)"),
    ):
        name = f"{stage}/pulse_rate"
        assert window._result_state._series_items[name, metric].text(0) == title
        select_plot_metric(window, name, metric)
        assert window.figure.axes[0].get_title(loc="left") == title
        pd.testing.assert_frame_equal(results[stage]["pulse_rate"], original[stage]["pulse_rate"])
