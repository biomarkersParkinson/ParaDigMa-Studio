"""Explicit mutable workspace state shared by composed controllers.

Controllers receive these state objects directly. Qt ownership stays with the
top-level window; job state retains worker lifetimes. DataFrames reference the
existing input/results without copying or altering scientific tables here.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .contracts import (
    AnalysisResults,
    ClockMetadata,
    FloatArray,
    GaitIntervals,
    GaitSummaries,
    JSONValue,
    LoadingInfo,
    PositionArray,
    Provenance,
    RecordingDescription,
    RunRecord as RunRecord,
    SeriesKey,
    TimeOffsets,
)
from .result_plot_cache import ResultPlotCache

if TYPE_CHECKING:
    from threading import Event

    import numpy as np
    import pandas as pd
    from matplotlib.artist import Artist
    from matplotlib.axes import Axes
    from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QTreeWidgetItem, QWidget

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
    load_run_id: str | None = None
    loading: LoadingInfo | None = None


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
    provenance: Provenance = field(default_factory=dict)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    aggregation_tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    _plot_tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    _plot_labels: dict[SeriesKey, str] = field(default_factory=dict)
    _timings: dict[str, pd.DataFrame] = field(default_factory=dict)
    _interval_ends: dict[str, FloatArray] = field(default_factory=dict)
    _bar_bounds: dict[str, tuple[FloatArray, FloatArray]] = field(default_factory=dict)
    _display_offsets: TimeOffsets = field(default_factory=dict)
    _source_timelines: dict[str, FloatArray] | dict[str, dict[str, FloatArray]] = field(
        default_factory=dict
    )
    _recording_bases: dict[str, float] = field(default_factory=dict)
    _epoch_views: dict[tuple[Hashable, ...], pd.DataFrame | GaitSummaries] = field(
        default_factory=dict
    )
    _epoch_presence_views: dict[str, pd.DataFrame] = field(default_factory=dict)
    _detail_selections: dict[str, tuple[pd.DataFrame, PositionArray]] = field(default_factory=dict)
    results: AnalysisResults | None = None
    result_timeline: FloatArray | dict[str, FloatArray] | None = None
    result_source_frame: pd.DataFrame | dict[str, pd.DataFrame] | None = None
    display_clock: ClockMetadata | None = None
    _gait_presence_cache: GaitIntervals | None = None
    _gait_epoch_cache: GaitSummaries | None = None
    _plot_signature: tuple[int, tuple[SeriesKey, ...]] | None = None
    _installing_results: bool = False
    _profile_selection: tuple[str, str, float] | None = None
    _table_output_names: tuple[str, ...] | None = None
    active_frame: pd.DataFrame | None = None
    display_frame: pd.DataFrame | None = None
    active_positions: PositionArray | None = None
    active_selection: dict[str, JSONValue] = field(default_factory=dict)
    _table_views: OrderedDict[tuple[str, bool], pd.DataFrame] = field(default_factory=OrderedDict)

    _table_choices: dict[str, str | None] = field(default_factory=dict)
    _series_items: dict[SeriesKey, QTreeWidgetItem] = field(default_factory=dict)
    _result_layout_index: int | None = None
    results_scroll: QScrollArea | None = None
    overview_values: dict[tuple[str, str, tuple[str, ...]], QLabel] = field(default_factory=dict)
    overview_module_cards: dict[str, QWidget] = field(default_factory=dict)
    overview_gait_charts: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class SensorState:
    sensor_frame: pd.DataFrame | None = None
    sensor_times: FloatArray | None = None
    _sensor_context: SensorContext | None = None
    _sensor_navigator: SensorNavigator | None = None
    _sensor_time_indices: OrderedDict[tuple[int, float], tuple[FloatArray, SensorTimeIndex]] = (
        field(default_factory=OrderedDict)
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
    run_owner: RunRecord | None = None
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
