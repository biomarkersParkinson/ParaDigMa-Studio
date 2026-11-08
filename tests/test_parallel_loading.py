"""Real bounded readers: exact frames, deterministic batches and owned cleanup."""

import hashlib
import logging
import multiprocessing
import os
import pickle
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from importlib.resources import files
from pathlib import Path
from threading import Event, Lock, enumerate as threads

import pandas as pd
import pytest
from conftest import wait_for_job, wait_for_previews
from gui_helpers import wait_until
from PySide6.QtCore import QTimer

from paradigma_studio import recording_loading, recordings
from paradigma_studio.core import load_sensor_file
from paradigma_studio.loading_timing import LoadTiming
from paradigma_studio.recording_loading import loading_plan
from paradigma_studio.recordings import load_recordings


@pytest.fixture
def resources(monkeypatch):
    monkeypatch.setattr(recording_loading, "available_memory", lambda: 100 * 1024**3)
    monkeypatch.setattr(recording_loading, "_available_cpu_count", lambda: 8)


@pytest.mark.parametrize(
    "suffix,count,decode,size,expected",
    [
        ("avro", 12, 0.8, 5_000_000, "processes"),
        ("avro", 3, 0.8, 5_000_000, "sequential"),
        ("avro", 12, 0.001, 1000, "sequential"),
        ("csv", 12, 0.2, 5_000_000, "threads"),
        ("json", 12, 0.02, 5_000_000, "sequential"),
        ("json", 12, 0.08, 5_000_000, "threads"),
        ("parquet", 12, 0.01, 5_000_000, "threads"),
        ("CWA", 12, 0.03, 5_000_000, "sequential"),
        ("CWA", 12, 0.1, 5_000_000, "threads"),
        ("csv", 12, 0.001, 1000, "sequential"),
        ("pkl", 12, 0.01, 5_000_000, "sequential"),
        ("pickle", 12, 0.01, 5_000_000, "sequential"),
    ],
)
def test_auto_policy_uses_amortized_format_work(resources, suffix, count, decode, size, expected):
    plan = loading_plan([f"{index}.{suffix}" for index in range(count)], size, decode)
    assert plan.mode == expected
    assert plan.workers == (1 if expected == "sequential" else 2)


@pytest.mark.parametrize("available", [None, 0, 1024**3, 3 * 1024**3])
def test_low_or_unknown_memory_reserves_the_remaining_batch(resources, monkeypatch, available):
    monkeypatch.setattr(recording_loading, "available_memory", lambda: available)
    assert loading_plan(["a.avro"] * 336, 10_000_000, 1.0).workers == 1


def test_cpu_small_batch_mixed_work_and_explicit_caps(resources, monkeypatch):
    assert loading_plan(["a.csv"], 5_000_000, 1.0).workers == 1
    assert loading_plan(["a.avro", "b.csv"], 5_000_000, 1.0).workers == 1
    assert loading_plan(["a.avro"] * 12, 5_000_000, 1.0, sample_suffix=".csv").workers == 1
    assert loading_plan(["a.avro"] * 12, 5_000_000, 1.0, max_workers=1).workers == 1
    monkeypatch.setattr(recording_loading, "_available_cpu_count", lambda: 2)
    assert loading_plan(["a.avro"] * 12, 5_000_000, 1.0).workers == 1


@pytest.mark.parametrize(
    "options", [{"mode": "bad"}, {"max_workers": 0}, {"max_workers": True}, {"max_workers": 2.0}]
)
def test_invalid_options_are_rejected_before_reading(monkeypatch, options):
    monkeypatch.setattr(
        recordings, "load_sensor_file", lambda *_args, **_kwargs: pytest.fail("Opened a source")
    )
    with pytest.raises(ValueError):
        load_recordings(["source.csv"], **options)


