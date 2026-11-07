"""Overview issue summaries preserve the distinction between failures and skips."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from paradigma_studio.error_reporting import merge_errors
from paradigma_studio.module_issues import module_issue_summaries


def failure(file="recording_001__segment_1", **changes):
    return {
        "pipeline": "gait",
        "stage": "pipeline_execution",
        "file": file,
        "error": "Classification failed: Original processing failure",
        **changes,
    }


def payload(errors, **changes):
    return {
        "errors": errors,
        "quantifications": {"gait": pd.DataFrame({"time": [0.0], "value": [1.0]})},
        **changes,
    }


@pytest.fixture
def provenance():
    return {
        "sources": {f"recording_{index:03d}": f"/recordings/{index}.csv" for index in range(1, 5)}
    }


def test_multiple_sections_count_errors_and_original_recordings_separately(provenance):
    errors = [failure(), failure("recording_001__segment_2"), failure("recording_002__segment_1")]
    results = payload([*errors, deepcopy(errors[0])])
    logged = ["Error in classification step: Original processing failure [recording_001]"]
    summary = module_issue_summaries(results, provenance, logged)["gait"]
    assert summary.processing_errors == 3 and summary.affected_recordings == 2
    assert summary.title == "Partial results" and summary.severity == "warning"
    assert summary.description == "3 processing errors affecting 2 recordings."
    assert len(results["errors"]) == 4
    assert results["quantifications"]["gait"].value.tolist() == [1.0]


def test_shared_skips_count_in_each_module_without_inflating_the_run_total(provenance):
    skip = {
        "pipelines": ["gait", "tremor"],
        "file": "recording_003",
        "stage": "preparation",
        "skipped": True,
        "error": "Skipped recording: Too few samples",
    }
    errors = [failure(), skip, deepcopy(skip)]
    summaries = module_issue_summaries(payload(errors), provenance)
    assert summaries["gait"].processing_errors == 1
    assert summaries["gait"].skipped_recordings == 1
    assert summaries["tremor"].processing_errors == 0
    assert summaries["tremor"].skipped_recordings == 1
    assert summaries["tremor"].severity == "error"  # No usable Tremor output remains.
    assert len(merge_errors([], errors)) == 2


def test_skip_wording_is_explicit_and_classification_failures_are_not_skips(provenance):
    error = failure(
        error="Classification failed: All segments were removed: no segment ≥ 96 samples."
    )
    summary = module_issue_summaries(payload([error]), provenance)["gait"]
    assert summary.processing_errors == 1 and summary.skip_reports == 0


@pytest.mark.parametrize("file", ["", "unidentified_section"])
def test_unknown_recording_attribution_omits_recording_counts(provenance, file):
    summary = module_issue_summaries(payload([failure(file)]), provenance)["gait"]
    assert summary.affected_recordings is None
    assert summary.description == "1 processing error."


def test_explicit_section_map_and_single_file_segment_names_are_supported():
    results = payload(
        [failure("custom_section_a"), failure("custom_section_b")],
        metadata={
            "desktop_recordings": {
                "sections": {"custom_section_a": "original", "custom_section_b": "original"}
            }
        },
    )
    assert module_issue_summaries(results, {})["gait"].affected_recordings == 1
    single = payload([failure("segment_1"), failure("segment_2")])
    assert module_issue_summaries(single, {"source": "sensor.csv"})["gait"].affected_recordings == 1
    assert module_issue_summaries(single, {})["gait"].affected_recordings is None


def test_module_assigned_log_only_errors_are_included_and_unattributed_errors_stay_unassigned():
    diagnostics = [
        "Failed to aggregate tremor results: Original aggregation failure",
        "Unexpected diagnostic without module attribution",
    ]
    summaries = module_issue_summaries({}, {}, diagnostics)
    assert set(summaries) == {"tremor"}
    summary = summaries["tremor"]
    assert summary.processing_errors == 1 and summary.affected_recordings is None
    assert summary.aggregation_failed and summary.title == "No results available"
    assert summary.severity == "error"


@pytest.mark.parametrize(
    "outputs,available",
    [
        ({}, False),
        ({"quantifications": {"gait": pd.DataFrame()}}, False),
        ({"aggregations": {"gait": {"mean": np.nan}}}, False),
        ({"aggregations": {"gait": {"count": 0}}}, True),
        ({"aggregations": {"gait": {"count": 10**400}}}, True),
        ({"classifications": {"gait": pd.DataFrame({"prediction": [False]})}}, True),
    ],
)
def test_module_availability_is_based_on_returned_outputs_not_metadata(
    provenance, outputs, available
):
    results = {"errors": [failure()], "metadata": {"gait": {"input_samples": 5000}}, **outputs}
    summary = module_issue_summaries(results, provenance)["gait"]
    assert summary.has_results is available
    assert summary.title == ("Partial results" if available else "No results available")
    assert summary.severity == ("warning" if available else "error")


def test_aggregation_failure_keeps_available_details_and_explains_missing_summaries(provenance):
    results = payload([failure(file="", stage="aggregation", error="No valid aggregates")])
    summary = module_issue_summaries(results, provenance)["gait"]
    assert summary.title == "Partial results" and summary.aggregation_failed
    assert "summary statistics are unavailable because aggregation failed" in summary.description
    assert "recording" not in summary.description


def test_clean_modules_and_empty_outcomes_do_not_create_issue_notices(provenance):
    assert module_issue_summaries({}, provenance) == {}
    assert module_issue_summaries(payload([]), provenance) == {}


def test_missing_skip_attribution_is_not_reported_as_a_known_number_of_recordings():
    results = {
        "errors": [
            {"pipeline": "gait", "stage": "preparation", "skipped": True, "error": "Too short"}
        ]
    }
    summary = module_issue_summaries(results, {})["gait"]
    assert summary.skipped_recordings is None and summary.severity == "error"
    assert summary.description == "1 report of skipped recordings."


def test_returned_skip_flag_takes_precedence_over_rendered_history_without_the_flag(provenance):
    error = failure("recording_002", stage="preparation", skipped=True, error="Too short")
    history = merge_errors([], [error])
    summary = module_issue_summaries(payload([error]), provenance, history)["gait"]
    assert summary.processing_errors == 0 and summary.skipped_recordings == 1


@pytest.mark.parametrize("mapped", [None, "", []])
def test_unavailable_section_mapping_does_not_invent_an_original_recording(provenance, mapped):
    results = payload(
        [failure("unidentified_section")],
        metadata={"desktop_recordings": {"sections": {"unidentified_section": mapped}}},
    )
    summary = module_issue_summaries(results, provenance)["gait"]
    assert summary.affected_recordings is None and summary.description == "1 processing error."
