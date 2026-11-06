"""Error summaries count failures once while full diagnostic logs remain intact."""

import logging
from copy import deepcopy

import pandas as pd
import pytest
from conftest import wait_for_job
from run_fixtures import make_run

from paradigma_studio import app as desktop
from paradigma_studio.error_reporting import append_error, error_text, merge_errors
from paradigma_studio.history import RunHistory, now

INDEX_ERROR = "too many indices for array: array is 3-dimensional, but 5 were indexed"
NO_WINDOWS = (
    "No windows were created from predicted gait data. This occurs when all segments "
    "are too short. Data shape: (128, 13), segments: 1"
)


def failure(
    file="recording_001__segment_1", pipeline="gait", error=None, stage="pipeline_execution"
):
    return {
        "file": file,
        "pipeline": pipeline,
        "stage": stage,
        "error": error or f"Classification failed: {INDEX_ERROR}",
    }


def batch_errors():
    returned, logged = [], []
    for index in range(1, 20):
        key = f"recording_{index:03d}"
        body = NO_WINDOWS if index in (2, 6) else INDEX_ERROR
        step = "quantification" if index in (4, 13) else "classification"
        if index in (4, 8, 13, 19):
            body = "All segments were removed: no segment ≥ 96 samples."
        returned.append(failure(f"{key}__segment_1", error=f"{step.title()} failed: {body}"))
        if body == NO_WINDOWS:
            logged.append(f"{body} [{key}]")
        logged.append(f"Error in {step} step: {body} [{key}]")
    for index in range(20, 23):
        returned.append(
            {
                "file": f"recording_{index:03d}",
                "pipelines": ["gait", "tremor"],
                "stage": "preparation",
                "error": "Skipped recording: All segments were removed: no segment ≥ 96 samples.",
            }
        )
    return returned, logged


def test_batch_diagnostics_reduce_43_reports_to_22_contextual_failures():
    returned, logged = batch_errors()
    original = deepcopy(returned)
    assert len(returned) + len(logged) == 43
    expected = [error_text(error) for error in returned]
    assert merge_errors(logged, returned) == expected
    assert merge_errors(reversed(logged), returned) == expected
    assert merge_errors(expected + logged, []) == expected
    assert merge_errors(expected, returned) == expected
    assert returned == original


@pytest.mark.parametrize(
    "message",
    [
        f"Error in classification step: {INDEX_ERROR} [recording_001]",
        f"Gait pipeline failed on recording_001__segment_1: Classification failed: {INDEX_ERROR}",
        f"Failed to run gait pipeline on recording_001__segment_1: Classification failed: {INDEX_ERROR}",
    ],
)
def test_diagnostic_wrappers_and_parent_recording_suffix_match_the_returned_section(message):
    error = failure()
    assert merge_errors([message], [error]) == [error_text(error)]


@pytest.mark.parametrize(
    "other",
    [
        failure(file="recording_002__segment_1"),
        failure(file="recording_001__segment_2"),
        failure(pipeline="tremor"),
        failure(error=f"Quantification failed: {INDEX_ERROR}"),
        failure(error=f"Classification failed: {INDEX_ERROR} in a different array"),
        failure(error=f"Classification failed: ValueError: {INDEX_ERROR}"),
    ],
)
def test_structured_failures_with_distinct_context_or_details_remain_separate(other):
    first = failure()
    assert merge_errors([], [first, other, first]) == [error_text(first), error_text(other)]


@pytest.mark.parametrize(
    "message",
    [
        f"Error in classification step: {INDEX_ERROR} [recording_002]",
        f"Error in classification step: {INDEX_ERROR} [recording_0010]",
        f"Error in classification step: {INDEX_ERROR} [recording_001__segment_2]",
        f"Error in quantification step: {INDEX_ERROR} [recording_001]",
        f"tremor pipeline returned error: Classification failed: {INDEX_ERROR} [recording_001]",
        f"Error in classification step: {INDEX_ERROR} in a different array [recording_001]",
        "Failed to aggregate tremor results: No valid windows",
    ],
)
def test_unrepresented_logged_failures_are_retained(message):
    first = failure()
    assert merge_errors([message], [first]) == [error_text(first), message]


