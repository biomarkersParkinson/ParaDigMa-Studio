"""Coordinate result loading through explicit state, view and workflow ports."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from .contracts import (
    AnalysisResults,
    AnalysisSettings,
    FinishRunCallback,
    FloatArray,
    NoticeCallback,
    Provenance,
    RecordingAlignment,
    SensorInput,
    TimeOffsets,
)
from .history import merge_errors
from .result_preparation import PreparedResults, prepare_results
from .workspace_state import InputState, ResultState, RunState, SensorState

if TYPE_CHECKING:
    import pandas as pd
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
    build_result_overview: Callable[
        [tuple[dict[str, pd.DataFrame], dict[tuple[str, str], str]]], None
    ]
    populate_result_series: Callable[[], None]
    selected_result_series: Callable[[], list[tuple[str, str]]]
    select_dataset: Callable[[str], None]
    sync_table_outputs: Callable[[], None]
    show_notice: NoticeCallback
    finish_run: FinishRunCallback
    capture_warning: Callable[[str], None]
    navigate: Callable[[int], None]
    is_busy: Callable[[], bool]
    align_recordings: Callable[
        [dict[str, pd.DataFrame], AnalysisSettings, AnalysisResults], RecordingAlignment
    ]
    analysis_alignment: Callable[
        [pd.DataFrame | None, AnalysisSettings, AnalysisResults, TimeOffsets | None],
        tuple[FloatArray | None, dict[str, FloatArray], dict[str, float]],
    ]


class ResultController:
    def __init__(
        self,
        state: ResultState,
        inputs: InputState,
        runs: RunState,
        sensors: SensorState,
        view: ResultView,
        callbacks: ResultCallbacks,
    ) -> None:
        self.state, self.inputs, self.runs, self.sensors = state, inputs, runs, sensors
        self.view, self.callbacks = view, callbacks

    def analyzed(self, results: AnalysisResults) -> None:
        """Install one result snapshot, then update the view and run lifecycle."""
        self._invalidate_views()
        self.state.results = results
        if self.runs.current_run is None:
            self.state.result_source_frame = (
                self.inputs.recordings if self.inputs.recordings else self.inputs.frame
            )
        prepared = self.prepare(results, self.state.provenance, self.state.result_source_frame)
        self._install(prepared)

    def prepare(
        self, results: AnalysisResults, provenance: Provenance, source_frame: SensorInput | None
    ) -> PreparedResults:
        """Worker-safe preparation through the same explicit scientific services."""
        prepared = prepare_results(
            results,
            provenance,
            source_frame,
            align_recordings=self.callbacks.align_recordings,
            analysis_alignment=self.callbacks.analysis_alignment,
        )
        if any(
            "gait" in results.get(stage, {})
            for stage in ("aggregations", "metadata", "classifications", "quantifications")
        ):
            # Import chart classes in the worker; actual Qt widgets and canvases
            # are created only by the overview renderer on the UI thread.
            import_module(".gait_overview", __package__)
        return prepared

    def install_prepared(self, prepared: PreparedResults) -> None:
        """Install a completed background snapshot; defer its hidden graph build."""
        self._invalidate_views()
        self.state.results = prepared.results
        self.state.result_source_frame = prepared.source_frame
        self.state._installing_results = True
        try:
            self._install(prepared)
        finally:
            self.state._installing_results = False

    def _install(self, prepared: PreparedResults) -> None:
        results, data = prepared.results, prepared.data
        self.state.provenance = prepared.provenance
        self.state.result_timeline = prepared.timeline
        self.state._source_timelines = prepared.source_timelines
        self.state._display_offsets = prepared.offsets
        self.state._recording_bases = prepared.recording_bases
        self.state.display_clock = prepared.clock
        for notice in prepared.notices:
            self.callbacks.append_log(notice)
        if self.runs.active_run is not None:
            self.runs.active_run["_results"] = results
            self.runs.active_run["_provenance"] = dict(self.state.provenance)
            self.runs.active_run["_unsaved_results"] = True
        self.state._detail_selections = {}
        self._install_data(data)
        self._show_outputs(data)
        self._finish_analysis(results)
        self.view.result_tabs.setCurrentIndex(0)
        self.callbacks.navigate(2)

    def _invalidate_views(self) -> None:
        self.sensors._sensor_time_indices.clear()
        self.state._plot_signature = None
        self.state._profile_selection = None
        self.state._epoch_views.clear()
        self.state._epoch_presence_views.clear()
        self.state._gait_presence_cache = self.state._gait_epoch_cache = None
        self.state._table_views.clear()
        self.state._table_output_names = None

    def _install_data(self, data: ResultData) -> None:
        self.state.tables, self.state.aggregation_tables = data.tables, data.aggregates
        self.state._plot_tables, self.state._plot_labels = data.plot_frames, data.plot_labels
        self.state._timings, self.state._interval_ends = data.timings, data.interval_ends
        self.state._bar_bounds = data.bar_bounds

    def _show_outputs(self, data: ResultData) -> None:
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
        self.view.dataset.addItems(list(self.state.tables))
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

    def _finish_analysis(self, results: AnalysisResults) -> None:
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
