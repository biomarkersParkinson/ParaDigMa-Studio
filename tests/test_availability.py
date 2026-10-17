"""Prepared inputs and their presentation coverage."""

import numpy as np
import pandas as pd

from paradigma_studio.availability import availability_views, prepared_availability


def test_prepared_coverage_retains_real_gaps_sections_offsets_and_distinct_pipeline_inputs(
    window, tremor_outputs
):
    inputs = {
        "recording_001": pd.DataFrame({"time": [0.0, 0.01, 0.02, 1.0, 1.01]}),
        "recording_002": pd.DataFrame({"time": [0.0, 0.01]}),
    }
    coverage = prepared_availability(inputs, ["gait", "tremor"])
    np.testing.assert_allclose(
        coverage["gait"]["recording_001"]["intervals"], [[0.0, 0.03], [1.0, 1.02]]
    )
    coverage.update(
        prepared_availability(
            {"recording_001": pd.DataFrame({"time": [0.0, 0.01]})}, ["pulse_rate"]
        )
    )
    result = tremor_outputs
    result["metadata"]["desktop_availability"] = coverage
    offsets = {
        "gait": {"recording_001": 2.0, "recording_002": 10.0},
        "tremor": {"recording_001": 2.0, "recording_002": 10.0},
        "pulse_rate": 0.0,
    }
    views, labels = availability_views(result, offsets)
    assert set(views) == {"preparation/gait_tremor", "preparation/pulse_rate"}
    np.testing.assert_allclose(views["preparation/gait_tremor"].time, [2.0, 3.0, 10.0])
    assert "Gait, Tremor" in labels[("preparation/gait_tremor", "available")]
    window._result_state.provenance = {"display_offsets": offsets}
    window.analyzed(result)
    names = [
        name for name, metric in window.selected_result_series() if name.startswith("preparation/")
    ]
    assert len(names) == 2
    assert not any(name.startswith("preparation/") for name in window._result_state.tables)
    axis = next(
        ax for ax in window.figure.axes if ax._paradigma_dataset == "preparation/gait_tremor"
    )
    assert axis._paradigma_binary
    assert len(axis.collections[0].get_paths()) == 3


def test_availability_matches_exact_prepared_inputs_and_excludes_discarded_sections(monkeypatch):
    from paradigma_studio import core

    times = np.r_[np.arange(100) / 100, 5.0, 5.01]
    raw = pd.DataFrame(
        {"time": times, **{f"gyroscope_{axis}": np.ones(len(times)) for axis in "xyz"}}
    )
    raw.loc[50, "gyroscope_x"] = np.nan
    captured = []

    def orchestrator(**kwargs):
        captured.append(kwargs["dfs"])
        return {"metadata": {}, "quantifications": {}, "aggregations": {}, "errors": []}

    monkeypatch.setattr(core, "run_paradigma", orchestrator)
    result = core.analyze(
        raw,
        pipelines=["tremor"],
        drop_missing_samples=True,
        split_by_gaps=True,
        max_gap_seconds=1.5,
        min_segment_seconds=0.1,
    )
    prepared = captured[0]
    assert isinstance(prepared, dict) and len(prepared) == 2  # Official missing-sample splitting.
    np.testing.assert_array_equal(pd.concat(prepared.values()).time, np.delete(times[:100], 50))
    coverage = result["metadata"]["desktop_availability"]["tremor"]
    assert sum(section["samples"] for section in coverage.values()) == 99
    np.testing.assert_allclose(
        [interval for section in coverage.values() for interval in section["intervals"]],
        [[0.0, 0.5], [0.51, 1.0]],
    )
    assert raw.gyroscope_x.isna().sum() == 1
