"""Keep large saved-JSON decoding outside the GUI interpreter's lock."""

from __future__ import annotations

import multiprocessing
import pickle
import tempfile
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from .contracts import AnalysisResults, PathInput, Provenance
from .history import load_verified_result_export
from .result_integrity import validate_checksum, validate_run_id

if TYPE_CHECKING:
    import logging
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess

ISOLATE_JSON_BYTES = 8 * 1024 * 1024


def _read_export_child(
    path: str, output: str, status: Connection, run_id: str, checksum: str
) -> None:
    try:
        value = load_verified_result_export(path, run_id, checksum)
        # The parent owns this private transfer file; user files remain JSON.
        with open(output, "wb") as stream:
            pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)
        status.send(None)
    except Exception as exc:  # noqa: BLE001 -- Transfer child failures with their traceback.
        # Preserve the child traceback across the job boundary without loading
        # exception objects or arbitrary user-selected pickle files.
        status.send((isinstance(exc, ValueError), str(exc), traceback.format_exc()))
    finally:
        status.close()


def load_saved_results(
    path: PathInput,
    logger: logging.Logger,
    *,
    run_id: str,
    checksum: object,
    isolate_bytes: int = ISOLATE_JSON_BYTES,
) -> tuple[Provenance, AnalysisResults]:
    """Verify every disk reopen, isolating large C JSON-decoder calls from Qt."""
    validate_run_id(run_id)
    checksum = validate_checksum(checksum)
    path = Path(path)
    if path.stat().st_size < isolate_bytes:
        return load_verified_result_export(path, run_id, checksum)
    context = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="paradigma-result-open-") as directory:
        output = Path(directory) / "results.pkl"
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_read_export_child,
            args=(str(path), str(output), sender, run_id, checksum),
            daemon=True,
        )
        try:
            process.start()
            sender.close()
            while not receiver.poll(0.1):
                if not process.is_alive():
                    raise RuntimeError(
                        f"Saved-result reader exited unexpectedly ({process.exitcode})."
                    )
            try:
                error = receiver.recv()
            except EOFError as exc:
                raise RuntimeError("Saved-result reader closed without a result.") from exc
            if error is not None:
                invalid, message, details = error
                logger.info(details)
                if invalid:
                    raise ValueError(message)
                raise RuntimeError(message)
            # Only the owned child writes this parent-created private path.
            with output.open("rb") as stream:
                return pickle.load(stream)
        finally:
            _close_reader(process)
            receiver.close()
            sender.close()


def _close_reader(process: BaseProcess) -> None:
    if process.pid is not None:
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        process.close()
