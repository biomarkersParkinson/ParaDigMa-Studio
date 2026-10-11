"""Explicit mutable workspace state shared by composed controllers.

Qt widgets and workers remain owned by MainWindow. DataFrames are references to
existing input/results; controllers never copy or alter scientific tables here.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .contracts import RunRecord as RunRecord

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd
    from matplotlib.axes import Axes

    from .exploration import SensorContext
    from .sensor_navigation import SensorNavigator, SensorTimeIndex


@dataclass
class InputState:
    frame: pd.DataFrame | None = None
    source: str = ""
    sources: dict[str, str] = field(default_factory=dict)
    recordings: dict[str, pd.DataFrame] = field(default_factory=dict)


@dataclass
class RunState:
    runs: list[RunRecord] = field(default_factory=list)
    active_run: RunRecord | None = None
    current_run: RunRecord | None = None
    selected_run: RunRecord | None = None
    _run_row_records: tuple[RunRecord, ...] = ()
    _close_after_save: bool = False


@dataclass
class ResultState:
    provenance: dict = field(default_factory=dict)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    aggregation_tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    _plot_tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    _plot_labels: dict[tuple[str, str], str] = field(default_factory=dict)
    _timings: dict[str, pd.DataFrame] = field(default_factory=dict)
    _interval_ends: dict[str, np.ndarray] = field(default_factory=dict)
    _bar_bounds: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)
    _display_offsets: dict = field(default_factory=dict)
    _source_timelines: dict = field(default_factory=dict)
    _recording_bases: dict = field(default_factory=dict)
    _epoch_views: dict = field(default_factory=dict)
    _epoch_presence_views: dict = field(default_factory=dict)
    _detail_selections: dict = field(default_factory=dict)
    results: dict[str, Any] | None = None
    result_timeline: Any = None
    result_source_frame: pd.DataFrame | dict[str, pd.DataFrame] | None = None
    display_clock: dict | None = None
    _gait_presence_cache: Any = None
    _gait_epoch_cache: Any = None
    _plot_signature: Any = None
    _table_output_names: Any = None
    active_frame: pd.DataFrame | None = None
    display_frame: pd.DataFrame | None = None
    active_positions: np.ndarray | None = None
    active_selection: dict = field(default_factory=dict)
    _table_views: OrderedDict = field(default_factory=OrderedDict)


@dataclass
class SensorState:
    sensor_frame: pd.DataFrame | None = None
    sensor_times: np.ndarray | None = None
    _sensor_context: SensorContext | None = None
    _sensor_navigator: SensorNavigator | None = None
    _sensor_time_indices: OrderedDict[tuple[int, float], tuple[Any, SensorTimeIndex]] = field(
        default_factory=OrderedDict
    )
    _sensor_view_callbacks: dict[Axes, int] = field(default_factory=dict)
    _sensor_channel_colors: dict[str, str | tuple[float, ...] | np.ndarray] = field(
        default_factory=dict
    )


def state_property(container, name):
    """Keep existing window attributes as explicit views of controller state."""
    return property(
        lambda owner: getattr(getattr(owner, container), name),
        lambda owner, value: setattr(getattr(owner, container), name, value),
    )
