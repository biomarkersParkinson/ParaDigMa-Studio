"""Visible source selections own processing; original sensor frames stay intact."""

import numpy as np
import pandas as pd
import pytest
from PySide6.QtTest import QSignalSpy

from paradigma_studio import core
from paradigma_studio.column_mapping import SIGNALS, apply_signal_columns, validate_signal_columns
from paradigma_studio.exploration import source_timeline
from paradigma_studio.history import RunHistory, load_result_export, new_run
from paradigma_studio.results_view import recording_clock
from paradigma_studio.serialization import export_results


def selections(**sources):
    return {**dict.fromkeys(SIGNALS), **sources}


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("split_by_gaps", [False, True])
def test_manual_choices_replace_named_defaults_in_preparation_and_timelines(
    window, prepared, split_by_gaps
):
    # Keep the selected 4 Hz signal above the default 1.5-second section minimum.
    samples = np.arange(8, dtype=float)
    frame = pd.DataFrame(
        {
            "time": 100 * (samples + 1),
            "device_clock": samples / 4,
            "green": np.nan,
            "optical": samples + 2,
            "temperature": samples + 30,
        }
    )
    original = frame.copy(deep=True)
    window.loaded(("sensor.csv", frame))
    window.set_modules(["pulse_rate"])
    assert window.mapping.model.choices["time"] == "time"
    assert window.mapping.model.choices["green"] == "green"
    for target, source in (("time", "device_clock"), ("green", "optical")):
        selector = window.mapping._combos[target]
        selector.setCurrentIndex(selector.findData(source))
        assert window.mapping._warnings[target].isHidden()
    window.gaps.setChecked(split_by_gaps)
    window.prepared.setChecked(prepared)
    settings = window._analysis_controller._analysis_settings(["pulse_rate"])
    assert settings["split_by_gaps"] == (split_by_gaps and not prepared)
    assert settings["signal_columns"] == selections(time="device_clock", green="optical")
    assert window.mapping.model.validate(["pulse_rate"]).compatible == 1
    actual, exclusion, count = core._prepare_recording(
        frame, ["pulse_rate"], settings["column_mapping"], None, False, settings
    )
    if settings["split_by_gaps"]:
        assert set(actual) == {"segment_1"}
        actual = actual["segment_1"].drop(columns="data_segment_nr")
    expected = pd.DataFrame(
        {"time": frame.device_clock, "green": frame.optical, "temperature": frame.temperature}
    )
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    np.testing.assert_array_equal(source_timeline(frame, settings), frame.device_clock)
    assert exclusion is None and count == len(frame)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


@pytest.mark.parametrize("selected", [None, "missing_optical"])
def test_absent_selection_never_falls_back_to_a_present_standard_column(selected):
    frame = pd.DataFrame({"time": [0.0, 1.0], "green": [1.0, 2.0]})
    original = frame.copy(deep=True)
    settings = {"skip_preparation": True, "signal_columns": selections(time="time", green=selected)}
    mapped = apply_signal_columns(frame, {}, settings["signal_columns"])
    assert list(mapped.columns) == ["time"]
    with pytest.raises(ValueError, match="Missing sensor columns: green"):
        core._prepare_recording(frame, ["pulse_rate"], {}, None, False, settings)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


def test_explicit_not_included_survives_loads_and_auto_match_can_restore_it(window):
    window.mapping.set_recordings({"one": ["time", "green"]}, {})
    window.mapping.set_modules(["pulse_rate"])
    selector = window.mapping._combos["green"]
    changes = QSignalSpy(window.mapping.changed)
    selector.setCurrentIndex(selector.findData(None))
    window.mapping.set_recordings({"two": ["time", "green"]}, {})
    assert selector.currentText() == "Not included"
    assert window.mapping.signal_columns()["green"] is None
    assert window.mapping.model.validate(["pulse_rate"]).compatible == 0
    assert not window.mapping._warnings["green"].isHidden()
    assert window.mapping.default_button.isEnabled()
    assert changes.count() == 1
    window.mapping.default_button.click()
    assert selector.currentData() == "green"
    assert window.mapping.model.validate(["pulse_rate"]).compatible == 1
    assert window.mapping._warnings["green"].isHidden()
    assert changes.count() == 2


def test_absolute_clock_uses_the_selected_source_and_ignores_the_original_time():
    frame = pd.DataFrame({"time": [10.0, 20.0], "device_clock": [1700000000.0, 1700000001.0]})
    settings = {
        "time_input_unit": "absolute_s",
        "column_mapping": {"device_clock": "time"},
        "signal_columns": selections(time="device_clock"),
    }
    np.testing.assert_array_equal(source_timeline(frame, settings), [0.0, 1.0])
    clock = recording_clock(frame, settings)
    assert pd.Timestamp(clock["origin"]) == pd.Timestamp(1700000000, unit="s", tz="UTC")
    assert clock["source"] == "absolute_s"


def test_old_runs_without_selections_retain_literal_rename_semantics():
    frame = pd.DataFrame({"time": [0.0, 1.0], "green": [1.0, 2.0], "ppg": [3.0, 4.0]})
    legacy = apply_signal_columns(frame, {"ppg": "green"})
    assert legacy.columns.tolist() == ["time", "green", "green"]
    current = apply_signal_columns(frame, {"ppg": "green"}, selections(time="time", green="ppg"))
    pd.testing.assert_series_equal(current.green, frame.ppg.rename("green"), check_exact=True)
    assert current.columns.is_unique


