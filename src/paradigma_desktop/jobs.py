"""Background job signals and consistent warning/error forwarding."""

import logging
from PySide6.QtCore import QThread, Signal
from .history import failure_log, error_summary
from .analysis_process import AnalysisCancelled


class SignalHandler(logging.Handler):
    def __init__(self, signal, warning=None, error=None):
        super().__init__()
        self.signal = signal
        self.warning = warning
        self.error = error

    def emit(self, record):
        self.signal.emit(self.format(record))
        if error_summary(record.getMessage()):
            return  # Keep the log; count the individual pipeline failures.
        if record.levelno >= logging.ERROR or failure_log(record.getMessage()):
            if self.error is not None:
                self.error.emit(record.getMessage())
        elif self.warning is not None and record.levelno >= logging.WARNING:
            self.warning.emit(record.getMessage())


class Worker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    message = Signal(str)
    warning = Signal(str)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        logger = logging.Logger("paradigma-desktop", logging.INFO)
        handler = SignalHandler(self.message, self.warning, self.error)
        logger.addHandler(handler)
        package_logger = logging.getLogger("paradigma")
        previous_level = package_logger.level
        package_logger.setLevel(logging.INFO)
        package_logger.addHandler(handler)
        try:
            self.completed.emit(self.operation(logger))
        except AnalysisCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            package_logger.removeHandler(handler)
            package_logger.setLevel(previous_level)
            handler.close()
