"""Explicit mutable workspace state shared by composed controllers.

Controllers receive these state objects directly. Qt ownership stays with the
top-level window; job state retains worker lifetimes. DataFrames reference the
existing input/results without copying or altering scientific tables here.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .contracts import ClockMetadata, RecordingDescription, RunRecord as RunRecord
from .result_plot_cache import ResultPlotCache

if TYPE_CHECKING:
    from threading import Event

    import numpy as np
    import pandas as pd
    from matplotlib.artist import Artist
    from matplotlib.axes import Axes
    from PySide6.QtWidgets import QDialog

    from .exploration import SensorContext
    from .jobs import Worker
    from .previews import CachedPreview
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
    display_clock: ClockMetadata | None = None
    _gait_presence_cache: Any = None
    _gait_epoch_cache: Any = None
    _plot_signature: Any = None
    _installing_results: bool = False
    _profile_selection: tuple[str, str, float] | None = None
    _table_output_names: Any = None
    active_frame: pd.DataFrame | None = None
    display_frame: pd.DataFrame | None = None
    active_positions: np.ndarray | None = None
    active_selection: dict = field(default_factory=dict)
    _table_views: OrderedDict = field(default_factory=OrderedDict)

    _table_choices: dict = field(default_factory=dict)
    _series_items: dict = field(default_factory=dict)
    _result_layout_index: Any = None
    results_scroll: Any = None
    overview_values: dict = field(default_factory=dict)
    overview_module_cards: dict = field(default_factory=dict)
    overview_gait_charts: dict = field(default_factory=dict)


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


@dataclass
class DataState:
    _input_descriptions: dict[str, RecordingDescription] = field(default_factory=dict)
    _data_plot_dirty: bool = True
    _channel_colors: dict = field(default_factory=dict)


@dataclass
class AnalysisState:
    _origin_override: bool = False


@dataclass
class JobState:
    worker: Worker | None = None
    _analysis_stop: Event | None = None


@dataclass
class GraphState:
    _result_selection_artists: list[Artist] = field(default_factory=list)
    _result_shared_axes: Axes | None = None
    _result_plot_cache: ResultPlotCache = field(default_factory=ResultPlotCache)


@dataclass
class ShellState:
    sidebar_collapsed: bool = True
    _acknowledgements_dialog: QDialog | None = None


@dataclass(frozen=True)
class PreviewServices:
    _origin_preview: CachedPreview
    _time_preview: CachedPreview
    _sensor_preview: CachedPreview
