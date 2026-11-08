"""Compact module diagnostics derived without modifying scientific outputs."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Any

from .contracts import AnalysisResults, Provenance
from .error_reporting import ErrorContext, reconciled_errors
from .recording_skips import all_recordings_skipped
from .result_contracts import ResultCategory

_OUTPUT_CATEGORIES: tuple[ResultCategory, ...] = (
    "quantifications",
    "classifications",
    "aggregations",
)


def _quantity(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def issue_severity(has_results: bool) -> str:
    return "warning" if has_results else "error"


@dataclass(frozen=True)
class ModuleIssues:
    processing_errors: int
    affected_recordings: int | None
    skip_reports: int
    skipped_recordings: int | None
    aggregation_failed: bool
    has_results: bool

    @property
    def title(self) -> str:
        return "Partial results" if self.has_results else "No results available"

    @property
    def severity(self) -> str:
        return issue_severity(self.has_results)

    @property
    def description(self) -> str:
        parts = []
        if self.processing_errors:
            text = _quantity(self.processing_errors, "processing error")
            if self.affected_recordings is not None:
                text += f" affecting {_quantity(self.affected_recordings, 'recording')}"
            parts.append(text)
        if self.skip_reports:
            parts.append(
                f"{_quantity(self.skipped_recordings, 'recording')} skipped"
                if self.skipped_recordings is not None
                else f"{_quantity(self.skip_reports, 'report')} of skipped recordings"
            )
        if self.aggregation_failed:
            parts.append("Some summary statistics are unavailable because aggregation failed")
        return ". ".join(parts) + "."


def has_output(value: Any) -> bool:
    import pandas as pd

    if isinstance(value, pd.DataFrame):
        return not value.empty
    if isinstance(value, Mapping):
        return any(has_output(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_output(child) for child in value)
    return isinstance(value, Integral) or (isinstance(value, Real) and math.isfinite(float(value)))


def _original_recording(
    file: str, sections: Mapping[str, str], originals: set[str], source: str
) -> str | None:
    if not file:
        return None
    mapped = sections.get(file)
    if isinstance(mapped, str) and mapped:
        return mapped
    if file in originals:
        return file
    parents = [key for key in originals if file.startswith(key + "__segment_")]
    if len(parents) == 1:
        return parents[0]
    if re.fullmatch(r"segment_\d+", file):
        if len(originals) == 1:
            return next(iter(originals))
        if not originals and source:
            return source
    return None


def _recording_count(
    errors: Sequence[ErrorContext],
    sections: Mapping[str, str],
    originals: set[str],
    source: str,
) -> int | None:
    keys = {_original_recording(error.file, sections, originals, source) for error in errors}
    return None if None in keys else len(keys)


def module_issue_summaries(
    results: AnalysisResults, provenance: Provenance, diagnostics: Iterable[str] = ()
) -> dict[str, ModuleIssues]:
    groups: dict[str, list[ErrorContext]] = {}
    for error in reconciled_errors(diagnostics, results.get("errors", [])):
        for module in sorted(error.pipelines):
            groups.setdefault(module, []).append(error)
    if not groups:
        return {}
    recordings = results.get("metadata", {}).get("desktop_recordings", {})
    sections = recordings.get("sections", {})
    originals = set(provenance.get("sources", {})) | set(recordings.get("recordings", []))
    summaries = {}
    for module, errors in groups.items():
        failures = [error for error in errors if not error.skipped]
        skips = [error for error in errors if error.skipped]
        summaries[module] = ModuleIssues(
            processing_errors=len(failures),
            affected_recordings=_recording_count(
                failures, sections, originals, provenance.get("source", "")
            ),
            skip_reports=len(skips),
            skipped_recordings=_recording_count(
                skips, sections, originals, provenance.get("source", "")
            ),
            aggregation_failed=any(error.stage == "aggregation" for error in failures),
            has_results=any(
                has_output(results.get(category, {}).get(module)) for category in _OUTPUT_CATEGORIES
            ),
        )
    return summaries


@dataclass(frozen=True)
class ResultIssues:
    message: str
    severity: str = ""


def result_issue_summary(
    results: AnalysisResults,
    provenance: Provenance,
    diagnostics: Iterable[str] = (),
    warnings: Iterable[str] = (),
) -> ResultIssues:
    """Describe the owning run without replaying its completion lifecycle."""
    errors = reconciled_errors(diagnostics, results.get("errors", []))
    skips = [error for error in errors if error.skipped]
    failures = [error for error in errors if not error.skipped and not error.operation]
    operations = [error for error in errors if error.operation]
    warning_count = len(set(warnings))
    available = any(has_output(results.get(category, {})) for category in _OUTPUT_CATEGORIES)
    parts = []
    if failures:
        parts.append(_quantity(len(failures), "processing error"))
    if skips:
        recordings = results.get("metadata", {}).get("desktop_recordings", {})
        count = _recording_count(
            skips,
            recordings.get("sections", {}),
            set(provenance.get("sources", {})) | set(recordings.get("recordings", [])),
            provenance.get("source", ""),
        )
        parts.append(
            f"{_quantity(count, 'recording')} skipped"
            if count is not None
            else f"{_quantity(len(skips), 'report')} of skipped recordings"
        )
    if operations:
        parts.append(_quantity(len(operations), "operation error"))
    if warning_count:
        parts.append(_quantity(warning_count, "warning"))
    if not parts:
        return ResultIssues(
            "Analysis completed." if available else "No quantified windows. See Runs for details."
        )
    title = (
        ("Partial results" if available else "No results available")
        if failures or skips
        else "Analysis completed"
    )
    message = f"{title}: {'. '.join(parts)}. See Runs for details."
    if all_recordings_skipped(results) and not available:
        message = "No usable recordings remain; all recordings were skipped. See Runs for details."
    return ResultIssues(message, issue_severity(available) if failures or skips else "warning")
