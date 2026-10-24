"""Current saved-run fixtures shared by persistence and desktop tests."""

import hashlib
from pathlib import Path

from paradigma_studio.column_mapping import SIGNALS
from paradigma_studio.history import new_run, now


def saved_settings(**overrides):
    return {
        "pipelines": ["tremor"],
        "watch_side": "left",
        "accelerometer_units": "g",
        "gyroscope_units": "deg/s",
        "time_input_unit": "relative_s",
        "device_orientation": ["x", "y", "z"],
        "axis_inversions": [],
        "signal_columns": {signal: signal for signal in SIGNALS},
        "column_mapping": {},
        "split_by_gaps": True,
        "max_gap_seconds": 1.5,
        "min_segment_seconds": 1.5,
        "drop_missing_samples": True,
        "plot_time_origin": {"mode": "automatic"},
        **overrides,
    }


def make_run(source="sensor.csv", settings=None):
    return new_run(source, saved_settings(**(settings or {})))


def export_receipt(path, kind="JSON"):
    receipt = {"kind": kind, "path": str(path), "saved": now(), "complete": False}
    if kind == "JSON":
        receipt["sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return receipt