@pytest.mark.parametrize("reverse", [False, True])
def test_log_only_failure_chains_keep_the_most_specific_message_and_distinct_stages(reverse):
    bare = f"{NO_WINDOWS} [recording_001]"
    classified = f"Error in classification step: {NO_WINDOWS} [recording_001]"
    quantified = f"Error in quantification step: {NO_WINDOWS} [recording_001]"
    messages = [bare, classified] if not reverse else [classified, bare]
    assert merge_errors(messages, []) == [classified]
    current = []
    for message in [*messages, quantified, classified]:
        current = append_error(current, message)
    assert current == [classified, quantified]


def test_known_exception_types_and_missing_recording_context_do_not_hide_specific_errors():
    errors = [
        failure(error=f"Classification failed: {name}: bad array")
        for name in ("ValueError", "IndexError")
    ]
    assert merge_errors([], errors) == list(map(error_text, errors))
    contextual = f"Error in classification step: {INDEX_ERROR} [recording_001]"
    generic = failure(file="")
    assert merge_errors([contextual], [generic]) == [error_text(generic), contextual]


def test_existing_history_is_cleaned_in_memory_without_rewriting_log_or_files(tmp_path):
    returned, logged = batch_errors()
    record = make_run()
    original_errors = [error_text(error) for error in returned] + logged
    transcript = "\n".join(logged) + "\nTraceback (most recent call last):\nOriginal stack\n"
    record.update(status="Partial", finished=now(), errors=original_errors, log=transcript)
    history = RunHistory(tmp_path / "runs")
    history.save(record)
    path = history.directory / f"{record['id']}.json"
    original_bytes = path.read_bytes()
    restored, issues = history.load()
    assert not issues and len(restored) == 1
    assert restored[0]["errors"] == [error_text(error) for error in returned]
    assert restored[0]["log"] == transcript and path.read_bytes() == original_bytes


def test_gui_live_and_final_counts_use_one_summary_while_processing_log_keeps_messages(
    window, monkeypatch
):
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0.0, 1.0]})))
    returned, logged = batch_errors()
    wrappers = [
        f"Gait pipeline failed on {error['file']}: {error['error']} "
        f"[{error['file'].split('__')[0]}]"
        for error in returned
        if error.get("pipeline") == "gait"
    ]
    orphan = "Failed to aggregate tremor results: Original aggregation failure"

    def analyze(frame, settings, logger, cancel):
        for message in [*logged, *wrappers]:
            logger.error(message)
        try:
            raise ValueError("Original aggregation failure")
        except ValueError:
            logger.exception(orphan)
        return {"errors": returned}

    monkeypatch.setattr(desktop, "run_isolated_analysis", analyze)
    window.run_analysis()
    wait_for_job(window)
    record = window._run_state.current_run
    expected = [error_text(error) for error in returned] + [orphan]
    assert record["status"] == "Partial" and record["errors"] == expected
    assert "23 processing error(s)" in window.status.text()
    assert window.run_table.model().frame.loc[0, "Errors"] == 23
    assert window.run_errors.toPlainText() == "\n\n".join(expected)
    assert all(
        record["log"].splitlines().count(message) == 1 for message in [*logged, *wrappers, orphan]
    )
    assert "Traceback (most recent call last)" in record["log"]
    assert "in analyze" in record["log"]
    assert window.log.toPlainText().rstrip("\n") == record["log"].rstrip("\n")
    restored, issues = window.history.load()
    assert not issues and restored[0]["errors"] == expected


def test_live_counts_reconcile_a_log_only_chain_without_emitting_another_error(window):
    record = make_run()
    window._run_state.runs.insert(0, record)
    window._run_state.active_run = record
    window.refresh_runs()
    logger = logging.Logger("live-diagnostic")
    from types import SimpleNamespace

    from paradigma_studio.jobs import SignalHandler

    logger.addHandler(
        SignalHandler(
            SimpleNamespace(emit=window.append_log),
            error=SimpleNamespace(emit=window.capture_error),
        )
    )
    for message in (NO_WINDOWS, f"Error in classification step: {NO_WINDOWS}"):
        logger.error(message)
        assert window.run_table.model().frame.loc[0, "Errors"] == 1
    assert record["errors"] == [f"Error in classification step: {NO_WINDOWS}"]
    assert record["log"].count(NO_WINDOWS) == 2
    window.finish_run("Partial")
