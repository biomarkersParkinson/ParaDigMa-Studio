"""Actual process ownership, reuse, cancellation and resource-aware routing.

Protocol workers here control scheduling only. Scientific tests separately
exercise unmodified real ParaDigMa pipelines in actual spawned processes.
"""

import logging
import multiprocessing
import os
import pickle
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import numpy as np
import pandas as pd
import pytest

from paradigma_studio import analysis_limits, analysis_process, parallel_analysis


class Messages(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def protocol_worker(tasks, events, settings):
    while True:
        task = tasks.get()
        pid = os.getpid()
        if task.key:
            events.put(("log", logging.INFO, f"started:{pid}:{task.index}"))
            if settings.get("mode") == "processing":
                time.sleep(60)
            if settings.get("mode") == "failure":
                events.put(("failed", "RuntimeError: controlled worker failure"))
                return
            if settings.get("mode") == "crash":
                os._exit(7)
            if task.index < 2:
                settings["gate"].wait(timeout=15)
            if task.index == 0:
                time.sleep(0.2)  # Finish out of order to exercise deterministic collection.
            result = {"index": task.index, "key": task.key, "pid": pid}
        else:
            events.put(("log", logging.INFO, f"merging:{pid}"))
            if settings.get("mode") == "aggregation":
                time.sleep(60)
            with task.input_path.open("rb") as stream:
                paths = pickle.load(stream)
            rows = []
            for path in paths:
                with path.open("rb") as stream:
                    rows.append(pickle.load(stream))
            result = {"rows": rows, "merge_pid": pid}
        with task.output_path.open("wb") as stream:
            pickle.dump(result, stream)
        events.put(("task_completed", task.index))


@pytest.fixture
def execution(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis_process, "parallel_worker_count", lambda *_: 2)
    monkeypatch.setattr(parallel_analysis, "_recording_worker", protocol_worker)
    original = parallel_analysis.tempfile.TemporaryDirectory
    monkeypatch.setattr(
        parallel_analysis.tempfile,
        "TemporaryDirectory",
        lambda **kwargs: original(dir=tmp_path, **kwargs),
    )
    handler = Messages()
    logger = logging.Logger("protocol", logging.INFO)
    logger.addHandler(handler)
    gate = multiprocessing.get_context("spawn").Barrier(2)
    frames = {name: pd.DataFrame({"time": [0.0, 1.0]}) for name in ("first", "second", "third")}
    return frames, {"gate": gate}, logger, handler


def wait_for(predicate):
    deadline = time.monotonic() + 20
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate(), "Recording workers did not reach the expected phase"


@pytest.mark.parametrize("recording_count", [3, 7])
def test_multiple_recordings_overlap_reuse_workers_and_collect_in_source_order(
    execution, tmp_path, recording_count
):
    frames, settings, logger, handler = execution
    frames.update(
        {
            f"extra_{index}": pd.DataFrame({"time": [0.0, 1.0]})
            for index in range(3, recording_count)
        }
    )
    before = {child.pid for child in multiprocessing.active_children()}
    result = analysis_process.run_isolated_analysis(frames, settings, logger, Event())
    assert [row["index"] for row in result["rows"]] == list(range(recording_count))
    assert [row["key"] for row in result["rows"]] == list(frames)
    pids = {row["pid"] for row in result["rows"]}
    assert len(pids) == 2 and result["merge_pid"] in pids
    assert next(message for message in handler.messages if message.startswith("Completed")) == (
        f"Completed recording 1/{recording_count}: second"
    )
    assert {child.pid for child in multiprocessing.active_children()} == before
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mode", ["processing", "aggregation"])
def test_stop_terminates_all_owned_workers_and_removes_batch_files(execution, tmp_path, mode):
    frames, settings, logger, handler = execution
    settings["mode"] = mode
    before = {child.pid for child in multiprocessing.active_children()}
    cancel = Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            analysis_process.run_isolated_analysis, frames, settings, logger, cancel
        )
        try:
            wait_for(
                lambda: (
                    sum(message.startswith("started:") for message in handler.messages) >= 2
                    if mode == "processing"
                    else any(message.startswith("merging:") for message in handler.messages)
                )
            )
            assert list(tmp_path.glob("paradigma-analysis-*"))
        finally:
            cancel.set()
        with pytest.raises(analysis_process.AnalysisCancelled):
            future.result(timeout=10)
    assert not list(tmp_path.iterdir())
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_failed_worker_stops_peers_and_cleans_private_files(execution, tmp_path):
    frames, settings, logger, _ = execution
    settings["mode"] = "failure"
    before = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(RuntimeError, match="controlled worker failure"):
        analysis_process.run_isolated_analysis(frames, settings, logger, Event())
    assert not list(tmp_path.iterdir())
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_abrupt_worker_exit_stops_peers_and_cleans_private_files(execution, tmp_path):
    frames, settings, logger, _ = execution
    settings["mode"] = "crash"
    before = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(RuntimeError, match="worker exited unexpectedly.*7"):
        analysis_process.run_isolated_analysis(frames, settings, logger, Event())
    assert not list(tmp_path.iterdir())
    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize("dictionary", [False, True])
