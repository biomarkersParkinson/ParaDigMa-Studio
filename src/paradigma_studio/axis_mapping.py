"""Fixed-order sensor signs and migration of saved global axis permutations."""

from __future__ import annotations

from collections.abc import Mapping

SENSORS = ("accelerometer", "gyroscope")
IMU_COLUMNS = tuple(f"{sensor}_{axis}" for sensor in SENSORS for axis in "xyz")


def validate_orientation(axes: object) -> list[str] | None:
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
    return list(axes)


def validate_axis_inversions(values: object) -> list[str] | None:
    if values is None:
        return None
    if (
        not isinstance(values, (list, tuple))
        or any(not isinstance(value, str) or value not in IMU_COLUMNS for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("Axis inversions must list unique accelerometer or gyroscope channels.")
    return [channel for channel in IMU_COLUMNS if channel in values]


def sensor_orientation(sensor: str, inversions: list[str]) -> list[str]:
    if sensor not in SENSORS:
        raise ValueError("Select accelerometer or gyroscope for axis directions.")
    return [("-" if f"{sensor}_{axis}" in inversions else "") + axis for axis in "xyz"]


def preparation_orientations(settings: Mapping[str, object]) -> dict[str, list[str] | None]:
    legacy = validate_orientation(settings.get("device_orientation", ["x", "y", "z"]))
    inversions = validate_axis_inversions(settings.get("axis_inversions"))
    if inversions is None:
        return dict.fromkeys(SENSORS, legacy)
    if legacy is not None and legacy != ["x", "y", "z"]:
        raise ValueError("Use column mapping for axis swaps when axis inversions are specified.")
    return {sensor: sensor_orientation(sensor, inversions) for sensor in SENSORS}


def migrate_legacy_orientation(
    mapping: Mapping[str, str] | None, orientation: object
) -> tuple[dict[str, str], list[str]]:
    """Compose old renaming then global orientation into one rename and signs.

    Unmentioned standard columns follow the same permutation as explicitly
    mapped columns. Additional names and identity mappings retain their meaning.
    """
    axes = validate_orientation(orientation) or ["x", "y", "z"]
    original = dict(mapping or {})
    routes = {
        f"{sensor}_{source[-1]}": f"{sensor}_{target}"
        for sensor in SENSORS
        for target, source in zip("xyz", axes, strict=True)
    }
    translated = {source: routes.get(target, target) for source, target in original.items()}
    for source, target in routes.items():
        if source != target and source not in original:
            translated[source] = target
    inversions = [
        f"{sensor}_{target}"
        for sensor in SENSORS
        for target, source in zip("xyz", axes, strict=True)
        if source.startswith("-")
    ]
    return translated, inversions