def test_threads_overlap_with_bounded_dispatch_and_publish_in_input_order(resources, monkeypatch):
    paths = [Path(f"{index}.csv") for index in range(6)]
    first_held, later_held, release = Event(), Event(), Event()
    guard = Lock()
    observed, active, peak = [], 0, 0
    progress = []

    def read(path, *, allow_pickle=False):
        nonlocal active, peak
        index = paths.index(Path(path))
        with guard:
            observed.append(index)
            active += 1
            peak = max(peak, active)
        try:
            if index == 1:
                first_held.set()
                assert release.wait(10)
            if index == 3:
                later_held.set()
                assert release.wait(10)
            return pd.DataFrame({"time": [0.0, 1.0], "value": [index, index + 1]})
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(recordings, "load_sensor_file", read)
    with ThreadPoolExecutor(max_workers=1) as caller:
        future = caller.submit(
            load_recordings, [*paths, paths[0]], mode="threads", progress=progress.append
        )
        try:
            assert first_held.wait(5) and later_held.wait(5)
            assert not future.done()
            assert 0 < progress[-1] < 1000
            assert set(observed) == {0, 1, 2, 3}
        finally:
            release.set()
        sources, frames = future.result(timeout=10)
    assert peak == 2 and len(observed) == len(paths)
    assert list(sources.values()) == list(map(str, paths))
    assert list(frames) == list(sources)
    assert [frame.value.iloc[0] for frame in frames.values()] == list(range(6))
    assert progress == sorted(set(progress)) and progress[-1] == 1000
    assert not any(thread.name.startswith("paradigma-load") for thread in threads())


def _copy_recording(source, directory):
    directory.mkdir()
    for path in [source, *source.parent.glob("*.bin")] if source.suffix == ".json" else [source]:
        shutil.copyfile(path, directory / path.name)
    return directory / source.name


@pytest.mark.parametrize("mode", ["threads", "processes"])
@pytest.mark.parametrize("format", ["csv", "parquet", "pickle", "tsdf", "cwa", "avro"])
def test_real_readers_keep_exact_values_metadata_and_source_bytes(
    tmp_path, resources, tsdf_writer, format, mode, caplog
):
    frame = pd.DataFrame({"time": [0, 10, 20], "gyroscope_x": [1, -2, 300]}).astype("int16")
    if format == "tsdf":
        source = tsdf_writer(frame, scale_factors=[0.02], dtype="int16")
    elif format in {"cwa", "avro"}:
        source = Path(
            str(
                files("paradigma_studio")
                / "data"
                / ("test_data.CWA" if format == "cwa" else "test_data.avro")
            )
        )
    else:
        source = tmp_path / f"source.{format}"
        if format == "csv":
            frame.to_csv(source, index=False)
        elif format == "parquet":
            frame.attrs["test_metadata"] = {"units": "rad/s", "offsets": [1.0, 2.0]}
            frame.to_parquet(source)
        else:
            frame["clock"] = pd.date_range("2026-10-25", periods=3, tz="Europe/Amsterdam")
            frame.attrs["test_metadata"] = {"units": "rad/s", "offsets": [1.0, 2.0]}
            frame.to_pickle(source)
    paths = [_copy_recording(source, tmp_path / f"copy-{i}") for i in range(3)]
    protected = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for parent in paths
        for path in parent.parent.iterdir()
    }
    expected = load_sensor_file(paths[0], allow_pickle=True)
    before = {child.pid for child in multiprocessing.active_children()}
    progress = []
    logger = logging.getLogger("loading-equivalence")
    with caplog.at_level(logging.INFO, logger=logger.name):
        sources, frames = load_recordings(
            paths, allow_pickle=True, mode=mode, progress=progress.append, logger=logger
        )
    timed = [
        record.args
        for record in caplog.records
        if record.getMessage().startswith("Loaded recording_")
    ]
    assert len(timed) == 3 and all(values[2] > 0 for values in timed)
    if format in {"tsdf", "avro"}:
        assert all(values[3] > 0 for values in timed)
    assert list(sources.values()) == list(map(str, paths))
    for actual in frames.values():
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        assert actual.attrs == expected.attrs
    assert protected == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    assert progress == sorted(set(progress)) and progress[-1] == 1000
    assert {child.pid for child in multiprocessing.active_children()} == before


