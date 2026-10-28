"""Analysis milestones advance the existing bar without adding UI/log text."""

import ast
import logging
from importlib.metadata import distribution
from pathlib import Path
from threading import Event

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_job
from PySide6.QtCore import QThread
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from test_scientific_equivalence import assert_equivalent, upstream_synthetic

from paradigma_studio.analysis_process import AnalysisCancelled, run_isolated_analysis
from paradigma_studio.analysis_progress import (
    COMPLETED,
    STAGES,
    AnalysisProgress,
    PipelineProgressHandler,
    ProgressLogHandler,
    RecordingProgress,
    report_progress,
)
from paradigma_studio.core import analyze


def message(handler, text):
    handler.handle(logging.LogRecord("official", logging.INFO, "", 0, text, (), None))


def wait_for_progress(window, value):
    for _ in range(300):
        if window.progress.value() == value:
            return
        QTest.qWait(10)
    assert window.progress.value() == value


def test_nested_shares_are_monotonic_deduplicated_and_finish_exactly():
    values = []
    progress = AnalysisProgress(values.append)
    first = progress.span(100, 300)
    first.report(500)
    first.report(0)
    first.report(500)
    first.report(float("nan"))
    first.report(1000)
    second = progress.span(300, 1000)
    second.report(500)
    second.report(1000)
    assert values == [200, 300, 650, 1000]


def test_official_starts_count_predecessors_and_weight_recording_sections():
    values = []
    handler = PipelineProgressHandler(AnalysisProgress(values.append), [1, 3], ["tremor"])
    message(handler, "Processing DataFrame 1/2: first")
    message(handler, "Step 1: Preprocessing gyroscope data")
    assert values == [0]
    message(handler, "Step 2: Extracting tremor features")
    assert values[-1] == 53
    message(handler, "Tremor analysis completed: 3 windows")
    message(handler, "Processing DataFrame 2/2: second")
    message(handler, "Step 3: Detecting tremor")
    assert values[-1] == 531
    message(handler, "Something else: Step 99 done")
    message(handler, "Processing DataFrame 1/2: first")
    message(handler, "Step 1: Preprocessing gyroscope data")
    assert values[-1] == 531
    message(handler, "Step 4: Combining quantifications from all files")
    message(handler, "Step 5: Aggregating results across all files")
    assert values[-2:] == [850, 875]
    assert values == sorted(set(values))


def test_skipped_or_failed_modules_resolve_when_the_next_module_starts():
    values = []
    handler = PipelineProgressHandler(AnalysisProgress(values.append), [1], ["gait", "tremor"])
    message(handler, "Processing DataFrame 1/1: recording")
    message(handler, "Step 1: Preprocessing IMU data")
    message(handler, "Gait pipeline failed on recording")
    assert values == [0]
    message(handler, "Step 1: Preprocessing gyroscope data")
    assert values[-1] == 540  # Seven gait stages resolved out of eleven total.
    message(handler, "Tremor analysis completed: 0 windows")
    assert values[-1] == 850


def test_unknown_scope_and_duplicate_pulse_announcements_cannot_invent_progress():
    values = []
    handler = PipelineProgressHandler(AnalysisProgress(values.append), [1], ["pulse_rate"])
    message(handler, "Step 3: Signal quality classification")
    message(handler, "Processing DataFrame 2/7: unexpected")
    assert not values
    message(handler, "Processing DataFrame 1/1: recording")
    message(handler, "Step 5: Quantifying pulse rate")
    message(handler, "Step 4: Pulse rate estimation")
    assert values == [0, 637]


@pytest.mark.parametrize("pipeline", ["gait", "tremor", "pulse_rate"])
def test_progress_adapter_messages_match_the_installed_official_pipeline(pipeline):
    path = distribution("paradigma").locate_file(f"paradigma/pipelines/{pipeline}_pipeline.py")
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert set(STAGES[pipeline]) <= set(strings)
    assert any(value.startswith(COMPLETED[pipeline]) for value in strings)


def test_parallel_interleaving_uses_sample_weights_and_never_goes_backwards():
    values = []
    logger = logging.Logger("progress")
    logger.addHandler(ProgressLogHandler(values.append))
    progress = RecordingProgress(logger, {"small": 1, "large": 3})
    progress.report("large", 500)
    progress.report("small", 1000)
    progress.report("large", 200)
    progress.report("missing", 1000)
    progress.report("large", 1000)
    assert values == [350, 570, 900]


def test_progress_listener_does_not_turn_updates_into_log_messages():
    values, records = [], []
    logger = logging.Logger("progress", logging.INFO)
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record.getMessage())
    logger.addHandler(handler)
    logger.addHandler(ProgressLogHandler(values.append))
    logger.info("Existing analysis log")
    for value in (250, 250, -1, 1001, True, "50"):
        report_progress(logger, value)
    assert values == [250]
    assert records == ["Existing analysis log"]


