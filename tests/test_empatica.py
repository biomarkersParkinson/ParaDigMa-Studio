"""Real Empatica example and encoded Avro import regressions."""

import copy
import json
from importlib.resources import files

import numpy as np
import pandas as pd
import pytest
from avro import schema
from avro.datafile import DataFileWriter
from avro.io import DatumWriter

from paradigma_studio.core import analyze, load_sensor_file


def write_avro(path, records):
    # Small independent recordings with the metadata fields used by the loader.
    params = {
        "type": "record",
        "name": "ImuParams",
        "fields": [
            {"name": name, "type": "double"}
            for name in (
                "physicalMin",
                "physicalMax",
                "digitalMin",
                "digitalMax",
                "conversionFactor",
            )
        ],
    }
    motion = {
        "type": "record",
        "name": "Motion",
        "fields": [
            {"name": "timestampStart", "type": "long"},
            {"name": "samplingFrequency", "type": "double"},
            {"name": "imuParams", "type": params},
            *[{"name": axis, "type": {"type": "array", "items": "double"}} for axis in "xyz"],
        ],
    }
    shape = {
        "type": "record",
        "name": "Empatica",
        "fields": [
            {
                "name": "schemaVersion",
                "type": {
                    "type": "record",
                    "name": "Version",
                    "fields": [
                        {"name": name, "type": "int"} for name in ("major", "minor", "patch")
                    ],
                },
            },
            {
                "name": "rawData",
                "type": {
                    "type": "record",
                    "name": "RawData",
                    "fields": [
                        {"name": "accelerometer", "type": motion},
                        {"name": "gyroscope", "type": ["null", "Motion"], "default": None},
                    ],
                },
            },
        ],
    }
    with path.open("wb") as stream:
        with DataFileWriter(stream, DatumWriter(), schema.parse(json.dumps(shape))) as writer:
            for record in records:
                writer.append(record)
    return path


@pytest.fixture
def record():
    sensor = {
        "timestampStart": 1700000000000123,
        "samplingFrequency": 10.0,
        "imuParams": {
            "physicalMin": -2.0,
            "physicalMax": 2.0,
            "digitalMin": -100.0,
            "digitalMax": 100.0,
            "conversionFactor": 0.02,
        },
        "x": [1.0, 2.0, 3.0],
        "y": [4.0, 5.0, 6.0],
        "z": [7.0, 8.0, 9.0],
    }
    return {
        "schemaVersion": {"major": 6, "minor": 5, "patch": 0},
        "rawData": {"accelerometer": sensor, "gyroscope": None},
    }


def test_official_empatica_example_opens_without_gyro():
    frame = load_sensor_file(files("paradigma_studio") / "data" / "test_data.avro")
    assert len(frame) == 115904
    assert set(frame) == {"time", "time_dt", *{f"accelerometer_{axis}" for axis in "xyz"}}
    assert frame.time.iloc[0] == 0
    assert frame.time.is_unique and frame.time.is_monotonic_increasing
    assert frame.time_dt.iloc[0] == pd.Timestamp("2025-11-26 10:41:54.256034")
    assert frame.accelerometer_x.iloc[0] == pytest.approx(-2048 * 0.0004879999905824661)
    assert frame.attrs["sampling_frequency"] == pytest.approx(63.99989700317383)
    for pipeline in ("gait", "tremor"):
        with pytest.raises(ValueError, match="require gyroscope samples"):
            analyze(frame, pipelines=[pipeline])
    with pytest.raises(ValueError, match="raw green PPG"):
        analyze(frame, pipelines=["pulse_rate"])


@pytest.mark.parametrize("version", [(6, 4, 0), (6, 5, 0)])
def test_optional_gyro_uses_own_scaling(tmp_path, record, version):
    record["schemaVersion"] = dict(zip(("major", "minor", "patch"), version))
    gyro = copy.deepcopy(record["rawData"]["accelerometer"])
    gyro["imuParams"].update(physicalMin=-50.0, physicalMax=50.0, conversionFactor=0.5)
    record["rawData"]["gyroscope"] = gyro
    if version < (6, 5, 0):
        # Old schemas must use ranges, even if a newer factor is present.
        record["rawData"]["accelerometer"]["imuParams"]["conversionFactor"] = 99.0
        gyro["imuParams"]["conversionFactor"] = 88.0
    else:
        # New schemas must use factors independently of legacy ranges.
        record["rawData"]["accelerometer"]["imuParams"]["physicalMax"] = 200.0
        gyro["imuParams"]["physicalMax"] = 200.0
    frame = load_sensor_file(write_avro(tmp_path / "aligned.avro", [record]))
    np.testing.assert_allclose(frame.accelerometer_x, [0.02, 0.04, 0.06])
    np.testing.assert_allclose(frame.gyroscope_x, [0.5, 1.0, 1.5])
    np.testing.assert_allclose(frame.time, [0.0, 0.1, 0.2])
    assert frame.time_dt.iloc[0] == pd.Timestamp(1700000000000123, unit="us")


@pytest.mark.parametrize("empty_gyro", [None, "empty"])
def test_absent_or_empty_gyro_is_optional(tmp_path, record, empty_gyro):
    if empty_gyro == "empty":
        gyro = copy.deepcopy(record["rawData"]["accelerometer"])
        gyro.update(x=[], y=[], z=[], samplingFrequency=0.0, timestampStart=0)
        record["rawData"]["gyroscope"] = gyro
    frame = load_sensor_file(write_avro(tmp_path / "accel.avro", [record]))
    assert len(frame) == 3
    assert not any(column.startswith("gyroscope") for column in frame)


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("samplingFrequency", 0.0, "sampling frequency"),
        ("samplingFrequency", float("nan"), "sampling frequency"),
        ("x", [1.0], "equal sample counts"),
        ("x", [1.0, float("inf"), 3.0], "finite numbers"),
    ],
)
def test_invalid_motion_data_rejected(tmp_path, record, field, value, expected):
    record["rawData"]["accelerometer"][field] = value
    with pytest.raises(ValueError, match=expected):
        load_sensor_file(write_avro(tmp_path / "invalid.avro", [record]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("timestampStart", 1700000001000123),
        ("samplingFrequency", 20.0),
        ("x", [1.0, 2.0]),
    ],
)
def test_unaligned_or_incomplete_gyro_is_not_silently_paired(tmp_path, record, field, value):
    gyro = copy.deepcopy(record["rawData"]["accelerometer"])
    gyro[field] = value
    record["rawData"]["gyroscope"] = gyro
    with pytest.raises(ValueError, match="timelines differ|equal sample counts"):
        load_sensor_file(write_avro(tmp_path / "unaligned.avro", [record]))


def test_empty_or_multiple_records_do_not_silently_lose_data(tmp_path, record):
    with pytest.raises(ValueError, match="no records"):
        load_sensor_file(write_avro(tmp_path / "empty.avro", []))
    with pytest.raises(ValueError, match="one recording per Avro file"):
        load_sensor_file(write_avro(tmp_path / "multiple.avro", [record, record]))
