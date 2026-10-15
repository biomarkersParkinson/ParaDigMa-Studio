"""Clock-only previews retain exact alignment semantics without result timelines."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from paradigma_studio import recordings
from paradigma_studio.exploration import source_timeline


def recording(unit="relative_s", *, day=0, clocks=True):
    origin = pd.Timestamp("2026-10-24T12:00:00.123456789", tz="Europe/Amsterdam")
    seconds = np.arange(5, dtype=float)
    values = np.full(5, 0.125) if unit.startswith("difference") else seconds + 1000
    if unit.startswith("absolute"):
        values = origin.timestamp() + seconds
    frame = pd.DataFrame(
        {
            "device_time": values * (1000 if unit.endswith("ms") else 1),
            "green": [1.0, np.nan, 1.0, 1.0, 1.0],
            **{f"accelerometer_{axis}": [np.nan, 1.0, 1.0, 1.0, 1.0] for axis in "xyz"},
            **{f"gyroscope_{axis}": [np.nan, np.nan, 1.0, 1.0, 1.0] for axis in "xyz"},
        }
    )
    if clocks:
        frame["time_dt"] = origin + pd.to_timedelta(day * 86400 + seconds, unit="s")
    return frame


@pytest.mark.parametrize(
    "unit",
    ["relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"],
)
@pytest.mark.parametrize("drop_missing", [False, True])
@pytest.mark.parametrize(
    "modules", [["gait"], ["tremor"], ["pulse_rate"], ["gait", "tremor", "pulse_rate"]]
)
def test_clock_only_batch_preview_matches_full_alignment_exactly_without_mutating_inputs(
    unit, drop_missing, modules, monkeypatch
):
    frames = {"first": recording(unit), "second": recording(unit, day=1)}
    original = deepcopy(frames)
    settings = {
        "pipelines": modules,
        "time_input_unit": unit,
        "column_mapping": {"device_time": "time"},
        "drop_missing_samples": drop_missing,
    }
    expected = recordings.align_recordings(frames, settings, {})[3]

    def unexpected(*args, **kwargs):
        pytest.fail("A clock preview must not construct result-group alignments")

    monkeypatch.setattr(recordings, "analysis_alignment", unexpected)
    assert recordings.preview_recording_clock(frames, settings) == expected
    for key, frame in frames.items():
        pd.testing.assert_frame_equal(frame, original[key], check_exact=True)


@pytest.mark.parametrize("clock_kind", ["none", "mixed", "incompatible", "metadata", "prepared"])
def test_clock_only_preview_preserves_unknown_metadata_and_prepared_clocks(clock_kind):
    frames = {"first": recording(clocks=False), "second": recording(day=1, clocks=False)}
    if clock_kind == "mixed":
        frames["first"]["time_dt"] = pd.date_range("2026-10-24", periods=5, freq="s")
    elif clock_kind == "incompatible":
        frames["first"]["time_dt"] = pd.date_range("2026-10-24", periods=5, freq="s")
        frames["second"]["time_dt"] = pd.date_range("2026-10-25", periods=5, freq="s", tz="UTC")
    elif clock_kind in ("metadata", "prepared"):
        for index, frame in enumerate(frames.values()):
            frame.attrs["desktop_recording_start"] = f"2026-10-{24 + index}T12:00:00+02:00"
    settings = {
        "pipelines": ["gait", "tremor", "pulse_rate"],
        "column_mapping": {"device_time": "time"},
        "drop_missing_samples": True,
        "skip_preparation": clock_kind == "prepared",
    }
    assert (
        recordings.preview_recording_clock(frames, settings)
        == recordings.align_recordings(frames, settings, {})[3]
    )


@pytest.mark.parametrize("dtype", ["float64", "Float64", "object"])
def test_channelwise_validity_keeps_the_first_retained_absolute_sample_and_input_values(dtype):
    frame = recording("absolute_s").drop(columns="time_dt").rename(columns={"device_time": "time"})
    if dtype == "object":
        frame = frame.astype(str)
        frame = frame.replace("nan", np.nan)
    else:
        frame = frame.astype(dtype)
    original = frame.copy(deep=True)
    settings = {"time_input_unit": "absolute_s", "drop_missing_samples": True}
    for modules, first in (([], 0), (["pulse_rate"], 2), (["tremor"], 2), (["gait"], 2)):
        timeline = source_timeline(frame, {**settings, "pipelines": modules})
        np.testing.assert_array_equal(timeline, np.arange(5) - first)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
