"""Tracebacks survive error boundaries without changing notices or error counts."""

import logging
import pickle
from queue import SimpleQueue
from threading import Event
from types import SimpleNamespace

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication

from paradigma_studio import (
    analysis_process,
    app as desktop,
    core,
    parallel_analysis,
    recording_results,
    recordings,
)
from paradigma_studio.analysis_process import QueueLogHandler, forward_analysis_log
from paradigma_studio.history import new_run
from paradigma_studio.jobs import SignalHandler, Worker
from paradigma_studio.results_view import normalise_clock, time_bound
from paradigma_studio.ui.deferred import DeferredWidget


def captured_logger():
    messages, errors = [], []
    logger = logging.Logger("error-boundary", logging.INFO)
    logger.addHandler(
        SignalHandler(
            SimpleNamespace(emit=messages.append), error=SimpleNamespace(emit=errors.append)
        )
    )
    return logger, messages, errors


@pytest.mark.parametrize("outcome", ["completed", "cancelled", "failed"])
def test_worker_terminal_signal_preserves_traceback_and_restores_logging(outcome, request):
    # Exercise the boundary synchronously so coverage can trace this Qt thread
    # entry point. Integration tests separately start real QThreads and jobs.
    package_logger = logging.getLogger("paradigma")
    original_level = package_logger.level
    request.addfinalizer(lambda: package_logger.setLevel(original_level))
    package_logger.setLevel(logging.WARNING)
    existing_handler = logging.NullHandler()
    package_logger.addHandler(existing_handler)
    request.addfinalizer(lambda: package_logger.removeHandler(existing_handler))
    handlers, level = list(package_logger.handlers), package_logger.level
    result, terminal, messages, warnings = object(), [], [], []

    def operation(logger):
        assert package_logger.level == logging.INFO
        package_logger.info("Toolbox diagnostic")
        logger.warning("Some windows were excluded")
        if outcome == "cancelled":
            raise analysis_process.AnalysisCancelled()
        if outcome == "failed":
            raise ValueError("Unexpected pipeline failure")
        return result

    worker = Worker(operation)
    worker.completed.connect(lambda value: terminal.append(("completed", value)))
    worker.cancelled.connect(lambda: terminal.append(("cancelled", None)))
    worker.failed.connect(lambda message: terminal.append(("failed", message)))
    worker.message.connect(messages.append)
    worker.warning.connect(warnings.append)
    worker.run()

    expected = {
        "completed": result,
        "cancelled": None,
        "failed": "ValueError: Unexpected pipeline failure",
    }
    assert terminal == [(outcome, expected[outcome])]
    assert warnings == ["Some windows were excluded"]
    assert "Toolbox diagnostic" in messages
    assert package_logger.handlers == handlers and package_logger.level == level
    if outcome == "failed":
        assert "Traceback" in messages[-1] and "in operation" in messages[-1]
        assert "ValueError: Unexpected pipeline failure" in messages[-1]
        assert "Traceback" not in terminal[0][1]
    else:
        assert all("Traceback" not in message for message in messages)


@pytest.mark.parametrize("recording", ["", "recording_002"])
def test_remote_exception_log_keeps_stack_and_counts_one_original_error(recording):
    events = SimpleQueue()
    child = logging.Logger("child")
    child.addHandler(QueueLogHandler(events, recording))

    def aggregate():
        raise ValueError("No valid windows")

    try:
        aggregate()
    except ValueError as exc:
        child.exception("Failed to aggregate tremor results: %s", exc)

    logger, messages, errors = captured_logger()
    forward_analysis_log(logger, events.get_nowait())
    message = "Failed to aggregate tremor results: No valid windows"
    if recording:
        message += f" [{recording}]"
    assert errors == [message]
    assert len(messages) == 1 and messages[0].startswith(message)
    assert "Traceback" in messages[0] and "in aggregate" in messages[0]
    assert "ValueError: No valid windows" in messages[0]


@pytest.mark.parametrize("boundary", ["single", "parallel"])
def test_process_failure_emits_one_traceback_and_one_concise_failure(
    boundary, monkeypatch, tmp_path
):
    events = SimpleQueue()

    def fail(*args, **kwargs):
        raise RuntimeError("Unexpected child failure")

    if boundary == "single":
        source = tmp_path / "input.pkl"
        source.write_bytes(pickle.dumps(pd.DataFrame({"time": [0.0]})))
        monkeypatch.setattr(core, "analyze", fail)
        output = tmp_path / "output.pkl"
        analysis_process._analyze_child(source, output, {}, events)
        assert not output.exists()
    else:
        monkeypatch.setattr(parallel_analysis, "_run_worker_loop", fail)
        parallel_analysis._recording_worker(None, events, {})

    diagnostic = events.get_nowait()
    assert diagnostic[:2] == ("log", logging.INFO)
    assert "Traceback" in diagnostic[2] and "in fail" in diagnostic[2]
    assert "RuntimeError: Unexpected child failure" in diagnostic[2]
    assert events.get_nowait() == ("failed", "RuntimeError: Unexpected child failure")
    assert events.empty()