def _warn_record():
    logging.getLogger("paradigma").warning("Controlled reader warning")
    return pd.DataFrame({"time": [0.0], "value": [42.0]})


def _crash_record():
    os._exit(7)


class _TrustedRecord:
    def __init__(self, operation):
        self.operation = operation

    def __reduce__(self):
        return self.operation, ()


@pytest.mark.parametrize("failure", ["invalid", "crash"])
def test_process_failures_keep_source_context_tracebacks_and_release_all_children(
    resources, tmp_path, caplog, failure
):
    frame = pd.DataFrame({"time": [0.0], "value": [1.0]})
    first = tmp_path / "first.csv"
    frame.to_csv(first, index=False)
    warning = tmp_path / "warning.pkl"
    warning.write_bytes(pickle.dumps(_TrustedRecord(_warn_record)))
    bad = tmp_path / ("bad.csv" if failure == "invalid" else "crash.pkl")
    if failure == "invalid":
        bad.write_bytes(b"")
    else:
        bad.write_bytes(pickle.dumps(_TrustedRecord(_crash_record)))
    logger = logging.getLogger("loading-test")
    before = {child.pid for child in multiprocessing.active_children()}
    changes = []
    with (
        caplog.at_level(logging.INFO, logger=logger.name),
        pytest.raises((ValueError, RuntimeError), match=bad.name),
    ):
        load_recordings(
            [first, bad, warning],
            allow_pickle=True,
            mode="processes",
            logger=logger,
            progress=changes.append,
        )
    assert 1000 not in changes
    assert {child.pid for child in multiprocessing.active_children()} == before
    assert "completed" in caplog.text and "Recording read/convert wall time" in caplog.text
    if failure == "invalid":
        assert "Traceback" in caplog.text and "EmptyDataError" in caplog.text


