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


def _quantity(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


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
        return "error" if self.processing_errors and not self.has_results else "warning"

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


def _has_output(value: Any) -> bool:
    import pandas as pd

    if isinstance(value, pd.DataFrame):
        return not value.empty
    if isinstance(value, Mapping):
        return any(_has_output(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_output(child) for child in value)
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
                _has_output(results.get(category, {}).get(module))
                for category in ("quantifications", "classifications", "aggregations")
            ),
        )
    return summaries
