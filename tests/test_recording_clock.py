"""Automatic origins use selected absolute time or explicit recording-start metadata."""

from copy import deepcopy
from importlib.resources import files

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_previews

from paradigma_studio.column_mapping import SIGNALS
from paradigma_studio.core import load_sensor_file
from paradigma_studio.recordings import align_recordings, preview_recording_clock
from paradigma_studio.results_view import recording_clock


def settings(unit="relative_s"):
    choices = dict.fromkeys(SIGNALS)
    choices["time"] = "selected_clock"
    return {"time_input_unit": unit, "signal_columns": choices}


@pytest.mark.parametrize(
    "unit",
    ["relative_s", "relative_ms", "difference_s", "difference_ms", "absolute_s", "absolute_ms"],
)
@pytest.mark.parametrize("metadata", [False, True])
@pytest.mark.parametrize("dates_first", [False, True])
def test_unselected_date_columns_never_change_automatic_origin(unit, metadata, dates_first):
    epoch = pd.Timestamp("2026-10-23T12:00:00Z")
    start = pd.Timestamp("2026-10-24T08:00:00.123456789", tz="Europe/Amsterdam")
    seconds = np.array([5.0, 6.0, 8.0])
    if unit.startswith("absolute"):
        seconds = epoch.timestamp() + np.array([0.0, 1.0, 3.0])
    elif unit.startswith("difference"):
        seconds = np.array([5.0, 1.0, 2.0])
    selected = seconds * (1000 if unit.endswith("ms") else 1)
    frame = pd.DataFrame({"selected_clock": selected, "time": [0.0, 10.0, 20.0]})
    if metadata:
        frame.attrs["desktop_recording_start"] = start.isoformat()
    expected = (
        epoch
        if unit.startswith("absolute")
        else start - pd.Timedelta(5, unit="s")
        if metadata
        else None
    )
    baseline = recording_clock(frame, settings(unit))
    assert (pd.Timestamp(baseline["origin"]) if baseline else None) == expected
    for name in ("date_of_birth", "time_dt", "datetime", "timestamp"):
        for as_text in (False, True):
            extra = frame.copy(deep=True)
            extra[name] = ["1980-01-01"] * 3 if as_text else pd.date_range("1980-01-01", periods=3)
            if dates_first:
                extra = extra[[name, *frame.columns]]
            original = deepcopy(extra)
            assert recording_clock(extra, settings(unit)) == baseline
            pd.testing.assert_frame_equal(extra, original, check_exact=True)
            assert extra.attrs == original.attrs


@pytest.mark.parametrize("extension", ["csv", "parquet", "pkl"])
@pytest.mark.parametrize("unit", ["relative_s", "absolute_s"])
def test_generic_imports_do_not_turn_an_unselected_time_dt_into_start_metadata(
    tmp_path, extension, unit
):
    start = pd.Timestamp("2026-10-23T12:00:00Z")
    seconds = np.arange(3.0) + (start.timestamp() if unit == "absolute_s" else 0)
    frame = pd.DataFrame(
        {"selected_clock": seconds, "time_dt": pd.date_range("1980-01-01", periods=3)}
    )
    path = tmp_path / f"recording.{extension}"
    getattr(frame, {"csv": "to_csv", "parquet": "to_parquet", "pkl": "to_pickle"}[extension])(
        path, **({"index": False} if extension != "pkl" else {})
    )
    before = path.read_bytes()
    loaded = load_sensor_file(path, allow_pickle=extension == "pkl")
    assert "desktop_recording_start" not in loaded.attrs
    clock = recording_clock(loaded, settings(unit))
    assert (pd.Timestamp(clock["origin"]) if clock else None) == (
        start if unit == "absolute_s" else None
    )
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "name,start",
    [
        ("test_data.CWA", "2025-11-17T09:00:02.324188160"),
        ("test_data.avro", "2025-11-26T10:41:54.256034"),
    ],
)
def test_device_importers_declare_their_precise_start_without_relying_on_date_columns(name, start):
    frame = load_sensor_file(files("paradigma_studio") / "data" / name)
    expected = pd.Timestamp(start)
    assert pd.Timestamp(frame.attrs["desktop_recording_start"]) == expected
    frame["time_dt"] = pd.Timestamp("1980-01-01")
    clock = recording_clock(frame, {"time_input_unit": "relative_s"})
    assert pd.Timestamp(clock["origin"]) == expected
    assert clock["source"] == "Recording metadata"


