"""Interruptible analysis with parent-owned temporary files and process cleanup."""

from __future__ import annotations

import logging
import multiprocessing
import pickle
import tempfile
import traceback
from pathlib import Path
from queue import Empty
from typing import TYPE_CHECKING

from .analysis_limits import parallel_worker_count
from .analysis_progress import AnalysisProgress, report_progress
from .contracts import (
    AnalysisEvent,
    AnalysisLogEvent,
    AnalysisResults,
    AnalysisSettings,
    PathInput,
    SensorInput,
)

if TYPE_CHECKING:
    from multiprocessing.process import BaseProcess
    from multiprocessing.queues import Queue
    from threading import Event


class AnalysisCancelled(Exception):
    pass


class QueueLogHandler(logging.Handler):
    def __init__(self, queue: Queue[AnalysisEvent], recording: str = "") -> None:
        super().__init__()
        self.queue = queue
        self.recording = recording

    def emit(self, record: logging.LogRecord) -> None:
        from .history import error_summary

        message = record.getMessage()
        if self.recording and not error_summary(message):
            # Keep the original prefix for warning/failure recognition while
            # making interleaved pipeline steps attributable to their recording.
            message += f" [{self.recording}]"
        details = record.exc_text
        if not details and record.exc_info:
            details = logging.Formatter().formatException(record.exc_info)
        if details:
            # Traceback objects cannot cross processes. Preserve their formatted
            # text separately so error counting still uses the original message.
            self.queue.put(("log", record.levelno, message, details))
        else:
            self.queue.put(("log", record.levelno, message))


def forward_analysis_log(logger: logging.Logger, event: AnalysisLogEvent) -> None:
    """Restore remote diagnostic text without adding a second error record."""
    if logger.isEnabledFor(event[1]):
        record = logger.makeRecord(logger.name, event[1], "", 0, event[2], (), None)
        if len(event) == 4:
            record.exc_text = event[3]
        logger.handle(record)


def _analyze_child(
    input_path: PathInput,
    output_path: PathInput,
    settings: AnalysisSettings,
    queue: Queue[AnalysisEvent],
) -> None:
    try:
        from .core import analyze

        logger = logging.Logger("paradigma-studio", logging.INFO)
        logger.addHandler(QueueLogHandler(queue))
        queue.put(("progress", "", 20))
        # These private files are created by this process's parent, never user inputs.
        with open(input_path, "rb") as stream:
            frame = pickle.load(stream)
        progress = AnalysisProgress(
            lambda value: queue.put(("progress", "", 20 + value * 900 // 1000))
        )
        results = analyze(frame, logger=logger, progress=progress, **settings)
        with open(output_path, "wb") as stream:
            pickle.dump(results, stream, protocol=pickle.HIGHEST_PROTOCOL)
        queue.put(("progress", "", 960))
        queue.put(("completed",))
    except Exception as exc:  # noqa: BLE001 -- Final child-process failure reporting.
        # This process boundary also covers toolbox imports and result serialization.
        queue.put(("log", logging.INFO, traceback.format_exc()))
        queue.put(("failed", f"{type(exc).__name__}: {exc}"))


def run_isolated_analysis(
    frame: SensorInput,
    settings: AnalysisSettings,
    logger: logging.Logger,
    cancel: Event,
    *,
    max_workers: int | None = None,
) -> AnalysisResults:
    """Stop only the owned child; never terminate Qt's thread or other programs."""
    workers = parallel_worker_count(frame, settings, logger)
    if max_workers is not None:
        if (
            isinstance(max_workers, bool)
            or not isinstance(max_workers, int)
            or max_workers not in (1, 2)
        ):
            raise ValueError("max_workers must be 1 or 2.")
        if max_workers < workers:
            logger.info("Worker count capped at %s by the caller.", max_workers)
        workers = min(workers, max_workers)
    if isinstance(frame, dict) and len(frame) > 1 and workers > 1:
        from .parallel_analysis import run_parallel_analysis

        return run_parallel_analysis(frame, settings, logger, cancel, workers)
    if isinstance(frame, dict) and len(frame) > 1:
        logger.info("Processing %s recordings with 1 worker", len(frame))
    context = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="paradigma-analysis-") as directory:
        input_path, output_path = Path(directory) / "input.pkl", Path(directory) / "results.pkl"
        with input_path.open("wb") as stream:
            pickle.dump(frame, stream, protocol=pickle.HIGHEST_PROTOCOL)
        if cancel.is_set():
            raise AnalysisCancelled()
        report_progress(logger, 10)
        queue: Queue[AnalysisEvent] = context.Queue()
        # All toolbox intermediate files live under the parent's temporary root,
        # so they are removed even when the child is interrupted mid-calculation.
        process = context.Process(
            target=_analyze_child,
            args=(
                str(input_path),
                str(output_path),
                {**settings, "output_dir": str(Path(directory) / "outputs")},
                queue,
            ),
            daemon=True,
        )
        try:
            process.start()
            return _wait_for_analysis(process, queue, output_path, logger, cancel)
        finally:
            _close_analysis_process(process, queue)


def _wait_for_analysis(
    process: BaseProcess,
    queue: Queue[AnalysisEvent],
    output_path: Path,
    logger: logging.Logger,
    cancel: Event,
) -> AnalysisResults:
    """Relay child events until cancellation, failure or a complete result."""
    while True:
        if cancel.is_set():
            raise AnalysisCancelled()
        try:
            event = queue.get(timeout=0.1)
        except Empty:
            if not process.is_alive():
                raise RuntimeError(
                    f"Analysis process exited unexpectedly ({process.exitcode})."
                ) from None
            continue
        if event[0] == "log":
            forward_analysis_log(logger, event)
        elif event[0] == "progress":
            report_progress(logger, event[2])
        elif event[0] == "failed":
            raise RuntimeError(event[1])
        elif event[0] == "completed":
            if cancel.is_set():
                raise AnalysisCancelled()
            report_progress(logger, 970)
            with output_path.open("rb") as stream:
                results = pickle.load(stream)
            report_progress(logger, 980)
            return results


def _close_analysis_process(process, queue):
    """Release only the owned process and queue, including on cancellation."""
    if process.pid is not None:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        process.close()
    queue.close()
    queue.join_thread()
