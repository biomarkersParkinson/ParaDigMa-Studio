"""Read-only analysis milestones, independent of Qt and scientific calculations."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Sequence
from itertools import accumulate

from .contracts import Pipeline

ProgressCallback = Callable[[int], None]

# ParaDigMa 1.1.2 emits these INFO messages before starting each stage.
# A stage start confirms completion of its predecessors, not of that stage.
STAGES: dict[Pipeline, tuple[str, ...]] = {
    "gait": (
        "Step 1: Preprocessing IMU data",
        "Step 2: Extracting gait features",
        "Step 3: Detecting gait",
        "Step 4: Extracting arm activity features",
        "Step 5: Filtering gait",
        "Step 6a: Quantifying arm swing (unfiltered)",
        "Step 6b: Quantifying arm swing (filtered)",
    ),
    "tremor": (
        "Step 1: Preprocessing gyroscope data",
        "Step 2: Extracting tremor features",
        "Step 3: Detecting tremor",
        "Step 4: Quantifying tremor",
    ),
    "pulse_rate": (
        "Step 1: Preprocessing PPG and accelerometer data",
        "Step 2: Extracting signal quality features",
        "Step 3: Signal quality classification",
        "Step 4: Pulse rate estimation",
    ),
}
COMPLETED: dict[Pipeline, str] = {
    "gait": "Gait analysis pipeline completed.",
    "tremor": "Tremor analysis completed:",
    "pulse_rate": "Pulse rate analysis completed:",
}
_STARTS = {
    message: (name, index)
    for name, stages in STAGES.items()
    for index, message in enumerate(stages)
}
# Upstream announces quantification before entering its pulse estimation step.
_STARTS["Step 5: Quantifying pulse rate"] = ("pulse_rate", 3)
_RECORDING = re.compile(r"Processing DataFrame (\d+)/(\d+): .+")


class AnalysisProgress:
    """Compose fixed shares of a 0–1000 work plan without moving backwards."""

    def __init__(self, callback: ProgressCallback) -> None:
        self.callback = callback
        self.value = -1

    def report(self, value: float) -> None:
        if not math.isfinite(value):
            return
        current = max(0, min(1000, int(value)))
        if current > self.value:
            self.value = current
            self.callback(current)

    def span(self, start: float, end: float) -> AnalysisProgress:
        return AnalysisProgress(lambda value: self.report(start + (end - start) * value / 1000))


def milestone(progress: AnalysisProgress | None, value: float) -> None:
    if progress is not None:
        progress.report(value)


class ProgressLogHandler(logging.NullHandler):
    """Expose a job's progress callback without turning milestones into log text."""

    def __init__(self, callback: ProgressCallback) -> None:
        super().__init__()
        self.callback = callback
        self.value: int | None = None

    def report(self, value: int) -> None:
        if value != self.value:
            self.value = value
            self.callback(value)


def report_progress(logger: logging.Logger, value: int) -> None:
    """Deliver parent-process milestones only to explicit progress listeners."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        return
    for handler in logger.handlers:
        if isinstance(handler, ProgressLogHandler):
            handler.report(value)


class PipelineProgressHandler(logging.Handler):
    """Translate known official stage messages while leaving logs untouched."""

    def __init__(
        self, progress: AnalysisProgress, weights: Sequence[int], pipelines: Sequence[Pipeline]
    ) -> None:
        super().__init__(logging.INFO)
        self.progress = progress
        self.weights = list(weights)
        self.starts = list(accumulate(weights, initial=0))
        self.pipelines = list(pipelines)
        self.total = max(1, sum(weights))
        self.stage_count = sum(len(STAGES[name]) for name in pipelines)
        self.index = -1
        self.stages = dict.fromkeys(pipelines, 0)

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        match = _RECORDING.fullmatch(message)
        if match:
            index, total = int(match[1]) - 1, int(match[2])
            if total == len(self.weights) and self.index < index < total:
                self.index = index
                self.stages = dict.fromkeys(self.pipelines, 0)
                self._report()
        elif message.startswith("Step 4: Combining quantifications from all files"):
            self.progress.report(850)
        elif message.startswith("Step 5: Aggregating results across all files"):
            self.progress.report(875)
        elif self.index >= 0:
            self._stage_message(message)

    def _stage_message(self, message: str) -> None:
        stage = _STARTS.get(message)
        if stage is None:
            stage = next(
                (
                    (name, len(STAGES[name]))
                    for name in self.pipelines
                    if message.startswith(COMPLETED[name])
                ),
                None,
            )
        if stage is None or stage[0] not in self.stages:
            return
        name, completed = stage
        # Moving to another module also resolves a previous module that
        # skipped steps or returned an error; existing outcome logs stay intact.
        for previous in self.pipelines[: self.pipelines.index(name)]:
            self.stages[previous] = len(STAGES[previous])
        self.stages[name] = max(self.stages[name], completed)
        self._report()

    def _report(self) -> None:
        if self.stage_count:
            done = float(self.starts[self.index])
            done += self.weights[self.index] * sum(self.stages.values()) / self.stage_count
            self.progress.report(850 * done / self.total)


class RecordingProgress:
    """Combine independent worker milestones using fixed original sample counts."""

    def __init__(self, logger: logging.Logger, weights: dict[str, int]) -> None:
        self.logger = logger
        self.weights = weights
        self.total = max(1, sum(weights.values()))
        self.values = dict.fromkeys(weights, 0)
        self.completed = 0

    def report(self, recording: str, value: int) -> None:
        if recording not in self.weights or not 0 <= value <= 1000:
            return
        previous = self.values[recording]
        if value > previous:
            self.completed += self.weights[recording] * (value - previous)
            self.values[recording] = value
            report_progress(self.logger, 20 + 880 * self.completed // (self.total * 1000))