def test_filtering_unselected_signals_reuses_arrays_and_preserves_recording_metadata():
    frame = pd.DataFrame({"time": [10.0, 20.0], "clock": [0.0, 1.0], "green": [2.0, 3.0]})
    frame.attrs["desktop_recording_start"] = "2026-10-22T12:00:00Z"
    frame.columns.name = "Signals"
    mapped = apply_signal_columns(frame, {}, selections(time="clock", green="green"))
    assert np.shares_memory(mapped.time.to_numpy(), frame.clock.to_numpy())
    assert np.shares_memory(mapped.green.to_numpy(), frame.green.to_numpy())
    assert mapped.attrs == frame.attrs
    assert mapped.columns.name == frame.columns.name


def test_duplicate_names_for_a_selected_source_remain_an_error():
    frame = pd.DataFrame(
        [[0.0, 10.0, 1.0, 2.0], [1.0, 20.0, 3.0, 4.0]],
        columns=["time", "green", "ppg", "ppg"],
    )
    settings = {"skip_preparation": True, "signal_columns": selections(time="time", green="ppg")}
    with pytest.raises(ValueError, match="duplicate column names"):
        core._prepare_recording(frame, ["pulse_rate"], {}, None, False, settings)


def test_official_pipeline_receives_only_selected_signals_without_studio_settings(monkeypatch):
    frame = pd.DataFrame(
        {
            "time": [100.0, 200.0],
            "clock": [0.0, 1.0],
            "gyroscope_x": [np.nan, np.nan],
            "selected_x": [1.0, 2.0],
            "gyroscope_y": [3.0, 4.0],
            "gyroscope_z": [5.0, 6.0],
        }
    )
    expected = pd.DataFrame(
        {
            "time": frame.clock,
            "gyroscope_x": frame.selected_x,
            "gyroscope_y": frame.gyroscope_y,
            "gyroscope_z": frame.gyroscope_z,
        }
    )
    calls = []

    def capture(**kwargs):
        assert "signal_columns" not in kwargs
        pd.testing.assert_frame_equal(kwargs["dfs"], expected, check_exact=True)
        calls.append(True)
        return {"errors": []}

    monkeypatch.setattr(core, "run_paradigma", capture)
    result = core.analyze(
        frame,
        pipelines=["tremor"],
        skip_preparation=True,
        signal_columns=selections(
            time="clock",
            gyroscope_x="selected_x",
            gyroscope_y="gyroscope_y",
            gyroscope_z="gyroscope_z",
        ),
    )
    assert result["errors"] == [] and calls == [True]


@pytest.mark.parametrize("split_by_gaps", [False, True])
def test_saved_selections_restore_atomically_and_keep_not_included(
    window, tmp_path, synthetic_imu, split_by_gaps
):
    frame = synthetic_imu.assign(device_clock=synthetic_imu.time, device_gyro=2.0, green=np.nan)
    window.loaded(("sensor.csv", frame))
    window.set_modules(["tremor"])
    window.gaps.setChecked(split_by_gaps)
    for target, source in (
        ("time", "device_clock"),
        ("gyroscope_x", "device_gyro"),
        ("green", None),
    ):
        selector = window.mapping._combos[target]
        selector.setCurrentIndex(selector.findData(source))
    settings = window._analysis_controller._analysis_settings(["tremor"])
    path = tmp_path / "saved.json"
    export_results(path, {"errors": []}, {"settings": settings})
    provenance, _ = load_result_export(path)
    record = new_run("sensor.csv", provenance["settings"])
    history = RunHistory(tmp_path / "history")
    history.save(record)
    records, issues = history.load()
    assert issues == [] and records[0]["settings"]["signal_columns"] == settings["signal_columns"]
    window.mapping.auto_match()
    window.gaps.setChecked(not split_by_gaps)
    changes = QSignalSpy(window.mapping.changed)
    window._run_state.selected_run = record
    window.use_run_parameters()
    assert changes.count() == 1
    assert window.mapping.signal_columns() == settings["signal_columns"]
    assert window.mapping._combos["green"].currentText() == "Not included"
    restored = window._analysis_controller._analysis_settings(["tremor"])
    assert restored["split_by_gaps"] == split_by_gaps
    actual, _, _ = core._prepare_recording(
        frame, ["tremor"], restored["column_mapping"], None, False, restored
    )
    if split_by_gaps:
        assert set(actual) == {"segment_1"}
        actual = actual["segment_1"]
    assert "green" not in actual
    np.testing.assert_array_equal(actual.gyroscope_x, frame.device_gyro)
    np.testing.assert_array_equal(actual.time, frame.device_clock)


@pytest.mark.parametrize(
    "invalid",
    [{}, {"time": "clock"}, {**selections(), "green": 1}, selections(time="same", green="same")],
)
def test_invalid_signal_selections_are_rejected_before_processing_and_in_saved_runs(
    tmp_path, invalid
):
    with pytest.raises(ValueError, match="Signal columns|multiple signals"):
        validate_signal_columns(invalid)
    history = RunHistory(tmp_path)
    record = new_run("sensor.csv", {"signal_columns": invalid})
    history.save(record)
    records, issues = history.load()
    assert records == []
    assert len(issues) == 1
    assert "Signal columns" in issues[0] or "multiple signals" in issues[0]