def test_one_original_recording_with_multiple_sections_uses_one_process(
    synthetic_imu, monkeypatch, dictionary
):
    frame = synthetic_imu.iloc[:2000].copy()
    frame["data_segment_nr"] = np.repeat([1, 2], 1000)
    selected = {"only": frame} if dictionary else frame
    # Even an overly permissive resource selector cannot parallelize sections
    # of a single original recording.
    monkeypatch.setattr(analysis_process, "parallel_worker_count", lambda *_: 2)
    monkeypatch.setattr(
        parallel_analysis,
        "run_parallel_analysis",
        lambda *_: pytest.fail("A single recording entered the parallel path"),
    )
    result = analysis_process.run_isolated_analysis(
        selected,
        {"pipelines": ["tremor"], "skip_preparation": True},
        logging.Logger("single"),
        Event(),
    )
    assert not result["errors"]
    assert result["metadata"]["desktop_preparation"]["continuous_sections"] == 2


@pytest.mark.parametrize(
    "cpus,available,expected",
    [
        (1, 32, 1),
        (2, 32, 1),
        (4, 32, 2),
        (4, 2, 1),
        (4, 3, 2),
        (4, None, 1),
    ],
)
def test_worker_limit_reserves_cpu_and_ram(monkeypatch, cpus, available, expected):
    monkeypatch.setattr(analysis_limits, "_available_cpu_count", lambda: cpus)
    monkeypatch.setattr(
        analysis_limits,
        "available_memory",
        lambda: available * analysis_limits.GIB if available is not None else None,
    )
    frames = {"first": pd.DataFrame({"time": [0, 1]}), "second": pd.DataFrame({"time": [0, 1]})}
    assert analysis_limits.parallel_worker_count(frames, {}) == expected
    assert analysis_limits.parallel_worker_count({"only": frames["first"]}, {}) == 1
    assert analysis_limits.parallel_worker_count(frames["first"], {}) == 1


@pytest.mark.parametrize(
    "cpus,affinity,expected",
    [(8, {0}, 1), (8, {0, 1, 2}, 3), (2, {0, 1, 2}, 2)],
)
def test_available_cpu_count_respects_affinity(monkeypatch, tmp_path, cpus, affinity, expected):
    monkeypatch.setattr(analysis_limits.os, "cpu_count", lambda: cpus)
    monkeypatch.setattr(analysis_limits.os, "sched_getaffinity", lambda _: affinity, raising=False)
    # Isolate affinity from the host's Linux container quota as well as its CPUs.
    quota = tmp_path / "cpu.max"
    quota.write_text("max 100000", encoding="utf-8")
    monkeypatch.setattr(analysis_limits, "Path", lambda _: quota)
    assert analysis_limits._available_cpu_count() == expected


