"""Compare exact batch readers, including spawned startup/transfers and sampled RSS.

Use generated format fixtures or --paths for real recordings. Run modes sequentially;
correctness/source hashes and fixture generation remain outside each timed operation.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import logging
import os
import platform
import shutil
import statistics
import tempfile
import time
from functools import lru_cache
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from threading import Event, Lock, Thread

from benchmark_processing import _digest, _write_tsdf

from paradigma_studio.analysis_limits import _available_cpu_count, available_memory
from paradigma_studio.core import load_sensor_file
from paradigma_studio.recordings import find_recording_files, load_recordings
from paradigma_studio.storage import recording_files


@lru_cache(maxsize=1)
def _windows_rss_api():
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("faults", wintypes.DWORD),
            *[
                (name, ctypes.c_size_t)
                for name in (
                    "peak",
                    "working",
                    "peak_paged",
                    "paged",
                    "peak_nonpaged",
                    "nonpaged",
                    "pagefile",
                    "peak_pagefile",
                )
            ],
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    return kernel, psapi, Counters


def _rss(pid):
    if os.name == "nt":
        kernel, psapi, shape = _windows_rss_api()
        handle = kernel.OpenProcess(0x410, False, pid)
        if not handle:
            return None
        try:
            counters = shape()
            counters.size = ctypes.sizeof(counters)
            return (
                int(counters.working)
                if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.size)
                else None
            )
        finally:
            kernel.CloseHandle(handle)
    try:
        fields = (Path("/proc") / str(pid) / "status").read_text().splitlines()
        return next(int(line.split()[1]) * 1024 for line in fields if line.startswith("VmRSS:"))
    except (OSError, StopIteration):
        return None


class _MemoryProbe(logging.Handler):
    def __init__(self):
        super().__init__()
        self.pids = {os.getpid()}
        self.guard = Lock()
        self.stop = Event()
        self.peak = None
        self.strategies = []
        self.thread = Thread(target=self._watch, name="loading-memory-probe", daemon=True)

    def emit(self, record):
        with self.guard:
            self.pids.update(
                pid for pid in getattr(record, "loading_worker_pids", ()) if pid is not None
            )
        if record.getMessage().startswith("Loading strategy:"):
            self.strategies.append(record.getMessage())

    def _watch(self):
        while not self.stop.is_set():
            self.sample()
            self.stop.wait(0.05)

    def sample(self):
        with self.guard:
            pids = tuple(self.pids)
        observed = [value for pid in pids if (value := _rss(pid)) is not None]
        if observed:
            self.peak = max(self.peak or 0, sum(observed))


def _source_hash(paths):
    result = {}
    for path in recording_files(paths):
        if path.is_file():
            with path.open("rb") as stream:
                result[str(path)] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def _batch_hash(payload):
    sources, frames = payload
    return {
        key: {"source": sources[key], "frame_sha256": _digest(frame)}
        for key, frame in frames.items()
    }


def _measure(paths, mode, allow_pickle):
    probe = _MemoryProbe()
    logger = logging.Logger("loading-benchmark", logging.DEBUG)
    logger.addHandler(probe)
    probe.sample()
    probe.thread.start()
    started = time.perf_counter()
    try:
        payload = load_recordings(paths, allow_pickle=allow_pickle, logger=logger, mode=mode)
        elapsed = time.perf_counter() - started
    finally:
        probe.stop.set()
        probe.thread.join(timeout=5)
        probe.sample()
        logger.removeHandler(probe)
        probe.close()
    # Avoid holding a baseline batch alongside the next full candidate batch.
    return elapsed, _batch_hash(payload), probe.peak, probe.strategies


def _fixtures(root, count, samples, selected):
    root.mkdir()
    tsdf = _write_tsdf(root, samples)
    frame = load_sensor_file(tsdf)
    frame.to_csv(root / "sensor.csv", index=False)
    frame.to_parquet(root / "sensor.parquet", index=False)
    frame.to_pickle(root / "sensor.pickle")
    inputs = {
        "csv": root / "sensor.csv",
        "parquet": root / "sensor.parquet",
        "pickle": root / "sensor.pickle",
        "tsdf": tsdf,
        "cwa": Path(str(files("paradigma_studio") / "data" / "test_data.CWA")),
        "avro": Path(str(files("paradigma_studio") / "data" / "test_data.avro")),
    }
    batches = {}
    for name, source in inputs.items():
        if selected not in ("all", name):
            continue
        paths = []
        for index in range(count):
            folder = root / name / str(index)
            folder.mkdir(parents=True)
            for path in recording_files([source]):
                if path.is_file():
                    shutil.copyfile(path, folder / path.name)
            paths.append(folder / source.name)
        batches[name] = paths
    return batches


def benchmark(args):
    if min(args.recordings, args.samples, args.repeats) < 1:
        raise ValueError("recordings, samples and repeats must be positive")
    if "sequential" not in args.modes:
        raise ValueError("Include sequential mode as the correctness/performance baseline.")
    modes = ["sequential", *(mode for mode in dict.fromkeys(args.modes) if mode != "sequential")]
    with tempfile.TemporaryDirectory(prefix="paradigma-loading-benchmark-") as temporary:
        if args.paths:
            batches = {"selected": find_recording_files(args.paths)}
        else:
            batches = _fixtures(
                Path(temporary) / "fixtures", args.recordings, args.samples, args.format
            )
        results = {}
        for name, paths in batches.items():
            # Generated pickle fixtures are owned by this benchmark. Selected
            # user pickle files still require explicit --allow-pickle consent.
            trusted = args.allow_pickle or not args.paths
            source_hash = _source_hash(paths)
            load_sensor_file(paths[0], allow_pickle=trusted)
            reference = None
            result = {}
            for mode in modes:
                times, peaks, strategies = [], [], []
                for _ in range(args.repeats):
                    elapsed, digest, peak, strategy = _measure(paths, mode, trusted)
                    reference = digest if reference is None else reference
                    assert reference == digest, f"Frames/metadata/order changed: {name}, {mode}"
                    times.append(elapsed)
                    peaks.append(peak)
                    strategies.append(strategy)
                result[mode] = {
                    "seconds": times,
                    "median_seconds": statistics.median(times),
                    "sampled_peak_combined_rss_bytes": peaks,
                    "strategy_logs": strategies,
                }
                print(f"{name} / {mode}: {statistics.median(times):.3f} s", flush=True)
            assert _source_hash(paths) == source_hash, "Source files changed"
            results[name] = {
                "recordings": len(paths),
                "output_hashes": reference,
                "source_hashes": source_hash,
                "modes": result,
            }
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "versions": {
            name: version(name) for name in ("paradigma", "numpy", "pandas", "avro", "pyarrow")
        },
        "available_cpus": _available_cpu_count(),
        "available_memory_after_probe": available_memory(),
        "conditions": "Warm parent imports/file caches. Spawn startup, table transfers and worker shutdown included. Exact data/schema/attrs/source checks outside timers. RSS sampled every 50 ms for parent and owned readers on Linux/Windows; summed RSS counts shared pages per process. Explicit modes retain RAM guards; inspect strategy_logs for fallbacks. AVRO/CWA use bundled recorded examples; --samples applies to generated table/TSDF formats.",
        "batches": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--recordings", type=int, default=12)
    parser.add_argument("--samples", type=int, default=180_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--format",
        choices=("all", "avro", "csv", "parquet", "tsdf", "cwa", "pickle"),
        default="all",
    )
    parser.add_argument("--paths", nargs="+", type=Path)
    parser.add_argument("--allow-pickle", action="store_true")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("sequential", "threads", "processes", "auto"),
        default=["sequential", "threads", "processes", "auto"],
    )
    benchmark(parser.parse_args())
