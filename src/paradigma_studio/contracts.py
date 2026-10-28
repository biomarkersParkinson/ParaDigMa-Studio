"""Shared API types without importing the scientific stack at startup.

Run records and saved outputs have explicit application-owned fields.
ParaDigMa results and saved/display settings retain extensible nested payloads.
Preparation and official adapter keywords live in preparation_contracts.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from os import PathLike
from typing import TYPE_CHECKING, Any, Literal, NotRequired, Protocol, TypeAlias, TypedDict

if TYPE_CHECKING:
    import logging

    import numpy as np
    import pandas as pd
    from numpy.typing import NDArray

    from .jobs import Worker

PathInput: TypeAlias = str | PathLike[str]
Pipeline: TypeAlias = Literal["gait", "tremor", "pulse_rate"]
SensorInput: TypeAlias = "pd.DataFrame | dict[str, pd.DataFrame]"
FloatArray: TypeAlias = "NDArray[np.floating[Any]]"
SegmentArray: TypeAlias = "NDArray[np.int64]"
AnalysisSettings: TypeAlias = dict[str, Any]
AnalysisResults: TypeAlias = dict[str, Any]
AnalysisError: TypeAlias = str | dict[str, Any]
Provenance: TypeAlias = dict[str, Any]
RunStatus: TypeAlias = Literal[
    "Running", "Completed", "Partial", "Failed", "Cancelled", "Unfinished"
]
OutputKind: TypeAlias = Literal["CSV", "JSON"]
JobOperation: TypeAlias = "Callable[[logging.Logger], object]"
# Qt's object-valued completed signal carries heterogeneous job result payloads.
JobCompletion: TypeAlias = Callable[[Any], None]
TimeOffsets: TypeAlias = dict[str, float | dict[str, float]]
JSONValue: TypeAlias = "None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]"


AnalysisLogEvent: TypeAlias = tuple[Literal["log"], int, str] | tuple[Literal["log"], int, str, str]
AnalysisEvent: TypeAlias = (
    AnalysisLogEvent
    | tuple[Literal["progress"], str, int]
    | tuple[Literal["failed"], str]
    | tuple[Literal["completed"]]
)


@dataclass(frozen=True)
class TimeConfiguration:
    """One time selection and its provenance, rendered on Data and Analyze."""

    column: str | None
    unit: str
    column_from_file: bool
    column_source: str
    unit_from_file: bool
    unit_source: str


class RunOutput(TypedDict):
    """A local snapshot or user export, with details specific to its kind."""

    kind: OutputKind
    path: str
    metadata_path: NotRequired[str]
    saved: str
    dataset: NotRequired[str]
    local: NotRequired[bool]
    complete: bool
    sha256: NotRequired[str]
    selected: NotRequired[list[str]]
    selected_rows: NotRequired[int]
    selection: NotRequired[dict[str, JSONValue]]


class SoftwareVersions(TypedDict):
    """Software that performed the analysis, captured once when a run starts."""

    studio_version: str
    paradigma_version: str
    studio_build_commit: NotRequired[str]


class RunRecord(SoftwareVersions):
    """Normalized run history plus optional, never-persisted workspace caches."""

    format: str
    format_version: int
    id: str
    started: str
    finished: str | None
    status: RunStatus
    source: str
    settings: AnalysisSettings
    warnings: list[str]
    errors: list[str]
    outputs: list[RunOutput]
    log: str
    sources: NotRequired[dict[str, str]]
    _frame: NotRequired[SensorInput]
    _results: NotRequired[AnalysisResults]
    _provenance: NotRequired[Provenance]
    _unsaved_results: NotRequired[bool]


class ClockMetadata(TypedDict):
    origin: str
    timezone: str | None
    source: str


class RecordingDescription(TypedDict):
    """Read-only inspection results accompanying an unchanged source frame."""

    time_column: Hashable | None
    time_unit: str
    missing: int
    sensors: pd.DataFrame
    time: pd.DataFrame | None


# Direct loads may omit cached descriptives; background loads always supply them.
RecordingLoadPayload: TypeAlias = (
    "tuple[str, pd.DataFrame] | tuple[str, pd.DataFrame, RecordingDescription]"
)
RecordingsLoadPayload: TypeAlias = (
    "tuple[dict[str, str], dict[str, pd.DataFrame], dict[str, RecordingDescription]]"
)


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


class NoticeCallback(Protocol):
    def __call__(self, message: str, severity: str = "warning") -> None: ...


class FinishRunCallback(Protocol):
    def __call__(self, status: RunStatus, errors: Iterable[AnalysisError] = ()) -> None: ...


class StartJobCallback(Protocol):
    def __call__(self, operation: JobOperation, completed: JobCompletion) -> None: ...


class ConnectWorkerCallback(Protocol):
    def __call__(self, worker: Worker, completed: JobCompletion) -> None: ...
