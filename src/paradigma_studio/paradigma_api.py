"""Typed, lazy adapters for ParaDigMa 1.1.2; never transform scientific data.

The upstream package has incomplete/stale annotations (notably TimeUnit,
orientation and sampling frequency). The boundary casts describe the inspected
pinned implementation; independent scientific tests check its actual outputs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Unpack, cast

from .contracts import AnalysisResults, PathInput, SegmentArray
from .preparation_contracts import (
    AccelerationUnit,
    GyroscopeUnit,
    OfficialRunOptions,
    Sensor,
    SignedAxis,
    TimeInputUnit,
)

if TYPE_CHECKING:
    from datetime import datetime

    import numpy as np
    import pandas as pd
    from numpy.typing import NDArray


def load_single_data_file(file_path: PathInput) -> tuple[str, pd.DataFrame, datetime | None]:
    # The package initializer imports every pipeline; keep this inside workers.
    from paradigma.load import load_single_data_file as official

    return cast("tuple[str, pd.DataFrame, datetime | None]", official(file_path))


def run_paradigma(**kwargs: Unpack[OfficialRunOptions]) -> AnalysisResults:
    from paradigma.orchestrator import run_paradigma as official

    return cast("AnalysisResults", official(**kwargs))


def prepare_raw_data(
    df: pd.DataFrame,
    accelerometer_units: AccelerationUnit = "m/s^2",
    gyroscope_units: GyroscopeUnit = "deg/s",
    time_input_unit: TimeInputUnit = "relative_s",
    resampling_frequency: float = 100.0,
    column_mapping: dict[str, str] | None = None,
    device_orientation: list[SignedAxis] | None = None,
    validate: bool = True,
    auto_segment: bool = False,
    max_segment_gap_s: float = 1.5,
    min_segment_length_s: float = 1.5,
) -> pd.DataFrame:
    from paradigma.prepare_data import prepare_raw_data as official

    return cast(
        "pd.DataFrame",
        official(
            df=df,
            accelerometer_units=accelerometer_units,
            gyroscope_units=gyroscope_units,
            time_input_unit=time_input_unit,
            resampling_frequency=resampling_frequency,
            column_mapping=column_mapping,
            device_orientation=device_orientation,
            validate=validate,
            auto_segment=auto_segment,
            max_segment_gap_s=max_segment_gap_s,
            min_segment_length_s=min_segment_length_s,
        ),
    )


def correct_watch_orientation(
    df: pd.DataFrame,
    device_orientation: list[SignedAxis] | None = None,
    sensor: Sensor | Literal["both"] = "both",
) -> pd.DataFrame:
    from paradigma.prepare_data import correct_watch_orientation as official

    return cast("pd.DataFrame", official(df, device_orientation=device_orientation, sensor=sensor))


def create_segments(
    time_array: NDArray[np.integer[Any] | np.floating[Any]], max_segment_gap_s: float
) -> SegmentArray:
    from paradigma.segmenting import create_segments as official

    return cast("SegmentArray", official(time_array, max_segment_gap_s))


def discard_segments(
    df: pd.DataFrame,
    segment_nr_colname: str,
    min_segment_length_s: float,
    fs: float,
    format: Literal["timestamps", "windows"] = "timestamps",
) -> pd.DataFrame:
    from paradigma.segmenting import discard_segments as official

    return cast("pd.DataFrame", official(df, segment_nr_colname, min_segment_length_s, fs, format))
