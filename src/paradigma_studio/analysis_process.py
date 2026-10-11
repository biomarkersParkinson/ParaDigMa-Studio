"""Interruptible analysis with parent-owned temporary files and process cleanup."""

import logging
import multiprocessing
from pathlib import Path
import pickle
from queue import Empty
import tempfile


class AnalysisCancelled(Exception):
    pass


class QueueLogHandler(logging.Handler):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def emit(self, record):
        self.queue.put(("log", record.levelno, record.getMessage()))


def _analyze_child(input_path, output_path, settings, queue):
    try:
        from .core import analyze

        logger = logging.Logger("paradigma-studio", logging.INFO)
        logger.addHandler(QueueLogHandler(queue))
        # These private files are created by this process's parent, never user inputs.
        with open(input_path, "rb") as stream:
            frame = pickle.load(stream)
        results = analyze(frame, logger=logger, **settings)
        with open(output_path, "wb") as stream:
            pickle.dump(results, stream, protocol=pickle.HIGHEST_PROTOCOL)
        queue.put(("completed",))
    except Exception as exc:
        queue.put(("failed", f"{type(exc).__name__}: {exc}"))


def run_isolated_analysis(frame, settings, logger, cancel):
    """Stop only the owned child; never terminate Qt's thread or other programs."""
    context = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="paradigma-analysis-") as directory:
        input_path, output_path = Path(directory) / "input.pkl", Path(directory) / "results.pkl"
        with input_path.open("wb") as stream:
            pickle.dump(frame, stream, protocol=pickle.HIGHEST_PROTOCOL)
        if cancel.is_set():
            raise AnalysisCancelled()
        queue = context.Queue()
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
            while True:
                if cancel.is_set():
                    raise AnalysisCancelled()
                try:
                    event = queue.get(timeout=0.1)
                except Empty:
                    if not process.is_alive():
                        raise RuntimeError(
                            f"Analysis process exited unexpectedly ({process.exitcode})."
                        )
                    continue
                if event[0] == "log":
                    logger.log(event[1], event[2])
                elif event[0] == "failed":
                    raise RuntimeError(event[1])
                elif event[0] == "completed":
                    if cancel.is_set():
                        raise AnalysisCancelled()
                    with output_path.open("rb") as stream:
                        return pickle.load(stream)
        finally:
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
