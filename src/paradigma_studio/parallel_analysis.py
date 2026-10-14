"""Parent-owned recording workers, bounded dispatch and deterministic result merging."""

from __future__ import annotations

import logging
import multiprocessing
import pickle
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from queue import Empty
from typing import TYPE_CHECKING, Any

from .contracts import AnalysisResults, AnalysisSettings

if TYPE_CHECKING:
    from multiprocessing.process import BaseProcess
    from multiprocessing.queues import Queue
    from threading import Event

    import pandas as pd


@dataclass(frozen=True)
class RecordingTask:
    index: int
    input_path: Path
    output_path: Path
    key: str = ""


def run_parallel_analysis(
    frames: dict[str, pd.DataFrame],
    settings: AnalysisSettings,
    logger: logging.Logger,
    cancel: Event,
    workers: int,
) -> AnalysisResults:
    """Own every worker directly, so cancellation never leaves grandchildren."""
    from .analysis_process import AnalysisCancelled
    from .core import validate_recordings

    validate_recordings(frames)
    if workers != 2 or len(frames) < 2:
        raise ValueError("Parallel analysis requires two workers and multiple recordings.")
    context = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="paradigma-analysis-") as directory:
        root = Path(directory)
        tasks: Queue[RecordingTask] = context.Queue(maxsize=workers)
        events: Queue[Any] = context.Queue()
        processes = [
            context.Process(target=_recording_worker, args=(tasks, events, settings), daemon=True)
            for _ in range(workers)
        ]
        try:
            if cancel.is_set():
                raise AnalysisCancelled()
            for process in processes:
                process.start()
            logger.info("Processing %s recordings with %s workers", len(frames), workers)
            paths = _dispatch_recordings(
                frames, root, tasks, events, processes, logger, cancel, workers
            )
            payload, output = root / "merge-input.pkl", root / "results.pkl"
            _write_pickle(payload, paths)
            tasks.put(RecordingTask(len(frames), payload, output))
            _wait_for_merge(len(frames), events, processes, logger, cancel)
            if cancel.is_set():
                raise AnalysisCancelled()
            with output.open("rb") as stream:
                return pickle.load(stream)
        finally:
            _close_workers(processes, tasks, events)


def _recording_worker(tasks, events, settings):
    try:
        _run_worker_loop(tasks, events, settings)
    except Exception as exc:
        events.put(("failed", f"{type(exc).__name__}: {exc}"))


def _run_worker_loop(tasks, events, settings):
    from paradigma.orchestrator import run_paradigma
    from threadpoolctl import threadpool_limits

    from .analysis_process import QueueLogHandler

    # Import native libraries before applying the limit; each process gets one
    # native computation thread instead of multiplying BLAS/OpenMP thread pools.
    del run_paradigma
    with threadpool_limits(limits=1):
        while True:
            task = tasks.get()
            logger = logging.Logger("paradigma-studio-recording", logging.INFO)
            logger.addHandler(QueueLogHandler(events, recording=task.key))
            _execute_task(task, settings, logger)
            events.put(("task_completed", task.index))


def _execute_task(task: RecordingTask, settings: AnalysisSettings, logger: logging.Logger) -> None:
    from .core import analyze
    from .recording_results import merge_recording_results

    with task.input_path.open("rb") as stream:
        payload = pickle.load(stream)
    if task.key:
        logger.info("Processing recording %s", task.key)
        result = analyze(
            payload,
            logger=logger,
            **{
                **settings,
                "output_dir": str(task.output_path.parent / f"outputs-{task.index}"),
                "run_steps": ["preprocessing", "classification", "quantification"],
            },
        )
    else:
        outputs = []
        for path in payload:
            with path.open("rb") as stream:
                outputs.append(pickle.load(stream))
        result = merge_recording_results(outputs, settings, logger)
    _write_pickle(task.output_path, result)


def _dispatch_recordings(frames, root, tasks, events, processes, logger, cancel, workers):
    pending = iter(enumerate(frames.items()))
    paths = [root / f"result-{index}.pkl" for index in range(len(frames))]
    for _ in range(workers):
        _submit_next(pending, root, paths, tasks, cancel)
    completed = set()
    while len(completed) < len(frames):
        event = _receive_event(events, processes, logger, cancel)
        if event[0] == "task_completed":
            index = event[1]
            if index in completed or not 0 <= index < len(paths) or not paths[index].is_file():
                raise RuntimeError("Analysis worker returned an invalid recording completion.")
            completed.add(index)
            logger.info(
                "Completed recording %s/%s: %s", len(completed), len(frames), list(frames)[index]
            )
            _submit_next(pending, root, paths, tasks, cancel)
    return paths


def _submit_next(
    pending: Iterator, root: Path, paths: list[Path], tasks: Queue, cancel: Event
) -> None:
    from .analysis_process import AnalysisCancelled

    if cancel.is_set():
        raise AnalysisCancelled()
    item = next(pending, None)
    if item is not None:
        index, (key, frame) = item
        path = root / f"input-{index}.pkl"
        _write_pickle(path, {key: frame})
        if cancel.is_set():
            raise AnalysisCancelled()
        tasks.put(RecordingTask(index, path, paths[index], key))


def _receive_event(events, processes, logger, cancel):
    from .analysis_process import AnalysisCancelled

    while True:
        if cancel.is_set():
            raise AnalysisCancelled()
        try:
            event = events.get(timeout=0.1)
        except Empty:
            exited = next((process for process in processes if not process.is_alive()), None)
            if exited is not None:
                raise RuntimeError(
                    f"Analysis worker exited unexpectedly ({exited.exitcode})."
                ) from None
            continue
        if event[0] == "log":
            logger.log(event[1], event[2])
        elif event[0] == "failed":
            raise RuntimeError(event[1])
        else:
            return event


def _wait_for_merge(index, events, processes, logger, cancel):
    event = _receive_event(events, processes, logger, cancel)
    if event != ("task_completed", index):
        raise RuntimeError("Analysis worker returned an invalid aggregate completion.")


def _write_pickle(path: Path, value: Any) -> None:
    # Only parent-created private paths are used, never user-supplied pickles.
    with path.open("wb") as stream:
        pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)


def _close_workers(processes: Sequence[BaseProcess], tasks: Queue, events: Queue) -> None:
    for process in processes:
        if process.pid is not None and process.is_alive():
            process.terminate()
    for process in processes:
        if process.pid is None:
            continue
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        process.close()
    # Queued work may be abandoned on cancellation. Never wait for its feeder
    # thread to flush to children that have already been terminated.
    for queue in (tasks, events):
        queue.cancel_join_thread()
        queue.close()