def test_large_recordings_keep_sequential_path_when_ram_cannot_fit_two_workers(monkeypatch):
    monkeypatch.setattr(analysis_limits, "_available_cpu_count", lambda: 8)
    monkeypatch.setattr(analysis_limits, "available_memory", lambda: 16 * analysis_limits.GIB)
    frame = pd.DataFrame({"time": [0, 1]})
    monkeypatch.setattr(frame, "memory_usage", lambda **_: pd.Series([analysis_limits.GIB]))
    frames = {"first": frame, "second": frame}
    assert analysis_limits.parallel_worker_count(frames, {}) == 1
    monkeypatch.setattr(analysis_limits, "available_memory", lambda: 32 * analysis_limits.GIB)
    assert analysis_limits.parallel_worker_count(frames, {}) == 2


@pytest.mark.parametrize(
    "configuration",
    [
        "imu_config",
        "ppg_config",
        "gait_config",
        "arm_activity_config",
        "tremor_config",
        "pulse_rate_config",
    ],
)
def test_mutable_scientific_configs_require_one_worker_even_with_resources_for_two(
    monkeypatch, configuration
):
    monkeypatch.setattr(analysis_limits, "_available_cpu_count", lambda: 8)
    monkeypatch.setattr(analysis_limits, "available_memory", lambda: 32 * analysis_limits.GIB)
    frame = pd.DataFrame({"time": [0, 1]})
    frames = {"first": frame, "second": frame.copy()}
    assert analysis_limits.parallel_worker_count(frames, {}) == 2
    assert analysis_limits.parallel_worker_count(frames, {configuration: object()}) == 1
    assert analysis_limits.parallel_worker_count(frames, {configuration: None}) == 2


@pytest.mark.parametrize(
    "cpus,available,largest,expected,reason",
    [
        (8, 32, 0.5, 2, "Two workers are available"),
        (8, 24, 0.5, 2, "Two workers are available"),
        (8, 13, 0.5, 2, "Two workers are available"),
        (8, 12, 0.5, 1, "RAM limit (two workers need at least 13.00 GiB available)"),
        (2, 24, 0.5, 1, "CPU limit"),
        (2, 12, 0.5, 1, "CPU limit"),
        (8, None, 0.5, 1, "available RAM could not be determined"),
    ],
)
def test_seven_recording_worker_decision_reports_measured_resources(
    monkeypatch, cpus, available, largest, expected, reason
):
    monkeypatch.setattr(analysis_limits, "_available_cpu_count", lambda: cpus)
    monkeypatch.setattr(
        analysis_limits,
        "available_memory",
        lambda: int(available * analysis_limits.GIB) if available is not None else None,
    )
    frame = pd.DataFrame({"time": [0.0]})
    monkeypatch.setattr(
        frame, "memory_usage", lambda **_: pd.Series([int(largest * analysis_limits.GIB)])
    )
    frames = {f"recording_{index:03d}": frame for index in range(1, 8)}
    handler = Messages()
    logger = logging.Logger("resources", logging.INFO)
    logger.addHandler(handler)
    assert analysis_limits.parallel_worker_count(frames, {}, logger) == expected
    assert len(handler.messages) == 1
    message = handler.messages[0]
    assert message.startswith(f"Worker selection: {expected} worker") and reason in message
    assert f"Available CPUs: {cpus}" in message
    if available is not None:
        assert f"available RAM: {available:.2f} GiB" in message
        assert "largest loaded recording: 0.50 GiB" in message
        assert "estimated RAM per worker: 6.00 GiB" in message
        assert "RAM reserve: 1.00 GiB" in message
    if cpus == 2 and available == 12:
        assert "RAM limit" in message


