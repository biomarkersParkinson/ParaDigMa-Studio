"""Empatica IMU import using ParaDigMa's device-loading tutorial conventions.

ParaDigMa 1.1.2 rejects an absent gyroscope despite its tutorial supporting
accelerometer-only files. This adapter makes that sensor optional and uses
each sensor's own conversion parameters. Other formats keep official loaders.
"""

from pathlib import Path

import numpy as np
from avro.datafile import DataFileReader
from avro.io import DatumReader

from .input_metadata import record_import_units


def _motion_stream(sensor, name, version):
    if sensor is None:
        return None
    if not isinstance(sensor, dict):
        raise ValueError(f"Invalid Empatica {name} sensor record.")
    axes = [np.asarray(sensor.get(axis, []), dtype=float) for axis in "xyz"]
    if any(axis.ndim != 1 for axis in axes) or len({axis.size for axis in axes}) != 1:
        raise ValueError(f"Empatica {name} axes must have equal sample counts.")
    if not axes[0].size:
        return None
    samples = np.column_stack(axes)
    if not np.isfinite(samples).all():
        raise ValueError(f"Empatica {name} samples must be finite numbers.")
    frequency, start, factor = _motion_metadata(sensor, name, version)
    values = samples * factor
    if not np.isfinite(values).all():
        raise ValueError(f"Converted Empatica {name} samples must be finite numbers.")
    return values, frequency, start


def _motion_metadata(sensor, name, version):
    frequency = float(sensor["samplingFrequency"])
    if not np.isfinite(frequency) or frequency <= 0:
        raise ValueError(f"Empatica {name} sampling frequency must be positive and finite.")
    start = sensor["timestampStart"]
    if not isinstance(start, int) or isinstance(start, bool):
        raise ValueError(f"Empatica {name} timestampStart must be integer microseconds.")
    params = sensor["imuParams"]
    if version < (6, 5, 0):
        digital_range = float(params["digitalMax"]) - float(params["digitalMin"])
        if not np.isfinite(digital_range) or digital_range <= 0:
            raise ValueError(f"Invalid Empatica {name} digital conversion range.")
        factor = (float(params["physicalMax"]) - float(params["physicalMin"])) / digital_range
    else:
        factor = float(params["conversionFactor"])
    if not np.isfinite(factor) or factor <= 0:
        raise ValueError(f"Empatica {name} conversion factor must be positive and finite.")
    return frequency, start, factor


def load_empatica_imu(path):
    """Load one Empatica Avro record without requiring gyroscope samples.

    Only IMU channels are imported. Processed BVP is not raw green PPG. Reject
    unaligned IMU streams instead of pairing measurements at different times.
    """
    import pandas as pd

    with Path(path).open("rb") as stream, DataFileReader(stream, DatumReader()) as reader:
        record = next(reader, None)
        if record is None:
            raise ValueError("The Empatica Avro file contains no records.")
        if next(reader, None) is not None:
            raise ValueError(
                "Empatica import requires one recording per Avro file; split multi-record files first."
            )
    try:
        raw = record["rawData"]
        schema = record["schemaVersion"]
        version = tuple(schema[key] for key in ("major", "minor", "patch"))
        if not isinstance(raw, dict) or any(
            type(value) is not int or value < 0 for value in version
        ):
            raise ValueError("Invalid Empatica rawData or schemaVersion.")
        accel = _motion_stream(raw.get("accelerometer"), "accelerometer", version)
        gyro = _motion_stream(raw.get("gyroscope"), "gyroscope", version)
    except (KeyError, TypeError) as error:
        raise ValueError(f"Invalid Empatica sensor metadata: {error}") from error
    if accel is None:
        raise ValueError("The Empatica file contains no accelerometer samples.")
    values, frequency, start = accel
    elapsed = np.arange(len(values), dtype=float) / frequency
    frame = pd.DataFrame(
        {
            "time": elapsed,
            "time_dt": pd.to_datetime(start, unit="us") + pd.to_timedelta(elapsed, unit="s"),
            **{f"accelerometer_{axis}": values[:, index] for index, axis in enumerate("xyz")},
        }
    )
    if gyro is not None:
        gyro_values, gyro_frequency, gyro_start = gyro
        if len(gyro_values) != len(values) or gyro_frequency != frequency or gyro_start != start:
            raise ValueError(
                "Empatica accelerometer and gyroscope timelines differ; resample them to a common timeline before import."
            )
        for index, axis in enumerate("xyz"):
            frame[f"gyroscope_{axis}"] = gyro_values[:, index]
    frame.attrs.update(
        source_format="empatica",
        sampling_frequency=frequency,
        timestamp_start_us=start,
        schema_version=version,
    )
    record_import_units(frame, "empatica")
    return frame
