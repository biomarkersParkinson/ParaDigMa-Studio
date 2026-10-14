"""Actual spawned recording workers preserve official scientific results."""

import logging
from copy import deepcopy
from threading import Event

import numpy as np
import pandas as pd
import pytest
from test_scientific_equivalence import (
    DATA,
    assert_equivalent,
    compare_workflows,
    upstream_synthetic,
)

from paradigma_studio import analysis_process
from paradigma_studio.core import analyze

pytestmark = pytest.mark.scientific


def parallel(frames, settings, monkeypatch):
    monkeypatch.setattr(analysis_process, "parallel_worker_count", lambda *_: 2)
    return analysis_process.run_isolated_analysis(
        frames, settings, logging.Logger("parallel-reference", logging.INFO), Event()
    )


@pytest.mark.parametrize("side", ["left", "right"])
def test_recorded_gait_and_tremor_parallel_results_equal_official_batch(
    tmp_path, monkeypatch, side
):
    recording = pd.read_parquet(DATA / "prepared_imu.parquet")
    later = recording.iloc[40000:].copy().reset_index(drop=True)
    later["time"] -= later.time.iloc[0]
    frames = {"recording_001": recording, "recording_002": later}
    original = deepcopy(frames)
    settings = {"pipelines": ["gait", "tremor"], "skip_preparation": True, "watch_side": side}
    sequential, _, _ = compare_workflows(
        frames,
        frames,
        settings["pipelines"],
        tmp_path,
        skip_preparation=True,
        watch_side=side,
    )
    actual = parallel(frames, settings, monkeypatch)
    assert actual["errors"] == []
    assert_equivalent(actual, sequential)
    assert_equivalent(frames, original, "original recording inputs")


@pytest.mark.parametrize("unit", ["difference_s", "difference_ms"])
def test_raw_difference_recordings_keep_exclusion_gaps_and_classification_identities(
    synthetic_imu, monkeypatch, unit
):
    frame = synthetic_imu.iloc[:2000].copy()
    times = frame.time.to_numpy().copy()
    times[1000:] += 5
    frame["time"] = np.r_[0, np.diff(times)] * (1000 if unit.endswith("ms") else 1)
    frame.loc[1000:1001, "gyroscope_x"] = np.nan
    frames = {"first": frame, "second": frame.copy()}
    settings = {
        "pipelines": ["tremor"],
        "time_input_unit": unit,
        "split_by_gaps": True,
        "drop_missing_samples": True,
    }
    expected = analyze(frames, **deepcopy(settings))
    actual = parallel(frames, settings, monkeypatch)
    assert actual["errors"] == []
    assert_equivalent(actual, expected)
    assert actual["metadata"]["desktop_preparation"]["excluded_samples"] == 4
    assert actual["metadata"]["desktop_preparation"]["continuous_sections"] == 4


def test_all_modules_and_partial_group_failure_preserve_sequential_semantics(monkeypatch):
    frame = upstream_synthetic("gait")
    frame["green"] = np.sin(2 * np.pi * 1.2 * frame.time)
    frames = {"first": frame, "second": frame.iloc[6000:].copy().reset_index(drop=True)}
    settings = {"pipelines": ["gait", "tremor", "pulse_rate"], "watch_side": "left"}
    for missing in (False, True):
        selected = deepcopy(frames)
        if missing:
            selected["second"] = selected["second"].drop(columns="gyroscope_x")
        expected = analyze(selected, **deepcopy(settings))
        actual = parallel(selected, settings, monkeypatch)
        assert_equivalent(actual, expected)
        if missing:
            assert actual["errors"][0]["pipelines"] == ["gait", "tremor"]
            assert "gait" not in actual["quantifications"]


def test_empty_gait_outputs_and_per_file_pipeline_failure_keep_canonical_results(monkeypatch):
    frame = upstream_synthetic("gait")
    frame[[f"accelerometer_{axis}" for axis in "xyz"]] = 0.0
    settings = {"pipelines": ["gait"], "skip_preparation": True, "watch_side": "right"}
    for frames in (
        {"first": frame, "second": frame.copy()},
        {
            "short": frame.iloc[:100].copy(),
            "recorded": pd.read_parquet(DATA / "prepared_imu.parquet"),
        },
    ):
        actual = parallel(frames, settings, monkeypatch)
        expected = analyze(frames, **deepcopy(settings))
        assert_equivalent(actual, expected)


def test_custom_gait_duration_categories_and_statistics_match_official_batch(tmp_path, monkeypatch):
    frame = pd.read_parquet(DATA / "prepared_imu.parquet")
    frames = {"first": frame, "second": frame.iloc[40000:].copy().reset_index(drop=True)}
    settings = {
        "pipelines": ["gait"],
        "skip_preparation": True,
        "watch_side": "right",
        "gait_segment_categories": ["(0, 10)", [10, 30], (30, "inf")],
        "aggregates": ["median", "95p", "std"],
    }
    selected = {name: value for name, value in settings.items() if name != "pipelines"}
    expected, _, _ = compare_workflows(frames, frames, settings["pipelines"], tmp_path, **selected)
    actual = parallel(frames, settings, monkeypatch)
    assert not actual["errors"]
    assert_equivalent(actual, expected)
