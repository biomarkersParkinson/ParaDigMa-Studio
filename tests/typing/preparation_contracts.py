"""Static regressions, checked by mypy but never executed as pipeline tests.

Each ignore must suppress a real error (warn_unused_ignores is enabled), so
loosening an adapter/settings signature back to Any fails the regular check.
"""

import pandas as pd

from paradigma_studio.core import analyze
from paradigma_studio.paradigma_api import (
    correct_watch_orientation,
    prepare_raw_data,
    run_paradigma,
)
from paradigma_studio.preparation_contracts import PreparationSettings


def preparation_contract(frame: pd.DataFrame) -> None:
    selected: PreparationSettings = {
        "accelerometer_units": "m/s^2",
        "gyroscope_units": "rad/s",
        "time_input_unit": "difference_ms",
        "device_orientation": ["x", "y", "z"],
        "axis_inversions": ["gyroscope_x"],
        "signal_columns": {
            "time": "clock",
            "green": "my_ppg",
            "accelerometer_x": None,
            "accelerometer_y": None,
            "accelerometer_z": None,
            "gyroscope_x": None,
            "gyroscope_y": None,
            "gyroscope_z": None,
        },
    }
    analyze(frame, pipelines="pulse_rate", **selected)
    prepare_raw_data(frame, accelerometer_units="g", time_input_unit="absolute_ms")
    correct_watch_orientation(frame, ["-x", "y", "z"], sensor="gyroscope")
    run_paradigma(dfs=frame, pipelines=["tremor"], return_intermediate=["classification"])

    selected["accelerometer_units"] = "rad/s"  # type: ignore[typeddict-item]
    selected["gyroscope_units"] = "g"  # type: ignore[typeddict-item]
    selected["time_input_unit"] = "seconds"  # type: ignore[typeddict-item]
    selected["axis_inversions"] = ["green"]  # type: ignore[list-item]
    selected["signal_columns"] = {"ppg": "green"}  # type: ignore[dict-item]
    selected["split_by_gap"] = True  # type: ignore[typeddict-unknown-key]
    analyze(frame, pipelines="pulse_rate", time_input_unit="s")  # type: ignore[arg-type]
    analyze(frame, pipelines="tremor", axis_inversions=["gyroscope_w"])  # type: ignore[list-item]
    analyze(frame, pipelines="gait", watch_side="up")  # type: ignore[arg-type]
    prepare_raw_data(frame, accelerometer_units="rad/s")  # type: ignore[arg-type]
    correct_watch_orientation(frame, ["x", "y", "w"])  # type: ignore[list-item]
    correct_watch_orientation(frame, sensor="green")  # type: ignore[arg-type]
    run_paradigma(dfs=frame, watchside="left")  # type: ignore[call-arg]
    run_paradigma(dfs=frame, run_steps=["features"])  # type: ignore[list-item]
    run_paradigma(dfs=frame, pipelines=["balance"])  # type: ignore[list-item]