def test_process_logs_and_native_timing_fields_return_to_the_parent(resources, tmp_path, caplog):
    first = tmp_path / "first.csv"
    pd.DataFrame({"time": [0.0]}).to_csv(first, index=False)
    paths = [first]
    for index in range(2):
        path = tmp_path / f"warning-{index}.pkl"
        path.write_bytes(pickle.dumps(_TrustedRecord(_warn_record)))
        paths.append(path)
    logger = logging.getLogger("loading-test")
    with caplog.at_level(logging.INFO, logger=logger.name):
        load_recordings(paths, allow_pickle=True, mode="processes", logger=logger)
    warnings = [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert sorted(warnings) == [
        "Controlled reader warning [recording_002]",
        "Controlled reader warning [recording_003]",
    ]
    assert "startup/transfer/cleanup included" in caplog.text and "worker-s" in caplog.text


def _gated_reader(connection, entered, release):
    try:
        while (command := connection.recv()) is not None:
            index, path, _ = command
            entered.set()
            assert release.wait(15)
            connection.send(("loaded", index, pd.read_csv(path), LoadTiming(0.01, 0.0, 0.01)))
    finally:
        connection.close()


def test_gui_stays_responsive_and_installs_only_the_complete_batch(
    window, resources, tmp_path, recording_picker, monkeypatch
):
    previous = pd.DataFrame({"time": [0.0], "value": [99.0]})
    window.loaded(("previous.csv", previous))
    wait_for_previews(window)
    paths = [tmp_path / f"input-{index}.csv" for index in range(3)]
    for path in paths:
        pd.DataFrame({"time": [0.0, 1.0], "gyroscope_x": [1.0, 2.0]}).to_csv(path, index=False)
    context = multiprocessing.get_context("spawn")
    entered, release = context.Event(), context.Event()
    monkeypatch.setattr(
        recording_loading, "_load_worker", partial(_gated_reader, entered=entered, release=release)
    )
    controller = window._data_controller
    controller.services = replace(
        controller.services, load_recordings=partial(load_recordings, mode="processes")
    )
    beats = []
    timer = QTimer(window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: beats.append(True))
    timer.start()
    recording_picker(paths)
    before = {child.pid for child in multiprocessing.active_children()}
    window.open_file()
    try:
        wait_until(entered.is_set, timeout=10000)
        wait_until(lambda: len(beats) >= 3 and window.progress.value() > 0)
        assert window._input_state.frame is previous
        assert not window.progress.isTextVisible() and window.progress.height() == 4
    finally:
        release.set()
        wait_for_job(window)
        timer.stop()
    assert len(window._input_state.recordings) == 3
    assert len(window._data_state._input_descriptions) == 3
    record = window._run_state.runs[0]
    assert record["status"] == "Loaded"
    assert (
        "Initial statistics wall time" in record["log"]
        and "Recording discovery wall time" in record["log"]
    )
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_failed_process_start_closes_pipes_and_already_started_readers(
    resources, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    path = tmp_path / "input.csv"
    pd.DataFrame({"time": [0.0]}).to_csv(path, index=False)
    context = multiprocessing.get_context("spawn")
    created, connections = [], []
    before = {child.pid for child in multiprocessing.active_children()}

    def pipe():
        pair = context.Pipe()
        connections.extend(pair)
        return pair

    def process(**kwargs):
        child = context.Process(**kwargs)
        created.append(child)
        if len(created) == 2:

            def fail():
                raise OSError("Controlled process-start failure")

            child.start = fail
        return child

    monkeypatch.setattr(
        recording_loading.multiprocessing,
        "get_context",
        lambda _method: SimpleNamespace(Pipe=pipe, Process=process),
    )
    with pytest.raises(OSError, match="process-start failure"):
        load_recordings([path, tmp_path / "b.csv", tmp_path / "c.csv"], mode="processes")
    assert all(connection.closed for connection in connections)
    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize("mode", ["auto", "threads", "processes"])
def test_pickle_permission_is_checked_for_the_complete_batch_before_any_read(monkeypatch, mode):
    monkeypatch.setattr(
        recordings, "load_sensor_file", lambda *_args, **_kwargs: pytest.fail("Opened a source")
    )
    with pytest.raises(ValueError, match="untrusted.pkl.*explicitly trusted"):
        load_recordings(["valid.csv", "untrusted.pkl"], mode=mode)


def test_native_thread_diagnostics_keep_file_context_and_leave_unrelated_logs_untagged(
    resources, monkeypatch
):
    from types import SimpleNamespace

    from paradigma_studio.jobs import SignalHandler
    from paradigma_studio.loading_timing import loading_recording

    messages, warnings = [], []
    handler = SignalHandler(
        SimpleNamespace(emit=messages.append), SimpleNamespace(emit=warnings.append)
    )
    package_logger = logging.getLogger("paradigma")
    package_logger.addHandler(handler)
    previous_level = package_logger.level
    package_logger.setLevel(logging.INFO)

    def read(path, *, allow_pickle=False):
        if Path(path).stem != "first":
            package_logger.warning("Same reader warning")
        return pd.DataFrame({"time": [0.0]})

    monkeypatch.setattr(recordings, "load_sensor_file", read)
    try:
        load_recordings(["first.csv", "second.csv", "third.csv"], mode="threads")
        package_logger.warning("Outside loading")
    finally:
        package_logger.removeHandler(handler)
        package_logger.setLevel(previous_level)
        handler.close()
    assert sorted(warnings) == [
        "Outside loading",
        "Same reader warning [recording_002]",
        "Same reader warning [recording_003]",
    ]
    assert loading_recording() == ""


@pytest.mark.parametrize("bad_first", [False, True])
def test_failed_parallel_gui_import_keeps_the_previous_input_and_owned_diagnostics(
    window, resources, tmp_path, recording_picker, bad_first
):
    previous = pd.DataFrame({"time": [0.0], "value": [42.0]})
    window.loaded(("previous.csv", previous))
    wait_for_previews(window)
    good, third = tmp_path / "a-good.csv", tmp_path / "c-third.csv"
    for path in (good, third):
        pd.DataFrame({"time": [0.0, 1.0]}).to_csv(path, index=False)
    bad = tmp_path / ("0-bad.csv" if bad_first else "b-bad.csv")
    bad.write_bytes(b"")
    controller = window._data_controller
    controller.services = replace(
        controller.services, load_recordings=partial(load_recordings, mode="processes")
    )
    recording_picker([good, bad, third])
    window.open_file()
    wait_for_job(window)
    record = window._run_state.runs[0]
    assert window._input_state.frame is previous
    assert record["status"] == "Failed" and len(record["errors"]) == 1
    assert "bad.csv" in record["errors"][0]
    assert "Traceback" in record["log"] and "Recording read/convert wall time" in record["log"]


def _error_record():
    logging.getLogger("paradigma").error("Independent reader error with usable samples")
    return pd.DataFrame({"time": [0.0], "value": [42.0]})


@pytest.mark.parametrize("mode", ["threads", "processes"])
def test_successful_reads_retain_independent_error_reports(resources, tmp_path, mode):
    from types import SimpleNamespace

    from paradigma_studio.jobs import SignalHandler

    errors = []
    handler = SignalHandler(
        SimpleNamespace(emit=lambda _message: None), error=SimpleNamespace(emit=errors.append)
    )
    logger = logging.getLogger("paradigma")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    first = tmp_path / "first.csv"
    pd.DataFrame({"time": [0.0]}).to_csv(first, index=False)
    paths = [first]
    for index in range(2):
        path = tmp_path / f"error-{index}.pkl"
        path.write_bytes(pickle.dumps(_TrustedRecord(_error_record)))
        paths.append(path)
    try:
        _, frames = load_recordings(paths, allow_pickle=True, mode=mode, logger=logger)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.close()
    assert len(frames) == 3
    assert sorted(errors) == [
        "Independent reader error with usable samples [recording_002]",
        "Independent reader error with usable samples [recording_003]",
    ]


def _identified_reader(connection, release):
    try:
        while (command := connection.recv()) is not None:
            index, path, _ = command
            if index == 1:
                assert release.wait(15)
            elif index == 2:
                release.set()
            frame = pd.read_csv(path)
            frame["reader_pid"] = os.getpid()
            connection.send(("loaded", index, frame, LoadTiming(0.01, 0.0, 0.01)))
    finally:
        connection.close()


def test_processes_reuse_two_readers_without_reordering_distinct_inputs(
    resources, tmp_path, monkeypatch
):
    paths = [tmp_path / f"{index}.csv" for index in range(9)]
    for index, path in enumerate(paths):
        pd.DataFrame({"time": [0.0], "value": [index]}).to_csv(path, index=False)
    gate = multiprocessing.get_context("spawn").Event()
    monkeypatch.setattr(
        recording_loading, "_load_worker", partial(_identified_reader, release=gate)
    )
    before = {child.pid for child in multiprocessing.active_children()}
    sources, frames = load_recordings(paths, mode="processes")
    assert list(sources.values()) == list(map(str, paths))
    assert [frame.value.iloc[0] for frame in frames.values()] == list(range(9))
    child_frames = list(frames.values())[1:]
    assert len({int(frame.reader_pid.iloc[0]) for frame in child_frames}) == 2
    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize("frozen,expected", [(False, "sequential"), (True, "processes")])
def test_auto_avro_preserves_interactive_callers_and_recognizes_frozen_entrypoints(
    resources, monkeypatch, frozen, expected
):
    import sys

    monkeypatch.delattr(sys.modules["__main__"], "__file__", raising=False)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    assert loading_plan(["input.avro"] * 12, 5_000_000, 1.0).mode == expected
