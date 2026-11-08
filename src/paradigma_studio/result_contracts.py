"""Stable result sections and Studio metadata; upstream leaves remain extensible."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypeAlias, TypedDict

if TYPE_CHECKING:
    import pandas as pd

Pipeline: TypeAlias = Literal["gait", "tremor", "pulse_rate"]
ResultCategory: TypeAlias = Literal[
    "classifications", "quantifications", "aggregations", "metadata"
]


class ProcessingError(TypedDict):
    error: str
    pipeline: NotRequired[Pipeline]
    pipelines: NotRequired[list[Pipeline]]
    stage: NotRequired[str]
    file: NotRequired[str]
    skipped: NotRequired[bool]


AnalysisError: TypeAlias = str | ProcessingError
ClassificationTables: TypeAlias = "dict[str, pd.DataFrame | dict[str, pd.DataFrame]]"


class AnalysisResults(TypedDict, total=False):
    """Known envelope; module-specific statistics and metadata are upstream data.

    These annotations do not validate imported files or transform the returned
    dictionary. Readers retain runtime validation and tolerate extension fields.
    """

    classifications: dict[str, Any]
    quantifications: dict[str, Any]
    aggregations: dict[str, Any]
    metadata: dict[str, Any]
    errors: list[AnalysisError]


class RecordingMetadata(TypedDict):
    recordings: list[str]
    sections: dict[str, str]


class RecordingPreparation(TypedDict, total=False):
    input_samples: int
    excluded_samples: int
    samples_after_exclusion: int
    invalid_columns: list[str]
    split_at_excluded_samples: bool
    skipped_reason: str
    analyzed_samples: int
    continuous_sections: int


class PreparationMetadata(RecordingPreparation, total=False):
    by_recording: dict[str, RecordingPreparation]
    analysis_groups: list[list[Pipeline]]
    by_module: dict[str, PreparationMetadata]


class AvailabilitySection(TypedDict):
    samples: int
    sample_interval_s: float
    intervals: list[list[float]]


PreparedAvailability: TypeAlias = dict[Pipeline, dict[str, AvailabilitySection]]