@pytest.fixture
def live_analysis(window):
    entered, release, cancel = Event(), Event(), Event()
    completed = []
    window._job_state._analysis_stop = cancel

    def operation(logger):
        entered.set()
        while not release.wait(0.01):
            if cancel.is_set():
                raise AnalysisCancelled()
        if cancel.is_set():
            raise AnalysisCancelled()
        report_progress(logger, 980)
        return "results"

    def ready(payload):
        assert QThread.currentThread() is QApplication.instance().thread()
        assert window.progress.value() < 1000
        completed.append(payload)

    window.start_job(operation, ready)
    worker = window._job_state.worker
    for _ in range(500):
        if entered.is_set():
            break
        QTest.qWait(10)
    assert entered.is_set()
    try:
        yield worker, release, cancel, completed
    finally:
        release.set()
        wait_for_job(window)


def test_bar_uses_the_same_layout_and_no_added_text_with_coalesced_updates(window, live_analysis):
    worker, release, _cancel, completed = live_analysis
    controller = window._job_controller
    QApplication.instance().processEvents()
    geometry = window.progress.geometry()
    status = window.status.text()
    assert (window.progress.minimum(), window.progress.maximum(), window.progress.value()) == (
        0,
        1000,
        0,
    )
    assert not window.progress.isTextVisible() and window.progress.height() == 4
    changes = QSignalSpy(window.progress.valueChanged)
    for value in (100, 400, 250, 700, 700):
        controller.analysis_progress(worker, value)
    assert window.progress.value() == 0
    wait_for_progress(window, 700)
    assert window.progress.value() == 700 and changes.count() == 1
    assert window.progress.geometry() == geometry and window.status.text() == status
    assert not window.log.toPlainText()
    controller.analysis_progress(object(), 950)
    controller.analysis_progress(worker, 1000)
    controller.analysis_progress(worker, -1)
    assert not controller._progress_timer.isActive()
    assert window.progress.value() == 700
    release.set()
    wait_for_job(window)
    assert completed == ["results"]
    assert window.progress.value() == 1000 and window.progress.isHidden()


def test_cancelling_freezes_the_bar_and_discards_late_updates(window, live_analysis):
    worker, _release, cancel, completed = live_analysis
    controller = window._job_controller
    controller.analysis_progress(worker, 400)
    wait_for_progress(window, 400)
    controller.stop_analysis()
    controller.analysis_progress(worker, 980)
    QTest.qWait(230)
    wait_for_job(window)
    assert cancel.is_set() and not completed
    assert window.progress.value() == 400 and window.progress.isHidden()
    assert not controller._progress_timer.isActive()


def test_late_worker_updates_cannot_change_a_new_job(window, live_analysis):
    old, release, _cancel, _completed = live_analysis
    release.set()
    wait_for_job(window)
    new_release = Event()
    window._job_state._analysis_stop = Event()
    window.start_job(lambda logger: new_release.wait(5), lambda _: None)
    try:
        window._job_controller.analysis_progress(old, 900)
        QTest.qWait(230)
        assert window.progress.value() == 0
    finally:
        new_release.set()
        wait_for_job(window)


def test_other_background_jobs_keep_their_busy_indicator(window):
    release = Event()

    def operation(logger):
        report_progress(logger, 600)
        return release.wait(5)

    window.start_job(operation, lambda _: None)
    try:
        QTest.qWait(230)
        assert window.progress.minimum() == window.progress.maximum() == 0
        assert not window.progress.isTextVisible()
    finally:
        release.set()
        wait_for_job(window)


def test_failed_analysis_does_not_reach_full_progress(window):
    window._job_state._analysis_stop = Event()

    def operation(logger):
        report_progress(logger, 700)
        raise ValueError("controlled failure")

    window.start_job(operation, lambda _: pytest.fail("A failed job cannot deliver results"))
    wait_for_job(window)
    assert window.progress.isHidden() and window.progress.value() < 1000
    assert not window._job_controller._progress_timer.isActive()


@pytest.mark.scientific
@pytest.mark.parametrize("pipelines", [["gait", "tremor"], ["gait", "tremor", "pulse_rate"]])
def test_progress_reporting_preserves_scientific_results_and_source(pipelines):
    frame = upstream_synthetic("gait")
    frame["green"] = 1 + np.sin(2 * np.pi * 1.2 * frame.time)
    frame["time"] += np.where(np.arange(len(frame)) >= len(frame) // 2, 5.0, 0.0)
    original = frame.copy(deep=True)
    values = []
    settings = {"pipelines": pipelines, "split_by_gaps": True}
    expected = analyze(frame, **settings)
    actual = analyze(frame, progress=AnalysisProgress(values.append), **settings)
    assert_equivalent(actual, expected)
    pd.testing.assert_frame_equal(frame, original)
    assert values == sorted(set(values)) and values[-1] == 1000
    assert len(values) > 10


@pytest.mark.parametrize("workers", [1, 2])
def test_spawned_progress_reaches_the_parent_without_becoming_log_text(
    synthetic_imu, workers, monkeypatch
):
    from paradigma_studio import analysis_process

    monkeypatch.setattr(analysis_process, "parallel_worker_count", lambda *_: workers)
    frame = synthetic_imu.iloc[:2000].copy()
    frames = {"small": frame, "large": synthetic_imu}
    logger = logging.Logger("progress-parent", logging.INFO)
    values = []
    logger.addHandler(ProgressLogHandler(values.append))
    result = run_isolated_analysis(
        frames, {"pipelines": ["tremor"]}, logger, Event(), max_workers=workers
    )
    assert result["quantifications"]["tremor"] is not None
    assert values == sorted(values) and values[-1] == 980
    assert any(120 < value < 900 for value in values)
