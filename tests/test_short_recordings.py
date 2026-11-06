"""Short batch members retain usable outputs, diagnostics and original source identities."""

import logging
from copy import deepcopy
from pathlib import Path
from threading import Event

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_job, wait_for_previews
from test_scientific_equivalence import assert_equivalent

from paradigma_studio import analysis_process, core
from paradigma_studio.analysis_progress import ProgressLogHandler
from paradigma_studio.history import load_result_export
from paradigma_studio.inspection import inspect_recording


@pytest.fixture
def valid(synthetic_imu):
    return synthetic_imu.iloc[:2000].copy()


@pytest.fixture
def settings():
    return {"pipelines": ["tremor"], "split_by_gaps": True, "drop_missing_samples": True}


def short_recording(valid, kind):
    if kind in ("empty", "one-sample"):
        return valid.iloc[: int(kind == "one-sample")].copy()
    short = valid.iloc[:300].copy()
    if kind == "minimum-duration":
        return short.iloc[:30].copy()
    if kind == "missing-samples":
        short["gyroscope_x"] = np.nan
    elif kind == "excluded-sections":
        short.loc[100:199, "gyroscope_x"] = np.nan
    else:
        assert kind == "gap-sections"
        short["time"] += np.repeat([0, 10, 20], 100)
    return short


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "one-sample",
        "minimum-duration",
        "missing-samples",
        "excluded-sections",
        "gap-sections",
    ],
)
def test_unusable_batch_member_preserves_results_and_preparation_counts(valid, settings, kind):
    short = short_recording(valid, kind)
    frames = {"short": short, "usable": valid}
    original = deepcopy(frames)
    expected = core.analyze({"usable": valid}, **settings)
    actual = core.analyze(frames, **settings)
    for category in ("quantifications", "classifications", "aggregations"):
        assert_equivalent(actual[category], expected[category])
    assert not actual["quantifications"]["tremor"].empty
    (error,) = actual["errors"]
    assert error["file"] == "short" and error["skipped"] is True
    assert error["stage"] == "preparation" and error["pipelines"] == ["tremor"]
    assert "Skipped recording:" in error["error"]
    preparation = actual["metadata"]["desktop_preparation"]
    assert preparation["input_samples"] == len(valid) + len(short)
    assert preparation["analyzed_samples"] == len(valid)
    assert preparation["excluded_samples"] == short.gyroscope_x.isna().sum()
    skipped = preparation["by_recording"]["short"]
    assert skipped["analyzed_samples"] == skipped["continuous_sections"] == 0
    assert skipped["skipped_reason"] in error["error"]
    assert actual["metadata"]["desktop_recordings"] == {
        "recordings": ["short", "usable"],
        "sections": {"usable__segment_1": "usable"},
    }
    assert_equivalent(
        actual["metadata"]["desktop_availability"], expected["metadata"]["desktop_availability"]
    )
    assert_equivalent(frames, original, "unchanged inputs")


@pytest.mark.scientific
def test_short_file_batch_matches_official_results_from_usable_recording(valid, tmp_path):
    from paradigma.orchestrator import run_paradigma

    # Call the official raw orchestrator independently, including its per-file
    # preparation failure. No Studio preparation or scientific output is mocked.
    frames = {"usable": valid, "short": valid.iloc[:30].copy()}
    reference = run_paradigma(
        dfs=deepcopy(frames),
        pipelines=["tremor"],
        split_by_gaps=True,
        max_gap_seconds=1.5,
        min_segment_seconds=1.5,
        output_dir=tmp_path,
    )
    actual = core.analyze(frames, pipelines=["tremor"], split_by_gaps=True)
    assert len(reference["errors"]) == len(actual["errors"]) == 1
    assert reference["errors"][0]["file"] == actual["errors"][0]["file"] == "short"
    quantified = actual["quantifications"]["tremor"].copy()
    quantified["file_key"] = quantified.file_key.str.removesuffix("__segment_1")
    assert_equivalent(quantified, reference["quantifications"]["tremor"])
    assert_equivalent(actual["aggregations"], reference["aggregations"])


@pytest.mark.parametrize("workers", [1, 2])
@pytest.mark.parametrize("all_short", [False, True])
@pytest.mark.scientific
def test_spawned_batch_retains_order_metadata_and_monotonic_progress(
    valid, settings, monkeypatch, workers, all_short
):
    short = valid.iloc[:30].copy()
    frames = {
        "first": short if all_short else valid,
        "short": short,
        "last": short if all_short else valid,
    }
    expected = core.analyze(deepcopy(frames), **settings)
    monkeypatch.setattr(analysis_process, "parallel_worker_count", lambda *_: workers)
    progress = []
    logger = logging.Logger("short-batch", logging.INFO)
    logger.addHandler(ProgressLogHandler(progress.append))
    actual = analysis_process.run_isolated_analysis(frames, settings, logger, Event())
    assert_equivalent(actual, expected)
    assert progress == sorted(set(progress)) and progress[-1] == 980
    assert [error["file"] for error in actual["errors"]] == (
        list(frames) if all_short else ["short"]
    )
    if all_short:
        assert actual["quantifications"]["tremor"].empty
        assert actual["metadata"]["desktop_availability"] == {"tremor": {}}
    else:
        assert list(actual["quantifications"]["tremor"].file_key.unique()) == [
            "first__segment_1",
            "last__segment_1",
        ]


