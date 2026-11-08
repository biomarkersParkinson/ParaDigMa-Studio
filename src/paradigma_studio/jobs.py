"""Background job signals and consistent warning/error forwarding."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from copy import copy

from PySide6.QtCore import QThread, Signal

from .analysis_process import AnalysisCancelled
from .analysis_progress import ProgressLogHandler
from .contracts import TextSignal
from .history import error_summary, failure_log
from .loading_timing import defer_loading_error, loading_recording


class SignalHandler(logging.Handler):
    def __init__(
        self, signal: TextSignal, warning: TextSignal | None = None, error: TextSignal | None = None
    ) -> None:
        super().__init__()
        self.signal = signal
        self.warning = warning
        self.error = error

    def emit(self, record: logging.LogRecord) -> None:
        # Native reader threads share the job handler. Tag their diagnostics in
        # the emitting thread, before forwarding them to the GUI owner.
        recording = loading_recording()
        if recording:
            record = copy(record)
            record.msg = f"{record.getMessage()} [{recording}]"
            record.args = ()
        self.signal.emit(self.format(record))
        if error_summary(record.getMessage()):
            return  # Keep the log; count the individual pipeline failures.
        if record.levelno >= logging.ERROR or failure_log(record.getMessage()):
            if self.error is not None:
                message = record.getMessage()
                error = self.error

                def publish_error() -> None:
                    error.emit(message)

                if not defer_loading_error(publish_error):
                    publish_error()
        elif self.warning is not None and record.levelno >= logging.WARNING:
            self.warning.emit(record.getMessage())


class Worker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    message = Signal(str)
    warning = Signal(str)
    error = Signal(str)
    cancelled = Signal()
    progress = Signal(object, int)

    def __init__(self, operation: Callable[[logging.Logger], object]) -> None:
        super().__init__()
        self.operation = operation

    def run(self) -> None:
        logger = logging.Logger("paradigma-studio", logging.INFO)
        handler = SignalHandler(self.message, self.warning, self.error)
        logger.addHandler(handler)
        progress = ProgressLogHandler(lambda value: self.progress.emit(self, value))
        logger.addHandler(progress)
        package_logger = logging.getLogger("paradigma")
        previous_level = package_logger.level
        package_logger.setLevel(logging.INFO)
        package_logger.addHandler(handler)
        try:
            self.completed.emit(self.operation(logger))
        except AnalysisCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 -- Final boundary for arbitrary Qt jobs.
            # The Qt worker is the final boundary for arbitrary job operations.
            # Log diagnostics separately so failed emits/counts one concise error.
            self.message.emit(traceback.format_exc())
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            package_logger.removeHandler(handler)
            package_logger.setLevel(previous_level)
            handler.close()
            progress.close()
