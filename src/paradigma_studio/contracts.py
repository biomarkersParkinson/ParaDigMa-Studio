"""Shared API types without importing the scientific stack at startup.

ParaDigMa results, settings and stored run records have extensible nested
payloads. Keep their values permissive while typing frames and service inputs.
"""

from __future__ import annotations

from os import PathLike
from typing import Any, Literal, Protocol, TypeAlias, TypedDict, TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd
    from numpy.typing import NDArray

PathInput: TypeAlias = str | PathLike[str]
Pipeline: TypeAlias = Literal["gait", "tremor", "pulse_rate"]
SensorInput: TypeAlias = "pd.DataFrame | dict[str, pd.DataFrame]"
FloatArray: TypeAlias = "NDArray[np.floating[Any]]"
SegmentArray: TypeAlias = "NDArray[np.int64]"
AnalysisSettings: TypeAlias = dict[str, Any]
AnalysisResults: TypeAlias = dict[str, Any]
AnalysisError: TypeAlias = str | dict[str, Any]
Provenance: TypeAlias = dict[str, Any]
RunRecord: TypeAlias = dict[str, Any]
RunOutput: TypeAlias = dict[str, Any]
TimeOffsets: TypeAlias = dict[str, float | dict[str, float]]
JSONValue: TypeAlias = "None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]"
AnalysisEvent: TypeAlias = (
    tuple[Literal["log"], int, str] | tuple[Literal["failed"], str] | tuple[Literal["completed"]]
)


class ClockMetadata(TypedDict):
    origin: str
    timezone: str | None
    source: str


RecordingAlignment: TypeAlias = tuple[
    dict[str, FloatArray],
    dict[str, dict[str, FloatArray]],
    TimeOffsets,
    ClockMetadata | None,
    dict[str, float],
]


class TextSignal(Protocol):
    """The string-emitting part of a Qt signal, also usable by test doubles."""

    def emit(self, message: str, /) -> object: ...
