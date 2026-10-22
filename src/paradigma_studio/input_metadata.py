"""Supported importer units and consensus for the selected signal columns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

METADATA_KEY = "desktop_input_metadata"
UNIT_SIGNALS = {
    "Acceleration units": tuple(f"accelerometer_{axis}" for axis in "xyz"),
    "Gyroscope units": tuple(f"gyroscope_{axis}" for axis in "xyz"),
    "Time units": ("time",),
}
FORMAT_SOURCES = {
    "tsdf": "TSDF channel metadata",
    "cwa": "Axivity CWA importer (decoded physical values)",
    "empatica": "Empatica importer (converted physical values)",
}
_UNITS = {
    "Acceleration units": {
        "g": "g",
        "m/s^2": "m/s^2",
        "m/s²": "m/s^2",
        "m/s2": "m/s^2",
    },
    "Gyroscope units": {"deg/s": "deg/s", "°/s": "deg/s", "rad/s": "rad/s"},
    "Time units": {
        f"{representation}_{unit}": f"{representation}_{unit}"
        for representation in ("relative", "absolute", "difference")
        for unit in ("s", "ms")
    },
}


@dataclass(frozen=True)
class UnitDefault:
    value: str | None
    detail: str
    issue: str = ""


def record_import_units(frame: pd.DataFrame, source_format: str) -> None:
    """Describe the units emitted by the two supported device importers."""
    units = {"time": "relative_s"}
    units.update(dict.fromkeys(UNIT_SIGNALS["Acceleration units"], "g"))
    units.update(dict.fromkeys(UNIT_SIGNALS["Gyroscope units"], "deg/s"))
    frame.attrs[METADATA_KEY] = {
        "format": source_format,
        "units": {column: unit for column, unit in units.items() if column in frame},
    }


def unit_defaults(
    recordings: Mapping[str, pd.DataFrame], choices: Mapping[str, str | None]
) -> dict[str, UnitDefault]:
    """Use declarations for selected, present columns; never infer units from values."""
    return {
        title: _unit_default(title, signals, recordings, choices)
        for title, signals in UNIT_SIGNALS.items()
    }


def _unit_default(
    title: str,
    signals: tuple[str, ...],
    recordings: Mapping[str, pd.DataFrame],
    choices: Mapping[str, str | None],
) -> UnitDefault:
    observed: list[str | None] = []
    declared: set[str] = set()
    sources: set[str] = set()
    applicable = 0
    for frame in recordings.values():
        columns = [
            source
            for signal in signals
            if (source := choices.get(signal)) is not None and source in frame.columns
        ]
        if not columns:
            continue
        applicable += 1
        metadata = frame.attrs.get(METADATA_KEY, {})
        metadata = metadata if isinstance(metadata, dict) else {}
        source_format = metadata.get("format")
        source = FORMAT_SOURCES.get(source_format) if isinstance(source_format, str) else None
        units = metadata.get("units", {}) if source else {}
        units = units if isinstance(units, dict) else {}
        for column in columns:
            raw = units.get(column)
            normalized = raw.strip().casefold() if isinstance(raw, str) else ""
            if normalized:
                declared.add(normalized)
            observed.append(_UNITS[title].get(normalized))
        if source:
            sources.add(source)
    return _consensus(title, observed, declared, sources, applicable)


def _consensus(
    title: str,
    observed: list[str | None],
    declared: set[str],
    sources: set[str],
    applicable: int,
) -> UnitDefault:
    known = {value for value in observed if value is not None}
    if len(known) > 1:
        issue = f"{title} differ between selected channels or recordings."
    elif known and None in observed:
        issue = f"{title} are not declared consistently across all applicable recordings."
    elif not known and declared:
        issue = f"{title} in the file metadata are not supported."
    else:
        issue = ""
    if issue:
        return UnitDefault(
            None,
            issue + " Check the units; normalize differing inputs or analyze them separately.",
            issue,
        )
    if not known:
        return UnitDefault(
            None, "No supported unit metadata is available for the selected columns."
        )
    value = next(iter(known))
    return UnitDefault(
        value,
        f"{'; '.join(sorted(sources))}: selected channels declare {', '.join(sorted(declared))}. "
        f"Applies to {applicable} recording(s). Analyze uses {value}.",
    )
