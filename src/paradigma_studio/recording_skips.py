"""Identify insufficient recordings without suppressing other preparation failures."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .contracts import AnalysisResults, Pipeline


class InsufficientRecordingData(ValueError):
    """A recording has too few usable samples or no retained continuous sections."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


def skipped_recording_errors(
    preparation: dict[str, Any], pipelines: Sequence[Pipeline]
) -> list[dict[str, Any]]:
    """Keep per-recording omissions attributable in run history and saved results."""
    return [
        {
            "file": key,
            "pipelines": list(pipelines),
            "stage": "preparation",
            "skipped": True,
            "error": f"Skipped recording: {details['skipped_reason']}",
        }
        for key, details in preparation.get("by_recording", {}).items()
        if "skipped_reason" in details
    ]


def all_recordings_skipped(results: AnalysisResults) -> bool:
    """Distinguish an unusable batch from valid inputs with no detected outcomes."""
    errors = results.get("errors", [])
    return (
        bool(errors)
        and all(isinstance(error, dict) and error.get("skipped") for error in errors)
        and not any(results.get("metadata", {}).get("desktop_availability", {}).values())
    )