@pytest.mark.parametrize("workers", [1, 2])
def test_spawned_failure_keeps_original_child_stack_and_one_concise_failure(workers, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(analysis_process, "parallel_worker_count", lambda *_: workers)
    frames = {f"recording_{index}": pd.DataFrame({"time": [0.0]}) for index in range(workers)}
    messages, failures, errors = [], [], []
    worker = Worker(
        lambda logger: analysis_process.run_isolated_analysis(
            frames, {"pipelines": ["unknown"]}, logger, Event()
        )
    )
    worker.message.connect(messages.append)
    worker.failed.connect(failures.append)
    worker.error.connect(errors.append)
    worker.start()
    assert worker.wait(30000)
    application.processEvents()
    assert len(failures) == 1 and "ValueError: Unknown pipeline" in failures[0]
    assert "Traceback" not in failures[0] and not errors
    log = "\n".join(messages)
    assert "Traceback" in log and 'File "' in log and "in analyze" in log
    assert ("in _analyze_child" if workers == 1 else "in _execute_task") in log


def test_partial_module_failure_logs_stack_and_preserves_success(monkeypatch):
    successful = pd.DataFrame({"time": [0.0], "tremor_power": [1.0]})

    def analyze(frame, *, pipelines, **settings):
        if pipelines == ["pulse_rate"]:
            raise RuntimeError("Unavailable pulse-rate model")
        return {"quantifications": {"tremor": successful}}

    monkeypatch.setattr(core, "analyze", analyze)
    logger, messages, errors = captured_logger()
    result = core._analyze_pipeline_groups(None, ["tremor", "pulse_rate"], None, logger, False, {})
    assert result["quantifications"]["tremor"] is successful
    assert result["errors"] == [
        {
            "pipelines": ["pulse_rate"],
            "stage": "desktop_execution",
            "error": "RuntimeError: Unavailable pulse-rate model",
        }
    ]
    assert len(errors) == 1 and "Traceback" not in errors[0]
    assert "in analyze" in "\n".join(messages)


def test_partial_aggregation_failure_logs_stack_and_continues_other_modules(monkeypatch):
    def aggregate(combined, pipeline, settings):
        if pipeline == "tremor":
            raise RuntimeError("No valid tremor windows")
        combined["aggregations"][pipeline] = {"median": 60.0}

    monkeypatch.setattr(recording_results, "_aggregate_pipeline", aggregate)
    logger, messages, errors = captured_logger()
    combined = {"errors": [], "aggregations": {}}
    recording_results._aggregate_pipelines(combined, ["tremor", "pulse_rate"], {}, logger)
    assert combined["aggregations"] == {"tremor": {}, "pulse_rate": {"median": 60.0}}
    assert combined["errors"] == [
        {"pipeline": "tremor", "stage": "aggregation", "error": "No valid tremor windows"}
    ]
    assert len(errors) == 1 and "Traceback" not in errors[0]
    assert "in aggregate" in "\n".join(messages)


@pytest.mark.parametrize(
    "method,writer", [("export", "export_results"), ("export_csv", "export_table_csv")]
)
def test_export_failure_logs_stack_with_a_completed_run_selected(
    window, monkeypatch, tmp_path, method, writer
):
    frame = pd.DataFrame({"time": [0.0], "tremor_power": [1.0]})
    window.results = {"quantifications": {"tremor": frame}}
    window.selected_run = new_run("sensor.csv", {"pipelines": ["tremor"]})
    window.selected_run["status"] = "Completed"
    monkeypatch.setattr(window, "selected_export_table", lambda: ("quantifications/tremor", frame))
    monkeypatch.setattr(
        desktop.QFileDialog, "getSaveFileName", lambda *args: (str(tmp_path / "export.json"), "")
    )

    def fail(*args, **kwargs):
        raise RuntimeError("Unexpected writer failure")

    monkeypatch.setattr(desktop, writer, fail)
    getattr(window, method)()
    assert window.notice.text() == "Unexpected writer failure"
    log = window.log.toPlainText()
    assert "Traceback" in log and "in fail" in log
    assert "RuntimeError: Unexpected writer failure" in log
    assert window.selected_run["status"] == "Completed"  # Diagnostics did not change history.


def test_unexpected_loader_error_propagates_without_becoming_a_validation_error(monkeypatch):
    error = RuntimeError("Unexpected decoder failure")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(recordings, "load_sensor_file", fail)
    with pytest.raises(RuntimeError) as caught:
        recordings.load_recordings(["sensor.csv"])
    assert caught.value is error


@pytest.mark.parametrize("local_time", ["2026-03-29T02:30:00", "2026-10-25T02:30:00"])
def test_nonexistent_and_ambiguous_local_bounds_request_an_explicit_offset(local_time):
    clock = normalise_clock({"origin": "2026-01-01T00:00:00+01:00", "timezone": "Europe/Amsterdam"})
    with pytest.raises(ValueError, match="include a timezone offset"):
        time_bound(local_time, clock)
    assert time_bound(local_time + "+01:00", clock) > 0


def test_failed_deferred_initialization_preserves_exception_and_allows_retry(window):
    error = RuntimeError("Unavailable plotting dependency")
    attempts = []

    def initialize():
        attempts.append(True)
        if len(attempts) == 1:
            raise error

    widget = DeferredWidget(initialize, window)
    with pytest.raises(RuntimeError) as caught:
        widget.initialize()
    assert caught.value is error and not widget.initialized
    widget.initialize()
    widget.initialize()
    assert widget.initialized and len(attempts) == 2
