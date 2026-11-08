"""Bounded thread/process loading with parent-owned progress, logs and results."""

from __future__ import annotations

import logging
import multiprocessing
import sys
import traceback
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import suppress
from dataclasses import dataclass
from multiprocessing.connection import wait as wait_connections
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias, cast

from .analysis_limits import GIB, _available_cpu_count, available_memory
from .analysis_progress import ProgressCallback
from .contracts import AnalysisLogEvent, PathInput
from .loading_timing import LoadTiming, defer_loading_error, measure_load

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess

    import pandas as pd

    if sys.platform == "win32":
        from multiprocessing.connection import PipeConnection

        ReaderConnection: TypeAlias = Connection | PipeConnection
    else:
        ReaderConnection: TypeAlias = Connection

LoadMode: TypeAlias = Literal["auto", "sequential", "threads", "processes"]
LoadResult: TypeAlias = "tuple[pd.DataFrame, LoadTiming]"


class LoadReader(Protocol):
    def __call__(self, path: PathInput, *, allow_pickle: bool = False) -> pd.DataFrame: ...


LoadCompleted: TypeAlias = "Callable[[int, pd.DataFrame, LoadTiming], None]"
LoadEvent: TypeAlias = (
    AnalysisLogEvent
    | tuple[Literal["loaded"], int, "pd.DataFrame", LoadTiming]
    | tuple[Literal["failed"], int, str, str, str]
)


@dataclass(frozen=True)
class LoadingPlan:
    mode: Literal["sequential", "threads", "processes"]
    workers: int
    reason: str


