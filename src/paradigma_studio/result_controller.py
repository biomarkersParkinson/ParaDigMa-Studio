"""Coordinate result loading through explicit state, view and workflow ports."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .history import merge_errors
from .overview import recording_extent
from .result_data import prepare_result_data
from .results_view import normalise_clock, recording_clock
from .workspace_state import InputState, ResultState, RunState, SensorState

if TYPE_CHECKING:
    from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QTabWidget

    from .result_data import ResultData


@dataclass(frozen=True)
class ResultView:
    results_source: QLabel
    dataset: QComboBox
    export_button: QPushButton
    save_results_button: QPushButton
    status: QLabel
    result_tabs: QTabWidget


@dataclass(frozen=True)
class ResultCallbacks:
    append_log: Callable[[str], None]
    build_result_overview: Callable[..., None]
    populate_result_series: Callable[[], None]
    selected_result_series: Callable[[], list[tuple[str, str]]]
    select_dataset: Callable[[str], None]
    sync_table_outputs: Callable[[], None]
    show_notice: Callable[..., None]
    finish_run: Callable[..., None]
    capture_warning: Callable[[str], None]
    navigate: Callable[[int], None]
    is_busy: Callable[[], bool]
    align_recordings: Callable[..., tuple]
    analysis_alignment: Callable[..., tuple]


class ResultController:
    def __init__(
        self,
        state: ResultState,
        inputs: InputState,
        runs: RunState,
        sensors: SensorState,
        view: ResultView,
        callbacks: ResultCallbacks,
    ):
        self.state, self.inputs, self.runs, self.sensors = state, inputs, runs, sensors
        self.view, self.callbacks = view, callbacks

    def analyzed(self, results):
        """Install one result snapshot, then update the view and run lifecycle."""
        self._invalidate_views()
        self.state.results = results
        if self.runs.current_run is None:
            self.state.result_source_frame = (
                self.inputs.recordings if self.inputs.recordings else self.inputs.frame
            )
        settings = self.state.provenance.get("settings", {})
        batch_clock = self._align_sources(settings, results)
        self._resolve_clock(settings, batch_clock)
        if self.runs.active_run is not None:
            self.runs.active_run["_results"] = results
            self.runs.active_run["_provenance"] = dict(self.state.provenance)
            self.runs.active_run["_unsaved_results"] = True
        self.state._detail_selections = {}
        data = prepare_result_data(results, self.state._display_offsets)
        self._install_data(data)
        self._show_outputs(data)
        self._finish_analysis(results)
        self.view.result_tabs.setCurrentIndex(0)
        self.callbacks.navigate(2)

    def _invalidate_views(self):
        self.sensors._sensor_time_indices.clear()
        self.state._plot_signature = None
        self.state._profile_selection = None
        self.state._epoch_views.clear()
        self.state._epoch_presence_views.clear()
        self.state._gait_presence_cache = self.state._gait_epoch_cache = None
        self.state._table_views.clear()
        self.state._table_output_names = None

    def _align_sources(self, settings, results):
        batch_clock = None
        self.state._recording_bases = {}
        if isinstance(self.state.result_source_frame, dict):
            (
                self.state.result_timeline,
                self.state._source_timelines,
                self.state._display_offsets,
                batch_clock,
                self.state._recording_bases,
            ) = self.callbacks.align_recordings(self.state.result_source_frame, settings, results)
        else:
            (
                self.state.result_timeline,
                self.state._source_timelines,
                self.state._display_offsets,
            ) = self.callbacks.analysis_alignment(
                self.state.result_source_frame,
                settings,
                results,
                self.state.provenance.get("display_offsets"),
            )
        if self.state._display_offsets:
            self.state.provenance["display_offsets"] = dict(self.state._display_offsets)
        extent = recording_extent(self.state.result_timeline, self.state._recording_bases)
        if extent is not None:
            self.state.provenance["recording_extent"] = extent
        return batch_clock

    def _resolve_clock(self, settings, batch_clock):
        self.state.display_clock = None
        if self.state.provenance.get("display_clock"):
            try:
                self.state.display_clock = normalise_clock(self.state.provenance["display_clock"])
            except (ValueError, TypeError, KeyError, OverflowError):
                self.callbacks.append_log(
                    "Stored recording clock is invalid; using available recording timing."
                )
                self.state.provenance.pop("display_clock", None)
        if self.state.display_clock is None:
            self.state.display_clock = (
                batch_clock
                if isinstance(self.state.result_source_frame, dict)
                else recording_clock(
                    self.state.result_source_frame, settings, self.state.result_timeline
                )
            )
        origin = settings.get("plot_time_origin", {})
        if not self.state.provenance.get("display_clock") and origin.get("mode") == "custom":
            self.state.display_clock = normalise_clock(origin["clock"])
        elif origin.get("mode") == "elapsed":
            self.state.display_clock = None
        if self.state.display_clock is not None:
            self.state.provenance["display_clock"] = dict(self.state.display_clock)

    def _install_data(self, data: ResultData):
        self.state.tables, self.state.aggregation_tables = data.tables, data.aggregates
        self.state._plot_tables, self.state._plot_labels = data.plot_frames, data.plot_labels
        self.state._timings, self.state._interval_ends = data.timings, data.interval_ends
        self.state._bar_bounds = data.bar_bounds

    def _show_outputs(self, data: ResultData):
        sources = self.state.provenance.get("sources", {})
        self.view.results_source.setText(
            f"{len(sources)} recordings · One subject"
            if len(sources) > 1
            else Path(self.state.provenance.get("source", self.inputs.source)).name
            or "Current analysis"
        )
        self.callbacks.build_result_overview((data.coverage, data.coverage_labels))
        self.callbacks.populate_result_series()
        self.view.dataset.blockSignals(True)
        self.view.dataset.clear()
        self.view.dataset.addItems(self.state.tables)
        selected = [
            name for name, _ in self.callbacks.selected_result_series() if name in self.state.tables
        ]
        preferred = next(
            (name for name in selected if name.startswith("quantifications/")),
            selected[0] if selected else None,
        )
        if preferred is None:
            preferred = next(
                (
                    name
                    for name, frame in self.state.tables.items()
                    if name.startswith("quantifications/") and len(frame)
                ),
                None,
            )
        if preferred:
            self.view.dataset.setCurrentText(preferred)
        self.view.dataset.blockSignals(False)
        self.callbacks.select_dataset(self.view.dataset.currentText())
        self.callbacks.sync_table_outputs()
        self.view.export_button.setEnabled(not self.callbacks.is_busy())
        self.view.save_results_button.setEnabled(
            not self.callbacks.is_busy() and self.runs.current_run is not None
        )

    def _finish_analysis(self, results):
        errors = results.get("errors", [])
        if errors:
            self.callbacks.append_log(json.dumps(errors, indent=2, default=str))
            count = len(
                merge_errors(self.runs.active_run["errors"] if self.runs.active_run else [], errors)
            )
            message = f"Analysis returned {count} processing error(s); inspect Runs and the partial results."
            self.view.status.setText(message)
            self.callbacks.show_notice(message, "error")
            self.callbacks.finish_run("Partial", errors)
        else:
            has_rows = any(
                len(v) for k, v in self.state.tables.items() if k.startswith("quantifications/")
            )
            message = (
                "Analysis completed."
                if has_rows
                else "No quantified windows. See Runs for details."
            )
            if not has_rows:
                self.callbacks.capture_warning(message)
            record = self.runs.active_run or self.runs.current_run
            warnings = len(record["warnings"]) if record else 0
            logged_errors = len(record.get("errors", [])) if record else 0
            if logged_errors:
                message = f"Analysis returned {logged_errors} processing error(s); inspect Runs and the partial results."
                self.callbacks.show_notice(message, "error")
            elif warnings and has_rows:
                message = f"Analysis completed with {warnings} warning(s). See Runs."
                self.callbacks.show_notice(message)
            elif not has_rows:
                self.callbacks.show_notice(message)
            self.view.status.setText(message)
            self.callbacks.finish_run("Completed")
