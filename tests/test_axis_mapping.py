"""Independent sensor signs and the supported Python axis API."""

import pandas as pd
import pytest
from paradigma.prepare_data import correct_watch_orientation, prepare_raw_data
from run_fixtures import make_run

from paradigma_studio import core
from paradigma_studio.axis_mapping import (
    preparation_orientations,
    sensor_orientation,
    validate_axis_inversions,
)


@pytest.mark.parametrize("invalid", ["x", ["x"], ["green"], [None], ["gyroscope_x"] * 2, {}])
def test_invalid_axis_inversions_are_rejected(invalid):
    with pytest.raises(ValueError, match="Axis inversions"):
        validate_axis_inversions(invalid)


def test_new_axis_settings_require_mapping_for_swaps_and_keep_sensor_signs_independent():
    with pytest.raises(ValueError, match="Use column mapping"):
        preparation_orientations({"device_orientation": ["y", "x", "z"], "axis_inversions": []})
    assert preparation_orientations({"axis_inversions": ["gyroscope_y", "accelerometer_x"]}) == {
        "accelerometer": ["-x", "y", "z"],
        "gyroscope": ["x", "-y", "z"],
    }
    assert preparation_orientations({"device_orientation": None}) == {
        "accelerometer": None,
        "gyroscope": None,
    }
    with pytest.raises(ValueError, match="Select accelerometer or gyroscope"):
        sensor_orientation("green", [])


@pytest.mark.parametrize(
    "inversions,valid",
    [([], True), (["accelerometer_x"], True), (["green"], False), (["gyroscope_x"] * 2, False)],
)
def test_history_accepts_valid_axis_settings_and_reports_corrupt_settings(
    tmp_path, inversions, valid
):
    from paradigma_studio.history import RunHistory

    history = RunHistory(tmp_path)
    record = make_run("sensor.csv", {"axis_inversions": inversions})
    record["status"] = "Completed"
    history.save(record)
    records, issues = history.load()
    if valid:
        assert records == [record] and issues == []
    else:
        assert records == [] and len(issues) == 1
        assert "Axis inversions" in issues[0]


@pytest.mark.parametrize("modules", [["gait"], ["gait", "pulse_rate"]])
@pytest.mark.parametrize("prepared", [False, True])
def test_analysis_routes_mapped_sensor_signs_once_and_never_forwards_desktop_setting(
    synthetic_imu, monkeypatch, modules, prepared
):
    source = synthetic_imu.assign(
        green=1.0, accelerometer_x=0.2, accelerometer_y=0.4, accelerometer_z=1.0
    )
    original = source.copy(deep=True)
    mapping = {"accelerometer_y": "accelerometer_x", "accelerometer_x": "accelerometer_y"}
    calls = []

    def capture(**kwargs):
        assert "axis_inversions" not in kwargs
        calls.append(kwargs["dfs"])
        return {"errors": []}

    monkeypatch.setattr(core, "run_paradigma", capture)
    settings = {"axis_inversions": ["accelerometer_x", "gyroscope_y"], "skip_preparation": prepared}
    result = core.analyze(source, pipelines=modules, column_mapping=mapping, **settings)
    assert result["errors"] == []
    reference = source.rename(columns=mapping)
    if not prepared:
        reference = prepare_raw_data(reference, accelerometer_units="g", device_orientation=None)
        reference = correct_watch_orientation(reference, ["-x", "y", "z"], sensor="accelerometer")
        reference = correct_watch_orientation(reference, ["x", "-y", "z"], sensor="gyroscope")
    assert len(calls) == (2 if "pulse_rate" in modules else 1)
    for actual in calls:
        pd.testing.assert_frame_equal(actual, reference, check_exact=True)
    pd.testing.assert_frame_equal(source, original, check_exact=True)