@pytest.mark.parametrize(
    "settings,reason",
    [
        ({"gait_config": object()}, "Custom mutable toolbox configurations"),
        ({"run_steps": ["classification"]}, "Restricted pipeline steps"),
    ],
)
def test_configuration_fallback_is_explained_without_probing_resources(
    monkeypatch, settings, reason
):
    monkeypatch.setattr(
        analysis_limits, "available_memory", lambda: pytest.fail("Unexpected memory probe")
    )
    handler = Messages()
    logger = logging.Logger("settings", logging.INFO)
    logger.addHandler(handler)
    frame = pd.DataFrame({"time": [0.0]})
    assert analysis_limits.parallel_worker_count({"a": frame, "b": frame}, settings, logger) == 1
    assert reason in handler.messages[0]


def test_forced_single_worker_reports_actual_batch_worker_count(monkeypatch, synthetic_imu):
    monkeypatch.setattr(analysis_limits, "_available_cpu_count", lambda: 8)
    monkeypatch.setattr(analysis_limits, "available_memory", lambda: 24 * analysis_limits.GIB)
    handler = Messages()
    logger = logging.Logger("single-worker-batch", logging.INFO)
    logger.addHandler(handler)
    frame = synthetic_imu.iloc[:2000].copy()
    result = analysis_process.run_isolated_analysis(
        {"a": frame, "b": frame.copy()},
        {"pipelines": ["tremor"], "skip_preparation": True},
        logger,
        Event(),
        max_workers=1,
    )
    assert not result["errors"]
    assert any(message.startswith("Worker selection: 2 workers.") for message in handler.messages)
    assert "Worker count capped at 1 by the caller." in handler.messages
    assert "Processing 2 recordings with 1 worker" in handler.messages


def test_windows_memory_query_checks_native_success(monkeypatch):
    import ctypes
    from types import SimpleNamespace

    def query(pointer):
        pointer._obj.available_physical = 8 * analysis_limits.GIB
        return 1

    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=query)),
        raising=False,
    )
    assert analysis_limits._windows_memory() == 8 * analysis_limits.GIB
    ctypes.windll.kernel32.GlobalMemoryStatusEx = lambda _: 0
    assert analysis_limits._windows_memory() is None


def test_linux_available_memory_respects_container_headroom(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis_limits.sys, "platform", "linux")
    monkeypatch.setattr(
        analysis_limits.os,
        "sysconf",
        lambda name: 4096 if name == "SC_PAGE_SIZE" else 8 * analysis_limits.GIB // 4096,
        raising=False,
    )
    (tmp_path / "memory.max").write_text(str(4 * analysis_limits.GIB))
    (tmp_path / "memory.current").write_text(str(analysis_limits.GIB))
    monkeypatch.setattr(analysis_limits, "Path", lambda _: tmp_path)
    assert analysis_limits.available_memory() == 3 * analysis_limits.GIB


def test_ambiguous_or_invalid_recording_identifiers_keep_original_validation(monkeypatch):
    monkeypatch.setattr(analysis_limits, "_available_cpu_count", lambda: 8)
    monkeypatch.setattr(analysis_limits, "available_memory", lambda: 32 * analysis_limits.GIB)
    frame = pd.DataFrame({"time": [0, 1]})
    assert analysis_limits.parallel_worker_count({"a": frame, "a__segment_1": frame}, {}) == 1
    assert analysis_limits.parallel_worker_count({"../source": frame, "other": frame}, {}) == 1
    assert analysis_limits.parallel_worker_count({"a": frame, "bad": None}, {}) == 1


@pytest.mark.parametrize("cap", [0, 3, True, 1.5])
def test_invalid_worker_cap_is_rejected_before_starting_processes(synthetic_imu, cap):
    with pytest.raises(ValueError, match="max_workers must be 1 or 2"):
        analysis_process.run_isolated_analysis(
            synthetic_imu, {}, logging.Logger("invalid"), Event(), max_workers=cap
        )
