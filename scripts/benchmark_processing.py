"""Measure loading, inspection, isolated pipelines and saved-run round trips.

Uses temporary synthetic files and the recorded scientific fixture. Timings exclude
fixture creation and correctness digests; scientific timings include spawned workers,
private transfers and aggregation. Run baseline and candidate sequentially with the
same interpreter, native thread limits, inputs and warm filesystem caches.
"""

import argparse
import hashlib
import json
import logging
import platform
import shutil
import statistics
import tempfile
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from threading import Event

import numpy as np
import pandas as pd

from paradigma_studio.analysis_limits import parallel_worker_count
from paradigma_studio.analysis_process import run_isolated_analysis
from paradigma_studio.core import load_sensor_file
from paradigma_studio.history import RunHistory, load_verified_result_export, new_run
from paradigma_studio.inspection import inspect_recording, inspect_recordings
from paradigma_studio.recordings import load_recordings
from paradigma_studio.serialization import json_value


def _digest(value):
    """Hash full values, schema and missingness outside the timed operation."""
    digest = hashlib.sha256()
    if isinstance(value, pd.DataFrame):
        digest.update(str(list(zip(value.columns, value.dtypes.astype(str), strict=True))).encode())
        digest.update(pd.util.hash_pandas_object(value, index=True).to_numpy().tobytes())
        digest.update(json.dumps(value.attrs, sort_keys=True).encode())
    else:
        digest.update(json.dumps(json_value(value), sort_keys=True, allow_nan=False).encode())
    return digest.hexdigest()


def _measure(measurements, name, operation, repeats, *, verify=_digest):
    samples, digests = [], []
    for _ in range(repeats):
        started = time.perf_counter()
        value = operation()
        samples.append(time.perf_counter() - started)
        digests.append(verify(value))
    if len(set(digests)) != 1:
        raise AssertionError(f"Values changed across repeats: {name}")
    measurements[name] = {
        "seconds": samples,
        "median_seconds": statistics.median(samples),
        "output_sha256": digests[0],
    }
    print(f"{name}: {statistics.median(samples):.4f} s", flush=True)
    return value


def _write_tsdf(directory, samples):
    channels = [f"{kind}_{axis}" for kind in ("accelerometer", "gyroscope") for axis in "xyz"]
    times = np.full(samples, 10, dtype="int16")
    times[0] = 0
    values = np.random.default_rng(20261016).integers(
        -30_000, 30_000, size=(samples, 6), dtype="int16"
    )
    start = datetime(2026, 10, 13, tzinfo=UTC)
    streams = []
    for name, array, columns, units, scales in (
        ("time", times, ["time"], ["difference_ms"], [1]),
        ("values", values, channels, ["g"] * 3 + ["deg/s"] * 3, [0.01] * 6),
    ):
        filename = f"IMU_{name}.bin"
        array.tofile(directory / filename)
        streams.append(
            {
                "metadata_version": "0.1",
                "study_id": "benchmark",
                "subject_id": "synthetic",
                "device_id": "synthetic",
                "start_iso8601": start.isoformat(),
                "end_iso8601": (start + timedelta(seconds=samples / 100)).isoformat(),
                "file_name": filename,
                "rows": samples,
                "channels": columns,
                "units": units,
                "scale_factors": scales,
                "data_type": "int",
                "bits": 16,
                "endianness": "little",
            }
        )
    path = directory / "IMU_meta.json"
    path.write_text(json.dumps({"metadata_version": "0.1", "datasets": streams}))
    return path


def _benchmark_loading(directory, measurements, repeats, samples, fixture, recordings=1):
    tsdf = _write_tsdf(directory, samples)
    paths = [tsdf, tsdf.with_name("IMU_time.bin"), tsdf.with_name("IMU_values.bin")]
    original = [_file_digest(path) for path in paths]
    # First-use imports are covered by the startup/UI probes, not this warm path.
    load_sensor_file(tsdf)
    frame = _measure(measurements, "LOAD TSDF", lambda: load_sensor_file(tsdf), repeats)
    _measure(
        measurements,
        "INSPECT TSDF",
        lambda frame=frame: inspect_recording(frame, "difference_ms"),
        repeats,
    )
    assert original == [_file_digest(path) for path in paths], "Source TSDF files changed"
    del frame
    if recordings > 1:
        _benchmark_batch_loading(directory, measurements, repeats, recordings, paths)
    recorded = pd.read_parquet(fixture)
    raw = pd.concat([recorded] * 4, ignore_index=True)
    for extension in ("csv", "parquet"):
        path = directory / f"sensor.{extension}"
        if extension == "csv":
            raw.to_csv(path, index=False)
        else:
            raw.to_parquet(path, index=False)
        _measure(
            measurements,
            f"LOAD {extension.upper()}",
            lambda path=path: load_sensor_file(path),
            repeats,
        )
    for filename in ("test_data.CWA", "test_data.avro"):
        path = Path(str(files("paradigma_studio") / "data" / filename))
        _measure(
            measurements,
            f"LOAD {path.suffix[1:].upper()}",
            lambda path=path: load_sensor_file(path),
            repeats,
        )
    return recorded


def _batch_digest(frames):
    digest = hashlib.sha256()
    for key, frame in frames.items():
        digest.update(key.encode())
        digest.update(_digest(frame).encode())
    return digest.hexdigest()