class LoadingBatch:
    """Collect completions in the coordinator, independently of completion order."""

    def __init__(
        self, paths: list[str], logger: logging.Logger | None, progress: ProgressCallback | None
    ) -> None:
        self.paths, self.logger, self.progress = paths, logger, progress
        self.frames: dict[int, pd.DataFrame] = {}
        self.totals = LoadTiming()
        self.started = perf_counter()
        if progress is not None and len(paths) > 1:
            progress(0)

    def begin(self, index: int) -> None:
        if self.logger is not None:
            self.logger.info("Loading recording_%03d: %s", index + 1, self.paths[index])

    def completed(self, index: int, frame: pd.DataFrame, timing: LoadTiming) -> None:
        self.frames[index] = frame
        self.totals.read_decode_s += timing.read_decode_s
        self.totals.conversion_s += timing.conversion_s
        if self.logger is not None:
            self.logger.info(
                "Loaded recording_%03d in %.3f s (read/decode %.3f s; conversion %.3f s).",
                index + 1,
                timing.total_s,
                timing.read_decode_s,
                timing.conversion_s,
            )
        if self.progress is not None:
            self.progress(1000 * len(self.frames) // len(self.paths))

    def report(self) -> None:
        if self.logger is not None:
            self.logger.info(
                "Recording read/convert wall time: %.3f s; completed %s/%s files. Read/decode %.3f worker-s; conversion %.3f worker-s (summed across completed files).",
                perf_counter() - self.started,
                len(self.frames),
                len(self.paths),
                self.totals.read_decode_s,
                self.totals.conversion_s,
            )


def loading_plan(
    paths: Sequence[str],
    sample_bytes: int,
    sample_work_s: float,
    *,
    mode: LoadMode = "auto",
    max_workers: int = 2,
    sample_suffix: str | None = None,
) -> LoadingPlan:
    """Choose a measured format strategy; reserve RAM for the retained batch/UI."""
    if mode not in {"auto", "sequential", "threads", "processes"}:
        raise ValueError("Loading mode must be auto, sequential, threads or processes.")
    if (
        isinstance(max_workers, bool)
        or not isinstance(max_workers, int)
        or max_workers not in (1, 2)
    ):
        raise ValueError("max_workers must be 1 or 2.")
    if len(paths) < 2 or max_workers == 1 or mode == "sequential":
        return LoadingPlan("sequential", 1, "Single-file/small batch or caller worker limit.")
    available = available_memory()
    # Retained frames are separate from each reader's transient buffers. AVRO
    # Python records may expand far beyond the finished numeric frame.
    working = max(512 * 1024**2, sample_bytes * 32)
    reserve = GIB + sample_bytes * len(paths)
    if available is None or available < reserve + 2 * working:
        return LoadingPlan("sequential", 1, "Insufficient or unknown RAM headroom.")
    if mode != "auto":
        return LoadingPlan(mode, 2, "Explicit benchmark/caller strategy.")
    if _available_cpu_count() < 3:
        return LoadingPlan("sequential", 1, "Reserve a CPU for the interface.")
    suffixes = {Path(path).suffix.lower() for path in paths}
    if sample_suffix is not None:
        suffixes.add(sample_suffix.lower())
    return _format_plan(suffixes, sample_bytes, sample_work_s, len(paths))


def _format_plan(
    suffixes: set[str], sample_bytes: int, sample_work_s: float, remaining: int
) -> LoadingPlan:
    if suffixes == {".avro"}:
        if not _can_spawn():
            return LoadingPlan(
                "sequential", 1, "Interactive or daemonic caller requires sequential loading."
            )
        if remaining >= 8 and sample_work_s * remaining >= 4.0:
            return LoadingPlan("processes", 2, "AVRO decoding amortizes reusable process startup.")
        return LoadingPlan("sequential", 1, "AVRO batch is too small to amortize process startup.")
    if suffixes <= {".csv", ".parquet", ".json", ".cwa"} and sample_bytes >= 1024**2:
        if suffixes & {".json", ".cwa"} and sample_work_s < 0.05:
            return LoadingPlan(
                "sequential", 1, "Small TSDF/CWA reads do not reliably benefit from threads."
            )
        return LoadingPlan("threads", 2, "Native readers share tables without process transfers.")
    return LoadingPlan("sequential", 1, "Small, mixed CPU/native or trusted-pickle workload.")


def _can_spawn() -> bool:
    main_file = getattr(sys.modules.get("__main__"), "__file__", None)
    return not multiprocessing.current_process().daemon and (
        bool(getattr(sys, "frozen", False))
        or isinstance(main_file, str)
        and bool(main_file)
        and not main_file.startswith("<")
    )


def read_recording(
    reader: LoadReader, path: PathInput, allow_pickle: bool, recording_index: int | None = None
) -> LoadResult:
    timing = LoadTiming(
        recording=f"recording_{recording_index + 1:03d}" if recording_index is not None else ""
    )
    suffix = f" [{timing.recording}]" if timing.recording else ""
    with measure_load(timing):
        try:
            frame = reader(path, allow_pickle=allow_pickle)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{Path(path).name}: {exc}{suffix}") from exc
        except Exception as exc:
            # Keep the original exception identity/type and annotate its traceback.
            exc.add_note(f"Loading source: {path}{suffix}")
            raise
    return frame, timing


def load_parallel(
    paths: Sequence[tuple[int, str]],
    plan: LoadingPlan,
    reader: LoadReader,
    allow_pickle: bool,
    completed: LoadCompleted,
    logger: logging.Logger | None,
    started: Callable[[int], None],
) -> None:
    if plan.mode == "threads":
        _thread_load(paths, plan.workers, reader, allow_pickle, completed, started)
    elif plan.mode == "processes":
        _process_load(paths, plan.workers, allow_pickle, completed, logger, started)
    else:
        raise ValueError("A parallel loading plan is required.")


def _thread_load(
    paths: Sequence[tuple[int, str]],
    workers: int,
    reader: LoadReader,
    allow_pickle: bool,
    completed: LoadCompleted,
    started: Callable[[int], None],
) -> None:
    pending = iter(paths)
    active: dict[Future[LoadResult], int] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="paradigma-load") as pool:

        def submit() -> None:
            item = next(pending, None)
            if item is not None:
                index, path = item
                started(index)
                active[pool.submit(read_recording, reader, path, allow_pickle, index)] = index

        for _ in range(workers):
            submit()
        try:
            while active:
                ready, _ = wait(active, return_when=FIRST_COMPLETED)
                # Drain this bounded completion set before submitting more work.
                results = [(active.pop(future), future.result()) for future in ready]
                for index, (frame, timing) in results:
                    completed(index, frame, timing)
                for _ in results:
                    submit()
        finally:
            for future in active:
                future.cancel()


class _PipeLog(logging.Handler):
    def __init__(self, connection: ReaderConnection, recording: str) -> None:
        super().__init__()
        self.connection, self.recording = connection, recording

    def emit(self, record: logging.LogRecord) -> None:
        details = record.exc_text
        if not details and record.exc_info:
            details = logging.Formatter().formatException(record.exc_info)
        message = f"{record.getMessage()} [{self.recording}]"
        event: AnalysisLogEvent = (
            ("log", record.levelno, message, details)
            if details
            else ("log", record.levelno, message)
        )
        if record.levelno >= logging.ERROR:
            diagnostic: AnalysisLogEvent = (
                ("log", logging.INFO, f"ERROR: {message}", details)
                if details
                else ("log", logging.INFO, f"ERROR: {message}")
            )
            if defer_loading_error(
                lambda: self.connection.send(event), lambda: self.connection.send(diagnostic)
            ):
                return
        self.connection.send(event)


