"""Bounded, thread-safe progress from existing per-channel inspection work."""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING

from .analysis_progress import AnalysisProgress, ProgressCallback

if TYPE_CHECKING:
    import pandas as pd


class InspectionProgress:
    """Weight known frame dimensions without scanning samples or filesystem metadata."""

    def __init__(self, frames: dict[str, pd.DataFrame], callback: ProgressCallback) -> None:
        self.weights = {
            key: max(1, len(frame)) * max(1, len(frame.columns)) for key, frame in frames.items()
        }
        self.total = max(1, sum(self.weights.values()))
        self.values = dict.fromkeys(frames, 0)
        self.completed = 0
        self.progress = AnalysisProgress(callback)
        self.lock = Lock()

    def for_recording(self, key: str) -> ProgressCallback:
        return lambda value: self.report(key, value)

    def report(self, key: str, value: int) -> None:
        with self.lock:
            previous = self.values[key]
            if previous <= value <= 1000:
                self.completed += self.weights[key] * (value - previous)
                self.values[key] = value
                self.progress.report(self.completed / self.total)