@pytest.mark.parametrize("workers", [1, 2])
@pytest.mark.scientific
def test_combined_module_groups_skip_only_the_unusable_recording(valid, monkeypatch, workers):
    valid["green"] = np.sin(2 * np.pi * 1.2 * valid.time)
    frames = {"short": valid.iloc[:30].copy(), "usable": valid}
    settings = {"pipelines": ["tremor", "pulse_rate"], "split_by_gaps": True}
    expected = core.analyze(deepcopy(frames), **settings)
    monkeypatch.setattr(analysis_process, "parallel_worker_count", lambda *_: workers)
    actual = analysis_process.run_isolated_analysis(
        frames, settings, logging.Logger("groups"), Event()
    )
    assert_equivalent(actual, expected)
    assert not actual["quantifications"]["tremor"].empty
    assert [error["pipelines"] for error in actual["errors"] if error.get("skipped")] == [
        ["tremor"],
        ["pulse_rate"],
    ]
    assert all(error.get("stage") != "desktop_execution" for error in actual["errors"])


@pytest.mark.parametrize("workers", [1, 2])
@pytest.mark.scientific
def test_recorded_gait_and_tremor_keep_window_classification_and_pooled_results(
    monkeypatch, workers
):
    recording = pd.read_parquet(Path(__file__).parent / "data/paradigma/prepared_imu.parquet")
    frames = {"short": recording.iloc[:30].copy(), "usable": recording}
    settings = {
        "pipelines": ["gait", "tremor"],
        "split_by_gaps": True,
        "accelerometer_units": "g",
        "watch_side": "right",
    }
    expected = core.analyze({"usable": recording}, **settings)
    monkeypatch.setattr(analysis_process, "parallel_worker_count", lambda *_: workers)
    actual = analysis_process.run_isolated_analysis(
        frames, settings, logging.Logger("gait-batch"), Event()
    )
    assert len(actual["errors"]) == 1 and actual["errors"][0]["file"] == "short"
    for category in ("quantifications", "classifications", "aggregations"):
        assert_equivalent(actual[category], expected[category])
    assert not actual["quantifications"]["gait"]["filtered"].empty
    assert not actual["classifications"]["gait"]["detection"].empty


@pytest.mark.parametrize("fault", ["missing-channel", "invalid-time", "invalid-minimum"])
def test_other_preparation_errors_still_abort(valid, settings, fault):
    broken = valid.copy()
    message = "Missing sensor columns"
    if fault == "missing-channel":
        broken = broken.drop(columns="gyroscope_x")
    elif fault == "invalid-time":
        broken.loc[1, "time"] = 0
        message = "strictly increasing"
    else:
        settings["min_segment_seconds"] = -1
        message = "positive finite seconds"
    with pytest.raises(ValueError, match=message):
        core.analyze({"usable": valid, "broken": broken}, **settings)


def test_unexpected_segmentation_error_is_not_treated_as_a_short_recording(
    valid, settings, monkeypatch
):
    def fail(*args):
        raise ValueError("Unexpected segmentation failure")

    monkeypatch.setattr(core, "discard_segments", fail)
    with pytest.raises(ValueError, match="Unexpected segmentation failure"):
        core.analyze({"usable": valid}, **settings)


@pytest.mark.parametrize("all_short", [False, True])
def test_gui_batch_reports_skips_and_saves_original_sources_and_diagnostics(
    window, valid, tmp_path, monkeypatch, all_short
):
    frames = {
        "first": valid.iloc[:30].copy() if all_short else valid,
        "short": valid.iloc[:30].copy(),
    }
    sources = {key: str(tmp_path / f"{key}.csv") for key in frames}
    descriptions = {key: inspect_recording(frame, "relative_s") for key, frame in frames.items()}
    window.loaded_recordings((sources, frames, descriptions))
    wait_for_previews(window)
    window.set_modules(["tremor"])
    monkeypatch.setattr(analysis_process, "parallel_worker_count", lambda *_: 1)
    window.run_analysis()
    wait_for_job(window)
    record = window._run_state.current_run
    assert record["status"] == "Partial"
    assert len(record["errors"]) == (2 if all_short else 1)
    assert any("short" in error and "Skipped recording" in error for error in record["errors"])
    assert ("No usable recordings remain" in window.status.text()) is all_short
    assert window.run_button.isEnabled() and not window.progress.isVisible()
    assert window.export_button.isEnabled()
    window.save_results()
    wait_for_job(window)
    saved = next(output for output in record["outputs"] if output.get("local"))
    provenance, restored = load_result_export(saved["path"])
    assert provenance["sources"] == sources
    assert_equivalent(restored["errors"], window._result_state.results["errors"])
    assert_equivalent(
        restored["metadata"]["desktop_preparation"],
        window._result_state.results["metadata"]["desktop_preparation"],
    )
