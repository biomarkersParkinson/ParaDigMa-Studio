"""Preparation values and the keyword API of the pinned ParaDigMa 1.1.2.

These contracts describe choices, not the physical contents of a recording.
Runtime validation and scientific equivalence checks remain necessary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypeAlias, TypedDict

from .contracts import PathInput, Pipeline, SensorInput

if TYPE_CHECKING:
    import logging

    import pandas as pd
    from paradigma.config import GaitConfig, IMUConfig, PPGConfig, PulseRateConfig, TremorConfig

Sensor: TypeAlias = Literal["accelerometer", "gyroscope"]
SignedAxis: TypeAlias = Literal["x", "y", "z", "-x", "-y", "-z"]
IMUSignal: TypeAlias = Literal[
    "accelerometer_x",
    "accelerometer_y",
    "accelerometer_z",
    "gyroscope_x",
    "gyroscope_y",
    "gyroscope_z",
]
Signal: TypeAlias = Literal["time", "green"] | IMUSignal
SignalColumns: TypeAlias = dict[Signal, str | None]
AccelerationUnit: TypeAlias = Literal["g", "m/s^2"]
GyroscopeUnit: TypeAlias = Literal["deg/s", "rad/s"]
TimeInputUnit: TypeAlias = Literal[
    "relative_s", "relative_ms", "absolute_s", "absolute_ms", "difference_s", "difference_ms"
]
WatchSide: TypeAlias = Literal["left", "right"]
PipelineStep: TypeAlias = Literal[
    "preprocessing", "classification", "quantification", "aggregation"
]
IntermediateStep: TypeAlias = Literal["preparation"] | PipelineStep


class PreparationOptions(TypedDict, total=False):
    """Preparation keywords shared with the official orchestrator."""

    accelerometer_units: AccelerationUnit
    gyroscope_units: GyroscopeUnit
    time_input_unit: TimeInputUnit
    device_orientation: list[SignedAxis] | None
    skip_preparation: bool
    split_by_gaps: bool
    max_gap_seconds: float | None
    min_segment_seconds: float | None


class PreparationSettings(PreparationOptions, total=False):
    """App preparation keywords; mapping and missing-row policy are explicit arguments."""

    axis_inversions: list[IMUSignal] | None
    signal_columns: SignalColumns | None


class PipelineOptions(TypedDict, total=False):
    """Other forwarded keywords, separate from open saved/display settings."""

    run_steps: list[PipelineStep] | Literal["all"]
    save_intermediate: list[IntermediateStep]
    return_intermediate: list[IntermediateStep]
    output_dir: PathInput
    watch_side: WatchSide | None
    file_pattern: str | list[str] | None
    aggregates: list[str] | None
    gait_segment_categories: list[tuple[float, float] | list[float] | str] | None
    imu_config: IMUConfig | None
    ppg_config: PPGConfig | None
    gait_config: GaitConfig | None
    arm_activity_config: GaitConfig | None
    tremor_config: TremorConfig | None
    pulse_rate_config: PulseRateConfig | None
    logging_level: int


class AnalysisOptions(PreparationSettings, PipelineOptions, total=False):
    """Supported extra keywords to core.analyze; no display-only settings."""

    data_path: PathInput | None
    custom_logger: logging.Logger | None


class OfficialRunOptions(PreparationOptions, PipelineOptions, total=False):
    """Exact keyword names accepted by the pinned official orchestrator."""

    data_path: PathInput | None
    dfs: SensorInput | list[pd.DataFrame] | None
    pipelines: Pipeline | list[Pipeline] | None
    column_mapping: dict[str, str] | None
    custom_logger: logging.Logger | None
