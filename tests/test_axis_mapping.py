"""Independent sensor signs and exact migration of legacy signed permutations."""

from itertools import permutations, product

import numpy as np
import pandas as pd
import pytest
from paradigma.prepare_data import correct_watch_orientation, prepare_raw_data

from paradigma_studio import core
from paradigma_studio.axis_mapping import (
    IMU_COLUMNS,
    migrate_legacy_orientation,
    preparation_orientations,
    sensor_orientation,
    validate_axis_inversions,
)

LEGACY_AXES = [
    [sign + axis for sign, axis in zip(signs, axes, strict=True)]
    for axes in permutations("xyz")
    for signs in product(("", "-"), repeat=3)
]


@pytest.mark.parametrize("axes", LEGACY_AXES)
@pytest.mark.parametrize("schema", ["canonical", "aliases", "mixed"])
def test_legacy_migration_matches_official_transform_for_every_signed_permutation(axes, schema):
    canonical = pd.DataFrame(
        {
            "time": np.arange(200) / 100,
            **{name: np.arange(200) + i for i, name in enumerate(IMU_COLUMNS)},
        }
    )
    names = {
        name: f"source_{name}"
        for i, name in enumerate(IMU_COLUMNS)
        if schema == "aliases" or (schema == "mixed" and i % 2)
    }
    source = canonical.rename(columns=names)
    original = source.copy(deep=True)
    mapping = {renamed: name for name, renamed in names.items()}
    legacy = correct_watch_orientation(source.rename(columns=mapping), axes)
    translated, inversions = migrate_legacy_orientation(mapping, axes)
    migrated = source.rename(columns=translated)
    for sensor, orientation in preparation_orientations({"axis_inversions": inversions}).items():
        migrated = correct_watch_orientation(migrated, orientation, sensor=sensor)
    pd.testing.assert_frame_equal(migrated, legacy, check_exact=True, check_like=True)
    pd.testing.assert_frame_equal(source, original, check_exact=True)


def test_migration_retains_unrelated_names_identities_and_invalid_name_collisions():
    mapping = {"clock": "time", "time": "aux_clock", "ppg": "green", "temperature": "temperature"}
    translated, signs = migrate_legacy_orientation(mapping, ["-y", "x", "z"])
    assert {key: translated[key] for key in mapping} == mapping
    assert signs == ["accelerometer_x", "gyroscope_x"]
    # A duplicate canonical source must remain a duplicate after translation.
    translated, _ = migrate_legacy_orientation({"ax": "accelerometer_x"}, ["y", "x", "z"])
    assert translated["ax"] == translated["accelerometer_x"] == "accelerometer_y"


def test_legacy_orientation_composes_with_existing_cross_axis_column_mapping():
    source = pd.DataFrame({name: [index + 1.0] for index, name in enumerate(IMU_COLUMNS)})
    mapping = {
        "accelerometer_x": "accelerometer_y",
        "accelerometer_y": "accelerometer_x",
        "gyroscope_z": "gyroscope_x",
        "gyroscope_x": "gyroscope_z",
    }
    expected = correct_watch_orientation(source.rename(columns=mapping), ["-z", "x", "-y"])
    translated, inversions = migrate_legacy_orientation(mapping, ["-z", "x", "-y"])
    actual = source.rename(columns=translated)
    for sensor, axes in preparation_orientations({"axis_inversions": inversions}).items():
        actual = correct_watch_orientation(actual, axes, sensor=sensor)
    pd.testing.assert_frame_equal(actual, expected, check_like=True, check_exact=True)


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
    from paradigma_studio.history import RunHistory, new_run

    history = RunHistory(tmp_path)
    record = new_run("sensor.csv", {"axis_inversions": inversions})
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