def test_tsdf_declared_start_still_prefills_after_scaling(tsdf_writer):
    path = tsdf_writer(pd.DataFrame({"time": [0, 10, 20], "gyroscope_x": [1, 2, 3]}))
    frame = load_sensor_file(path)
    frame["date_of_birth"] = pd.Timestamp("1980-01-01")
    clock = recording_clock(frame, {"time_input_unit": "relative_ms"})
    assert pd.Timestamp(clock["origin"]) == pd.Timestamp("2026-10-13T10:00:00Z")


@pytest.mark.parametrize("start", ["invalid", "NaT", None])
def test_unusable_metadata_does_not_fall_back_to_unselected_dates(start):
    frame = pd.DataFrame({"time": [0.0, 1.0], "time_dt": pd.date_range("1980-01-01", periods=2)})
    frame.attrs["desktop_recording_start"] = start
    assert recording_clock(frame, {"time_input_unit": "relative_s"}) is None


def test_batch_preview_and_results_align_only_from_declared_start_metadata():
    frames = {}
    for day in (24, 25):
        start = pd.Timestamp(f"2026-10-{day}T12:00:00.123456789", tz="Europe/Amsterdam")
        frame = pd.DataFrame(
            {"selected_clock": [0.0, 1.0, 2.0], "time_dt": pd.date_range("1980-01-01", periods=3)}
        )
        frame.attrs["desktop_recording_start"] = start
        frames[str(day)] = frame
    config = settings()
    aligned = align_recordings(frames, config, {})
    assert preview_recording_clock(frames, config) == aligned[3]
    assert aligned[3]["timezone"] == "Europe/Amsterdam"
    assert pd.Timestamp(aligned[3]["origin"]) == pd.Timestamp("2026-10-24T12:00:00.123456789+02:00")
    assert aligned[4] == {"24": 0.0, "25": 25 * 3600.0}
    for frame in frames.values():
        frame.attrs.clear()
    assert preview_recording_clock(frames, config) is None
    elapsed = align_recordings(frames, config, {})
    assert elapsed[3] is None and elapsed[4] == {"24": 0.0, "25": 3.0}


def test_analyze_prefill_default_manual_override_and_results_share_the_selected_clock(
    window, tremor_outputs
):
    start = pd.Timestamp("2026-10-23T12:00:00Z")
    frame = pd.DataFrame(
        {
            "time": start.timestamp() + np.arange(3.0),
            "time_dt": pd.date_range("1980-01-01", periods=3),
            **{f"gyroscope_{axis}": [1.0, 2.0, 3.0] for axis in "xyz"},
        }
    )
    window.loaded(("sensor.csv", frame))
    window.set_modules(["tremor"])
    window.time.setCurrentText("absolute_s")
    wait_for_previews(window)
    assert pd.Timestamp(window.clock_input.text()) == start
    badge = window._analysis_controller.view.file_badges["Time origin"]
    assert not badge.isHidden()
    window._result_state.provenance = {"settings": {"time_input_unit": "absolute_s"}}
    window.analyzed(tremor_outputs)
    assert pd.Timestamp(window._result_state.display_clock["origin"]) == start
    window.clock_input.setText("2020-01-01T00:00:00Z")
    window.origin_edited()
    window.time.setCurrentText("relative_s")
    wait_for_previews(window)
    assert window.clock_input.text() == "2020-01-01T00:00:00Z"
    window.reset_origin()
    wait_for_previews(window)
    assert window.clock_input.text() == "" and badge.isHidden()
