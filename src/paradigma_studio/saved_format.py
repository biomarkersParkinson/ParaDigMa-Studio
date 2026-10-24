"""The current on-disk contract, independent of app and toolbox releases."""

from __future__ import annotations

RUN_FORMAT = "paradigma-studio.run"
RESULT_FORMAT = "paradigma-studio.results"
FORMAT_VERSION = 1


def validate_saved_format(value: object, expected: str) -> None:
    """Reject unsupported files without interpreting or migrating their contents."""
    if (
        not isinstance(value, dict)
        or value.get("format") != expected
        or type(value.get("format_version")) is not int
        or value["format_version"] != FORMAT_VERSION
    ):
        kind = "run history" if expected == RUN_FORMAT else "result export"
        raise ValueError(
            f"Unsupported {kind} format. Only ParaDigMa Studio format version "
            f"{FORMAT_VERSION} is supported; unversioned and other versions cannot be opened."
        )
