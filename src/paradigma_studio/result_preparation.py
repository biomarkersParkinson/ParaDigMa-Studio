"""Qt-independent result snapshots for background preparation and UI installation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from .contracts import (
    AnalysisResults,
    AnalysisSettings,
    ClockMetadata,
    FloatArray,
    Provenance,
    RecordingAlignment,
    SensorInput,
    TimeOffsets,
)
from .overview import recording_extent
from .result_data import ResultData, prepare_result_data
from .results_view import normalise_clock, recording_clock

if TYPE_CHECKING:
    import pandas as pd

AlignRecordings: TypeAlias = (
    "Callable[[dict[str, pd.DataFrame], AnalysisSettings, AnalysisResults], RecordingAlignment]"
)
AlignAnalysis: TypeAlias = (
    "Callable[[pd.DataFrame | None, AnalysisSettings, AnalysisResults, TimeOffsets | None], "
    "tuple[FloatArray | None, dict[str, FloatArray], dict[str, float]]]"
)


@dataclass(frozen=True)
class PreparedResults:
    results: AnalysisResults
    provenance: Provenance
    source_frame: SensorInput | None
    timeline: FloatArray | dict[str, FloatArray] | None
    source_timelines: dict[str, FloatArray] | dict[str, dict[str, FloatArray]]
    offsets: TimeOffsets
    recording_bases: dict[str, float]
    clock: ClockMetadata | None
    data: ResultData
    notices: tuple[str, ...]


def prepare_results(
    results: AnalysisResults,
    provenance: Provenance,
    source_frame: SensorInput | None,
    *,
    align_recordings: AlignRecordings,
    analysis_alignment: AlignAnalysis,
) -> PreparedResults:
    """Derive presentation data without accessing widgets or changing source tables."""
    settings = provenance.get("settings", {})
    bases: dict[str, float] = {}
    timeline: FloatArray | dict[str, FloatArray] | None
    timelines: dict[str, FloatArray] | dict[str, dict[str, FloatArray]]
    offsets: TimeOffsets
    if isinstance(source_frame, dict):
        timeline, timelines, offsets, batch_clock, bases = align_recordings(
            source_frame, settings, results
        )
    else:
        timeline, timelines, flat_offsets = analysis_alignment(
            source_frame, settings, results, provenance.get("display_offsets")
        )
        offsets = dict(flat_offsets)
        batch_clock = None
    if offsets:
        provenance["display_offsets"] = dict(offsets)
    extent = recording_extent(timeline, bases)
    if extent is not None:
        provenance["recording_extent"] = extent
    clock, notices = _resolve_clock(provenance, source_frame, timeline, batch_clock)
    return PreparedResults(
        results,
        provenance,
        source_frame,
        timeline,
        timelines,
        offsets,
        bases,
        clock,
        prepare_result_data(results, offsets),
        notices,
    )


def _resolve_clock(
    provenance: Provenance,
    frame: SensorInput | None,
    timeline: FloatArray | dict[str, FloatArray] | None,
    batch_clock: ClockMetadata | None,
) -> tuple[ClockMetadata | None, tuple[str, ...]]:
    settings = provenance.get("settings", {})
    clock: ClockMetadata | None = None
    notices: tuple[str, ...] = ()
    if provenance.get("display_clock"):
        try:
            clock = normalise_clock(provenance["display_clock"])
        except (ValueError, TypeError, KeyError, OverflowError):
            notices = ("Stored recording clock is invalid; using available recording timing.",)
            provenance.pop("display_clock", None)
    if clock is None:
        clock = (
            batch_clock if isinstance(frame, dict) else recording_clock(frame, settings, timeline)
        )
    origin = settings.get("plot_time_origin", {})
    if not provenance.get("display_clock") and origin.get("mode") == "custom":
        clock = normalise_clock(origin["clock"])
    elif origin.get("mode") == "elapsed":
        clock = None
    if clock is not None:
        provenance["display_clock"] = dict(clock)
    return clock, notices