def _load_worker(connection: ReaderConnection) -> None:
    index = -1
    try:
        while True:
            command = connection.recv()
            if command is None:
                return
            index, path, allow_pickle = cast("tuple[int, str, bool]", command)
            handler = _PipeLog(connection, f"recording_{index + 1:03d}")
            package_logger = logging.getLogger("paradigma")
            package_logger.addHandler(handler)
            previous = package_logger.level
            package_logger.setLevel(logging.INFO)
            try:
                from .core import load_sensor_file

                frame, timing = read_recording(load_sensor_file, path, allow_pickle, index)
                connection.send(("loaded", index, frame, timing))
                del frame
            except Exception as exc:  # noqa: BLE001 -- Report arbitrary decoder failures across processes.
                connection.send(
                    ("failed", index, type(exc).__name__, str(exc), traceback.format_exc())
                )
                return
            finally:
                package_logger.removeHandler(handler)
                package_logger.setLevel(previous)
                handler.close()
    except Exception as exc:  # noqa: BLE001 -- Include initialization/import failures in parent diagnostics.
        with suppress(BrokenPipeError, EOFError, OSError):
            connection.send(("failed", index, type(exc).__name__, str(exc), traceback.format_exc()))
    finally:
        connection.close()


@dataclass
class _ReaderProcess:
    process: BaseProcess
    connection: ReaderConnection
    index: int | None = None
    path: str = ""


def _submit_process(
    worker: _ReaderProcess,
    pending: Iterator[tuple[int, str]],
    allow_pickle: bool,
    started: Callable[[int], None],
) -> None:
    item = next(pending, None)
    if item is not None:
        worker.index, worker.path = item
        started(worker.index)
        worker.connection.send((*item, allow_pickle))
    else:
        worker.index = None


def _process_load(
    paths: Sequence[tuple[int, str]],
    count: int,
    allow_pickle: bool,
    completed: LoadCompleted,
    logger: logging.Logger | None,
    started: Callable[[int], None],
) -> None:
    context = multiprocessing.get_context("spawn")
    workers: list[_ReaderProcess] = []
    pending = iter(paths)
    succeeded = False
    started_at = perf_counter()
    try:
        for _ in range(min(count, len(paths))):
            parent, child = context.Pipe()
            process = context.Process(target=_load_worker, args=(child,), daemon=True)
            worker = _ReaderProcess(process, parent)
            workers.append(worker)
            try:
                process.start()
            finally:
                child.close()
            _submit_process(worker, pending, allow_pickle, started)
        if logger is not None:
            logger.debug(
                "Loading worker processes started.",
                extra={"loading_worker_pids": tuple(worker.process.pid for worker in workers)},
            )
        _receive_loads(workers, pending, allow_pickle, completed, logger, started)
        succeeded = True
    finally:
        _close_readers(workers, succeeded)
        if logger is not None:
            logger.info(
                "Loading process pool wall time (startup/transfer/cleanup included): %.3f s.",
                perf_counter() - started_at,
            )


def _receive_loads(
    workers: Sequence[_ReaderProcess],
    pending: Iterator[tuple[int, str]],
    allow_pickle: bool,
    completed: LoadCompleted,
    logger: logging.Logger | None,
    started: Callable[[int], None],
) -> None:
    while active := [worker for worker in workers if worker.index is not None]:
        ready = wait_connections([worker.connection for worker in active], timeout=0.1)
        for worker in active:
            if worker.connection not in ready:
                if worker.process.is_alive():
                    continue
                if not worker.connection.poll():
                    raise RuntimeError(
                        f"{Path(worker.path).name}: Loading worker exited unexpectedly ({worker.process.exitcode})."
                    )
            if _receive_worker(worker, completed, logger):
                _submit_process(worker, pending, allow_pickle, started)


def _receive_worker(
    worker: _ReaderProcess, completed: LoadCompleted, logger: logging.Logger | None
) -> bool:
    from .analysis_process import forward_analysis_log

    try:
        # Only the directly owned child writes this private connection.
        event = cast(LoadEvent, worker.connection.recv())
    except EOFError as exc:
        raise RuntimeError(
            f"{Path(worker.path).name}: Loading worker closed its connection unexpectedly."
        ) from exc
    if event[0] == "log":
        if logger is not None:
            forward_analysis_log(logger, event)
        return False
    if event[0] == "failed":
        if logger is not None:
            logger.info("%s", event[4])
        if event[2] == "ValueError":
            raise ValueError(event[3])
        detail = event[3] if event[2] == "RuntimeError" else f"{event[2]}: {event[3]}"
        raise RuntimeError(f"{Path(worker.path).name}: {detail} [recording_{event[1] + 1:03d}]")
    if event[1] != worker.index:
        raise RuntimeError("Loading worker returned an invalid recording identifier.")
    completed(event[1], event[2], event[3])
    return True


def _close_readers(workers: Sequence[_ReaderProcess], succeeded: bool) -> None:
    for worker in workers:
        process = worker.process
        if process.pid is not None:
            if succeeded and process.is_alive():
                with suppress(BrokenPipeError, EOFError, OSError):
                    worker.connection.send(None)
            elif process.is_alive():
                process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
            process.close()
        worker.connection.close()