def _benchmark_batch_loading(directory, measurements, repeats, count, original_paths):
    paths = []
    for index in range(count):
        target = directory / f"recording-{index:03d}"
        target.mkdir()
        for path in original_paths:
            shutil.copyfile(path, target / path.name)
        paths.append(target / original_paths[0].name)
    source_digests = [_file_digest(path) for path in original_paths]
    _, frames = _measure(
        measurements,
        "LOAD TSDF BATCH",
        lambda: load_recordings(paths),
        repeats,
        verify=lambda payload: _batch_digest(payload[1]),
    )
    original = _batch_digest(frames)
    sequential = _measure(
        measurements,
        "INSPECT TSDF BATCH SEQUENTIAL",
        lambda frames=frames: {
            key: inspect_recording(frame, "difference_ms") for key, frame in frames.items()
        },
        repeats,
    )
    concurrent = _measure(
        measurements,
        "INSPECT TSDF BATCH",
        lambda frames=frames: inspect_recordings(frames, "difference_ms"),
        repeats,
    )
    assert _digest(sequential) == _digest(concurrent), "Batch statistics changed"
    assert _batch_digest(frames) == original, "Inspected raw samples changed"
    del frames

    def load_and_inspect():
        _, frames = load_recordings(paths)
        descriptions = inspect_recordings(frames, "difference_ms")
        return frames, descriptions

    _measure(
        measurements,
        "LOAD AND INSPECT TSDF BATCH",
        load_and_inspect,
        repeats,
        verify=lambda payload: _digest((_batch_digest(payload[0]), _digest(payload[1]))),
    )
    for path in paths:
        assert [
            _file_digest(path.parent / original.name) for original in original_paths
        ] == source_digests, "Source TSDF files changed"


def _file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _benchmark_analysis(recorded, measurements, repeats):
    duration = recorded.time.iloc[-1] + np.median(np.diff(recorded.time))
    frame = pd.concat(
        [recorded.assign(time=recorded.time + index * duration) for index in range(8)],
        ignore_index=True,
    )
    settings = {"pipelines": ["gait", "tremor"], "skip_preparation": True, "watch_side": "left"}
    logger = logging.Logger("processing-benchmark", logging.INFO)
    logger.addHandler(logging.NullHandler())
    frames = {"recording_001": frame, "recording_002": frame.copy()}
    original = {key: _digest(value) for key, value in frames.items()}
    if parallel_worker_count(frames, settings) != 2:
        raise RuntimeError("This comparison requires resources for two recording workers.")
    for count, selected in ((1, frame), (2, frames)):
        results = _measure(
            measurements,
            f"ANALYZE {count} RECORDINGS",
            lambda selected=selected: run_isolated_analysis(selected, settings, logger, Event()),
            repeats,
        )
        if results.get("errors"):
            raise AssertionError(results["errors"])
    assert original == {key: _digest(value) for key, value in frames.items()}
    return {"recording_rows": len(frame), "seconds_per_recording": float(duration * 8)}


def _benchmark_saving(directory, measurements, repeats):
    rows = 300_000
    frame = pd.DataFrame(
        {
            "time": np.arange(rows, dtype=float) * 4,
            "file_key": ["recording_001"] * rows,
            "tremor_power": np.arange(rows) % 15 / 10,
            "pred_tremor_checked": np.arange(rows) % 2,
            "pred_arm_at_rest": np.ones(rows),
        }
    )
    results = {"quantifications": {"tremor": frame}, "classifications": {"tremor": frame}}
    history = RunHistory(directory / "runs")
    record = new_run("synthetic.csv", {"pipelines": ["tremor"]})
    record["status"] = "Completed"
    provenance = {
        "run_id": record["id"],
        "source": "synthetic.csv",
        "settings": {"pipelines": ["tremor"]},
    }
    outputs = _measure(
        measurements,
        "SAVE RUN 600000 ROWS",
        lambda: history.save_results(record, results, provenance),
        repeats,
        verify=lambda outputs: _file_digest(Path(outputs[0]["path"])),
    )
    path = Path(outputs[0]["path"])
    reopened = _measure(
        measurements,
        "REOPEN RUN 600000 ROWS",
        lambda: load_verified_result_export(path, record["id"], outputs[0]["sha256"]),
        repeats,
    )
    assert _digest(reopened) == _digest((provenance, results)), "Saved values changed"
    return {"saved_rows": rows * 2, "saved_bytes": path.stat().st_size}


def benchmark(
    report_path: Path,
    fixture: Path,
    repeats: int = 3,
    samples: int = 8_640_000,
    *,
    recordings: int = 1,
    loading_only: bool = False,
) -> None:
    if repeats < 1 or samples < 1 or recordings < 1:
        raise ValueError("repeats, samples and recordings must be positive")
    measurements = {}
    analysis, saving = {}, {}
    with tempfile.TemporaryDirectory(prefix="paradigma-processing-benchmark-") as temporary:
        directory = Path(temporary)
        recorded = _benchmark_loading(
            directory, measurements, repeats, samples, fixture, recordings
        )
        if not loading_only:
            analysis = _benchmark_analysis(recorded, measurements, repeats)
            saving = _benchmark_saving(directory, measurements, repeats)
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "versions": {name: version(name) for name in ("paradigma", "numpy", "pandas", "pyarrow")},
        "conditions": "Warm imports/file caches; temporary synthetic inputs and recorded IMU fixture. Timings include process startup and complete file writes/reads, exclude fixture construction and SHA-256 checks. Native thread limits must be identical for baseline and candidate.",
        "tsdf_samples": samples,
        "tsdf_recordings": recordings,
        "loading_only": loading_only,
        "tsdf_random_seed": 20261016,
        "fixture_sha256": _file_digest(fixture),
        **analysis,
        **saving,
        "measurements": measurements,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--samples", type=int, default=8_640_000)
    parser.add_argument("--recordings", type=int, default=1)
    parser.add_argument("--loading-only", action="store_true")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests/data/paradigma/prepared_imu.parquet",
    )
    args = parser.parse_args()
    benchmark(
        args.report,
        args.fixture,
        args.repeats,
        args.samples,
        recordings=args.recordings,
        loading_only=args.loading_only,
    )
