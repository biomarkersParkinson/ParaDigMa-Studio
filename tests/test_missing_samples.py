"""Exclusion must preserve time and never bridge missing stretches."""

from importlib.resources import files

import numpy as np
import pandas as pd
import pytest

from paradigma_studio import core


def recording():
    return pd.DataFrame(
        {"time": np.arange(20) / 10, **{f"gyroscope_{axis}": np.ones(20) for axis in "xyz"}}
    )


@pytest.mark.parametrize("prepared", [False, True])
def test_exclusion_preserves_source_and_separates_missing_run(monkeypatch, prepared):
    frame = recording()
    frame.loc[8:9, "gyroscope_x"] = np.nan
    original = frame.copy()
    captured = []
    monkeypatch.setattr(
        core, "run_paradigma", lambda **kwargs: captured.append(kwargs) or {"errors": []}
    )
    result = core.analyze(
        frame, pipelines="tremor", drop_missing_samples=True, skip_preparation=prepared
    )
    sections = list(captured[0]["dfs"].values())
    assert [len(section) for section in sections] == [8, 10]
    assert sections[0].time.iloc[-1] == 0.7
    assert sections[1].time.iloc[0] == 1.0
    assert all(
        np.isfinite(section.filter(regex="time|gyroscope").to_numpy()).all() for section in sections
    )
    assert result["metadata"]["desktop_preparation"]["excluded_samples"] == 2
    assert "drop_missing_samples" not in captured[0]
    pd.testing.assert_frame_equal(frame, original)


def test_gap_splitting_does_not_erase_missing_sample_boundaries(monkeypatch):
    frame = recording()
    frame.loc[8:9, "gyroscope_z"] = np.inf
    frame.loc[15:, "time"] += 10
    captured = []
    monkeypatch.setattr(
        core, "run_paradigma", lambda **kwargs: captured.append(kwargs["dfs"]) or {"errors": []}
    )
    core.analyze(
        frame,
        pipelines="tremor",
        drop_missing_samples=True,
        split_by_gaps=True,
        min_segment_seconds=0.1,
    )
    assert [len(section) for section in captured[0].values()] == [8, 5, 5]


@pytest.mark.parametrize("unit,step", [("difference_s", 0.1), ("difference_ms", 100.0)])
def test_excluding_sensor_rows_keeps_difference_timeline(monkeypatch, unit, step):
    frame = recording()
    frame["time"] = step
    frame.loc[0, "time"] = 0
    frame.loc[8:9, "gyroscope_y"] = np.nan
    captured = []
    monkeypatch.setattr(
        core, "run_paradigma", lambda **kwargs: captured.append(kwargs["dfs"]) or {"errors": []}
    )
    core.analyze(frame, pipelines="tremor", drop_missing_samples=True, time_input_unit=unit)
    sections = list(captured[0].values())
    assert sections[1].time.iloc[0] == pytest.approx(1.0)
    assert sections[1].time.iloc[-1] == pytest.approx(1.9)


def test_missing_difference_time_is_not_guessed():
    frame = recording()
    frame["time"] = 0.1
    frame.loc[0, "time"] = 0
    frame.loc[8, "time"] = np.nan
    with pytest.raises(ValueError, match="Missing time differences cannot be excluded"):
        core.analyze(
            frame, pipelines="tremor", drop_missing_samples=True, time_input_unit="difference_s"
        )


def test_missing_optional_columns_do_not_drop_valid_required_samples(monkeypatch):
    frame = recording()
    frame["extra"] = np.nan
    captured = []
    monkeypatch.setattr(
        core, "run_paradigma", lambda **kwargs: captured.append(kwargs["dfs"]) or {"errors": []}
    )
    core.analyze(frame, pipelines="tremor", drop_missing_samples=True)
    assert len(captured[0]) == len(frame)


def test_existing_segments_remain_separate_after_exclusion(monkeypatch):
    frame = recording()
    frame["data_segment_nr"] = [1] * 15 + [2] * 5
    frame.loc[8:9, "gyroscope_x"] = np.nan
    captured = []
    monkeypatch.setattr(
        core, "run_paradigma", lambda **kwargs: captured.append(kwargs["dfs"]) or {"errors": []}
    )
    core.analyze(frame, pipelines="tremor", drop_missing_samples=True)
    assert [len(section) for section in captured[0].values()] == [8, 5, 5]


def test_exclusion_that_leaves_no_useful_samples_reports_why():
    frame = recording()
    frame.loc[:, "gyroscope_x"] = np.nan
    with pytest.raises(ValueError, match="At least two valid samples"):
        core.analyze(frame, pipelines="tremor", drop_missing_samples=True)
    frame = recording().iloc[:3]
    with pytest.raises(ValueError, match="All segments were removed"):
        core.analyze(frame, pipelines="tremor", split_by_gaps=True)


def test_physilog_excerpt_runs_gait_and_reports_exclusion():
    frame = core.load_sensor_file(files("paradigma_studio") / "data" / "physilog_excerpt.parquet")
    assert len(frame) == 12010
    original = frame.copy()
    result = core.analyze(
        frame, pipelines="gait", drop_missing_samples=True, split_by_gaps=True, watch_side="left"
    )
    assert result["errors"] == []
    details = result["metadata"]["desktop_preparation"]
    assert details["excluded_samples"] == 10
    assert details["analyzed_samples"] == 12000
    assert details["continuous_sections"] == 4
    assert not result["quantifications"]["gait"]["unfiltered"].empty
    pd.testing.assert_frame_equal(frame, original)
