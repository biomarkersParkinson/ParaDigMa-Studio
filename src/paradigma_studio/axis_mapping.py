"""Fixed-order sensor signs and the Python API's global axis convention."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from .preparation_contracts import IMUSignal, Sensor, SignedAxis

SENSORS: tuple[Sensor, ...] = ("accelerometer", "gyroscope")
IMU_COLUMNS: tuple[IMUSignal, ...] = (
    "accelerometer_x",
    "accelerometer_y",
    "accelerometer_z",
    "gyroscope_x",
    "gyroscope_y",
    "gyroscope_z",
)


def validate_orientation(axes: object) -> list[SignedAxis] | None:
    if axes is None:
        return None
    if (
        not isinstance(axes, (list, tuple))
        or len(axes) != 3
        or any(
            not isinstance(axis, str) or axis not in {"x", "y", "z", "-x", "-y", "-z"}
            for axis in axes
        )
        or sorted(axis[-1] for axis in axes) != ["x", "y", "z"]
    ):
        raise ValueError(
            "Device axes must contain x, y and z once each, optionally prefixed with '-'."
        )
    # Membership and the full permutation were checked above.
    return cast("list[SignedAxis]", list(axes))


def validate_axis_inversions(values: object) -> list[IMUSignal] | None:
    if values is None:
        return None
    if (
        not isinstance(values, (list, tuple))
        or any(not isinstance(value, str) or value not in IMU_COLUMNS for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("Axis inversions must list unique accelerometer or gyroscope channels.")
    return [channel for channel in IMU_COLUMNS if channel in values]


def sensor_orientation(sensor: Sensor, inversions: list[IMUSignal]) -> list[SignedAxis]:
    if sensor not in SENSORS:
        raise ValueError("Select accelerometer or gyroscope for axis directions.")
    # f-strings do not retain Literal types; the fixed xyz alphabet is exhaustive.
    return [
        cast("SignedAxis", ("-" if f"{sensor}_{axis}" in inversions else "") + axis)
        for axis in "xyz"
    ]


def preparation_orientations(
    settings: Mapping[str, object],
) -> dict[Sensor, list[SignedAxis] | None]:
    global_axes = validate_orientation(settings.get("device_orientation", ["x", "y", "z"]))
    inversions = validate_axis_inversions(settings.get("axis_inversions"))
    if inversions is None:
        return dict.fromkeys(SENSORS, global_axes)
    if global_axes is not None and global_axes != ["x", "y", "z"]:
        raise ValueError("Use column mapping for axis swaps when axis inversions are specified.")
    return {sensor: sensor_orientation(sensor, inversions) for sensor in SENSORS}
