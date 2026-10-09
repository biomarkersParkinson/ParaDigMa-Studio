"""Preparation, validation, missing data and independent recording sections."""

import numpy as np
import pandas as pd
import pytest

from paradigma_desktop import core


@pytest.mark.parametrize("prepared", [False, True])
def test_mapped_numeric_text_runs_real_tremor(synthetic_imu, prepared):
    source = synthetic_imu.rename(columns={"time": "timestamp", "gyroscope_x": "gyr_x"}).astype(str)
    original = source.copy()
    results = core.analyze(
        source,
        pipelines="tremor",
        skip_preparation=prepared,
        column_mapping={"timestamp": "time", "gyr_x": "gyroscope_x"},
    )
    assert results["errors"] == []
    assert len(results["quantifications"]["tremor"]) > 0
    pd.testing.assert_frame_equal(source, original)


def test_short_recording_reports_hidden_toolbox_failure(synthetic_imu):
    results = core.analyze(synthetic_imu.iloc[:30], pipelines=["tremor"])
    assert results["errors"]
    assert results["errors"][0]["pipeline"] == "tremor"
    assert "Classification failed" in results["errors"][0]["error"]
    assert results["quantifications"]["tremor"].empty


def test_gap_split_processes_contiguous_recordings_separately(synthetic_imu):
    synthetic_imu.loc[6000:, "time"] += 10
    results = core.analyze(synthetic_imu, pipelines=["tremor"], split_by_gaps=True)
    assert results["errors"] == []
    quantified = results["quantifications"]["tremor"]
    assert set(quantified["file_key"]) == {"segment_1", "segment_2"}
    # No interpolated windows may be manufactured inside the 10-second gap.
    assert not quantified["time"].between(60, 69.99).any()
    assert quantified.loc[quantified["file_key"] == "segment_2", "time"].min() >= 70


def test_preparation_preserves_selected_units_and_orientation(monkeypatch):
    captured = []

    def capture(**kwargs):
        captured.append(kwargs["dfs"])
        return {"errors": []}

    monkeypatch.setattr(core, "run_paradigma", capture)
    tremor = pd.DataFrame(
        {"time": np.arange(200) / 100, "gyroscope_x": 1.0, "gyroscope_y": 2.0, "gyroscope_z": 3.0}
    )
    core.analyze(
        tremor, pipelines=["tremor"], gyroscope_units="rad/s", device_orientation=["-y", "x", "z"]
    )
    assert captured[0]["gyroscope_x"].iloc[0] == pytest.approx(-2 * 180 / np.pi)
    assert captured[0]["gyroscope_y"].iloc[0] == pytest.approx(180 / np.pi)
    pulse = pd.DataFrame(
        {
            "time": np.arange(200) / 30,
            "green": 1.0,
            "accelerometer_x": 1.0,
            "accelerometer_y": 2.0,
            "accelerometer_z": 3.0,
        }
    )
    core.analyze(
        pulse,
        pipelines=["pulse_rate"],
        accelerometer_units="g",
        device_orientation=["-y", "x", "z"],
    )
    assert captured[1]["accelerometer_x"].iloc[0] == -2.0
    assert captured[1]["accelerometer_y"].iloc[0] == 1.0


def test_minimum_gap_segment_duration_uses_recording_rate(monkeypatch):
    captured = []
    monkeypatch.setattr(
        core, "run_paradigma", lambda **kwargs: captured.append(kwargs["dfs"]) or {"errors": []}
    )
    time = np.arange(180) / 30
    time[90:] += 10
    pulse = pd.DataFrame({"time": time, "green": 1.0, **{f"accelerometer_{a}": 1.0 for a in "xyz"}})
    core.analyze(pulse, pipelines=["pulse_rate"], split_by_gaps=True)
    assert [len(frame) for frame in captured[0].values()] == [90, 90]


def test_prepared_pulse_optional_accelerometer_text_is_converted():
    time = np.arange(3600) / 30
    frame = pd.DataFrame(
        {
            "time": time,
            "green": np.sin(2 * np.pi * 1.2 * time),
            "accelerometer_x": 0.01 * np.sin(time),
            "accelerometer_y": 0.01 * np.cos(time),
            "accelerometer_z": 1.0,
        }
    ).astype(str)
    results = core.analyze(frame, pipelines=["pulse_rate"], skip_preparation=True)
    assert results["errors"] == []
    # The quality classifier rejects synthetic PPG; conversion must still let
    # the real pipeline finish rather than fail on optional string channels.
    assert results["quantifications"]["pulse_rate"].empty


@pytest.mark.parametrize("mapping", [[], False, 0, ""])
def test_falsy_invalid_mapping_is_rejected(synthetic_imu, mapping):
    with pytest.raises(ValueError, match="JSON object"):
        core.analyze(synthetic_imu, pipelines=["tremor"], column_mapping=mapping)


@pytest.mark.parametrize("axes", [["--x", "y", "z"], ["x", "x", "z"]])
def test_invalid_axes_are_rejected_before_toolbox_execution(synthetic_imu, axes):
    with pytest.raises(ValueError, match="Device axes"):
        core.analyze(synthetic_imu, pipelines=["tremor"], device_orientation=axes)


def test_negative_time_differences_are_rejected(synthetic_imu):
    synthetic_imu["time"] = 0.01
    synthetic_imu.loc[1, "time"] = -0.01
    with pytest.raises(ValueError, match="Time differences"):
        core.analyze(synthetic_imu, pipelines=["tremor"], time_input_unit="difference_s")


def test_nullable_missing_samples_fail_with_clear_validation(synthetic_imu):
    synthetic_imu["gyroscope_x"] = synthetic_imu["gyroscope_x"].astype("Float64")
    synthetic_imu.loc[1, "gyroscope_x"] = pd.NA
    with pytest.raises(ValueError, match="missing values"):
        core.analyze(synthetic_imu, pipelines=["tremor"])


def test_datetime_samples_are_not_mistaken_for_numeric_seconds(synthetic_imu):
    synthetic_imu["time"] = pd.to_datetime(synthetic_imu["time"], unit="s")
    with pytest.raises(ValueError, match="convert datetime"):
        core.analyze(synthetic_imu, pipelines=["tremor"])


def test_absolute_time_with_custom_index_runs(synthetic_imu):
    synthetic_imu["time"] += 1_700_000_000
    synthetic_imu.index = pd.RangeIndex(20000, 32000)
    results = core.analyze(synthetic_imu, pipelines=["tremor"], time_input_unit="absolute_s")
    assert results["errors"] == []
    assert len(results["quantifications"]["tremor"]) > 0


def test_empty_error_lists_do_not_create_a_phantom_result():
    assert core.result_tables({"errors": []}) == {}
