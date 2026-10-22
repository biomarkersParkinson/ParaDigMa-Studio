"""Analysis controls, clock previews and run configuration."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from importlib.metadata import version
from threading import Event
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject, QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QWidget,
)

from .analysis_help import DEFAULT_MAX_GAP_SECONDS, DEFAULT_MIN_SECTION_SECONDS
from .axis_mapping import migrate_legacy_orientation
from .core import validate_column_mapping
from .history import new_run
from .results_view import (
    normalise_clock,
)
from .time_controls import TimeField
from .ui.column_mapping import ColumnMappingEditor
from .ui.file_defaults import FileDefaults
from .widgets import (
    ContextComboBox,
    WrappedForm,
)
from .workspace_state import (
    AnalysisState,
    InputState,
    JobState,
    PreviewServices,
    ResultState,
    RunState,
)

if TYPE_CHECKING:
    import logging

    import pandas as pd

    from .contracts import (
        AnalysisResults,
        AnalysisSettings,
        ClockMetadata,
        NoticeCallback,
        RunRecord,
        SensorInput,
        StartJobCallback,
    )


@dataclass(frozen=True)
class AnalysisView:
    parent: QWidget
    acc: QComboBox
    analysis_controls: WrappedForm
    analysis_help: dict[str, tuple[QPushButton, QLabel]]
    analysis_help_panel: QWidget
    analysis_help_sections: dict[str, QWidget]
    analysis_scroll: QScrollArea
    clock_input: TimeField
    drop_missing: QCheckBox
    file_badges: dict[str, QLabel]
    file_default_buttons: dict[str, QPushButton]
    gaps: QCheckBox
    gyro: QComboBox
    log: QPlainTextEdit
    mapping: ColumnMappingEditor
    metadata_notice: QLabel
    max_gap: QDoubleSpinBox
    min_segment: QDoubleSpinBox
    module_buttons: dict[str, QPushButton]
    module_requirements: QLabel
    prepared: QCheckBox
    run_button: QPushButton
    side: ContextComboBox
    status: QLabel
    stop_button: QPushButton
    time: QComboBox


@dataclass(frozen=True)
class AnalysisCallbacks:
    analyzed: Callable[[AnalysisResults], None]
    clear_results: Callable[[], None]
    failure: Callable[[str], None]
    navigate: Callable[[int], None]
    persist_run: Callable[[RunRecord], bool]
    refresh_runs: Callable[[], None]
    show_notice: NoticeCallback
    start_job: StartJobCallback


@dataclass(frozen=True)
class AnalysisServices:
    recording_clock: Callable[[pd.DataFrame, AnalysisSettings], ClockMetadata | None]
    preview_recording_clock: Callable[
        [dict[str, pd.DataFrame], AnalysisSettings], ClockMetadata | None
    ]
    run_isolated_analysis: Callable[
        [SensorInput, AnalysisSettings, logging.Logger, Event], AnalysisResults
    ]


class AnalysisController(QObject):
    """Own analysis behavior through explicit state, frozen views and callbacks."""

    def __init__(
        self,
        analysis: AnalysisState,
        inputs: InputState,
        jobs: JobState,
        results: ResultState,
        runs: RunState,
        view: AnalysisView,
        callbacks: AnalysisCallbacks,
        services: AnalysisServices,
        previews: PreviewServices,
        modules: dict[str, str],
    ) -> None:
        super().__init__(view.parent)
        self.analysis = analysis
        self.inputs = inputs
        self.jobs = jobs
        self.results = results
        self.runs = runs
        self.view = view
        self.callbacks = callbacks
        self.services = services
        self.previews = previews
        self.modules = modules
        self.file_defaults = FileDefaults(
            {"Acceleration units": view.acc, "Gyroscope units": view.gyro, "Time units": view.time},
            view.file_badges,
            view.file_default_buttons,
            view.analysis_help,
            view.metadata_notice,
            self.update_origin_default,
        )

    def toggle_analysis_help(self, title: str, checked: bool) -> None:
        if self.analysis._updating_analysis_help:
            return
        self.analysis._updating_analysis_help = True
        # The Analyze page installs its body and all three layouts before wiring help.
        body = cast("QWidget", self.view.analysis_scroll.widget())
        updates = body.updatesEnabled()
        body.setUpdatesEnabled(False)
        try:
            if checked:
                for other_title, (info, _) in self.view.analysis_help.items():
                    if other_title != title:
                        info.setChecked(False)
            for name, (info, description) in self.view.analysis_help.items():
                description.setVisible(info.isChecked())
                self.view.analysis_help_sections[name].setVisible(info.isChecked())
            self.view.analysis_help_panel.setVisible(
                any(info.isChecked() for info, _ in self.view.analysis_help.values())
            )
            # Fit the fixed-height wrapper synchronously. Activating its layout
            # alone still uses the old height until a queued LayoutRequest,
            # which can paint the help over the parameter card in the meantime.
            for widget in (self.view.analysis_help_panel, self.view.analysis_controls, body):
                if isinstance(widget, WrappedForm):
                    widget._fit_height()
                cast("QLayout", widget.layout()).activate()
        finally:
            body.setUpdatesEnabled(updates)
            self.analysis._updating_analysis_help = False

    def selected_modules(self) -> list[str]:
        return [
            self.modules[name]
            for name, item in self.view.module_buttons.items()
            if item.isChecked()
        ]

    def reset_for_input(self) -> None:
        """Start a new input with fresh controls, then apply only its metadata."""
        self.previews._origin_preview.clear()
        controls = (
            self.view.side,
            self.view.acc,
            self.view.gyro,
            self.view.time,
            self.view.prepared,
            self.view.gaps,
            self.view.drop_missing,
            self.view.max_gap,
            self.view.min_segment,
            self.view.clock_input,
            self.view.mapping,
            *self.view.module_buttons.values(),
            *(info for info, _description in self.view.analysis_help.values()),
        )
        self.file_defaults.applying = True
        try:
            with ExitStack() as stack:
                for control in controls:
                    stack.enter_context(QSignalBlocker(control))
                self.analysis._origin_override = False
                self.file_defaults.reset()
                self.view.side.setCurrentText("left")
                self.view.prepared.setChecked(False)
                self.view.gaps.setChecked(True)
                self.view.drop_missing.setChecked(True)
                self.view.max_gap.setValue(DEFAULT_MAX_GAP_SECONDS)
                self.view.min_segment.setValue(DEFAULT_MIN_SECTION_SECONDS)
                self.view.clock_input.set_clock(None)
                self.view.clock_input.clear()
                self.view.mapping.reset_for_input()
                for name, item in self.view.module_buttons.items():
                    item.setChecked(self.modules[name] == "gait")
                for info, _description in self.view.analysis_help.values():
                    info.setChecked(False)
        finally:
            self.file_defaults.applying = False
        self.toggle_analysis_help("", False)
        self.preparation_changed()
        self.view.analysis_scroll.verticalScrollBar().setValue(0)

    def set_modules(self, pipelines: Iterable[str]) -> None:
        selected = set(pipelines)
        for name, item in self.view.module_buttons.items():
            blocked = item.blockSignals(True)
            item.setChecked(self.modules[name] in selected)
            item.blockSignals(blocked)
        self.modules_changed()

    def modules_changed(self, changed: str | None = None, checked: bool = False) -> None:
        selected = self.selected_modules()
        self.view.mapping.set_modules(selected)
        self.view.side.set_relevant("gait" in selected)
        requirements = []
        if "gait" in selected:
            requirements.append("Accelerometer")
        if "gait" in selected or "tremor" in selected:
            requirements.append("gyroscope")
        if "pulse_rate" in selected:
            requirements.append("raw green PPG")
        text = ", ".join(requirements)
        self.view.module_requirements.setText(
            text[0].upper() + text[1:] + " required." if text else "Select an analysis module."
        )
        self.view.run_button.setEnabled(
            self.inputs.frame is not None and bool(selected) and self.jobs.worker is None
        )
        self.update_origin_default()

    def preparation_changed(self, *_: object) -> None:
        prepared = self.view.prepared.isChecked()
        widget: QWidget
        for widget in (
            self.view.acc,
            self.view.gyro,
            self.view.time,
            *self.view.file_default_buttons.values(),
            self.view.gaps,
        ):
            widget.setEnabled(not prepared)
        self.view.mapping.set_preparation_enabled(not prepared)
        for widget in (self.view.max_gap, self.view.min_segment):
            widget.setEnabled(not prepared and self.view.gaps.isChecked())
        self.modules_changed()

    def origin_edited(self) -> None:
        self.analysis._origin_override = True
        self.file_defaults.mark_manual(["Time origin"])
        self.previews._origin_preview.cancel_pending()
        self.view.clock_input.setEnabled(True)

    def reset_origin(self) -> None:
        self.analysis._origin_override = False
        self.update_origin_default()

    def update_origin_default(self, *_: object) -> None:
        if self.file_defaults.applying:
            return
        if self.inputs.frame is not None:
            self.file_defaults.refresh(
                self.inputs.recordings or {"recording_001": self.inputs.frame},
                self.view.mapping.model.choices,
            )
        if self.analysis._origin_override or self.inputs.frame is None:
            return
        try:
            settings: AnalysisSettings = {
                "time_input_unit": self.view.time.currentText(),
                "skip_preparation": self.view.prepared.isChecked(),
                "column_mapping": validate_column_mapping(self.view.mapping.mapping()),
                "signal_columns": self.view.mapping.signal_columns(),
                "pipelines": self.selected_modules(),
                "drop_missing_samples": self.view.drop_missing.isChecked(),
            }
        except (ValueError, TypeError, KeyError, OverflowError):
            self.previews._origin_preview.cancel_pending()
            self.apply_origin_preview(None)
            return
        if settings["skip_preparation"] or not settings["drop_missing_samples"]:
            settings["pipelines"] = []
        elif "gait" in settings["pipelines"]:
            # Gait already requires every channel needed by tremor. Adding
            # tremor cannot change which samples establish the clock.
            settings["pipelines"] = [name for name in settings["pipelines"] if name != "tremor"]
        frame, recordings = self.inputs.frame, self.inputs.recordings
        key = json.dumps(settings, sort_keys=True)
        if self.previews._origin_preview.is_requested(key):
            return

        def preview() -> ClockMetadata | None:
            if recordings:
                return self.services.preview_recording_clock(recordings, settings)
            return self.services.recording_clock(frame, settings)

        # Keep the current value editable. A user edit cancels the automatic
        # preview, so its eventual result cannot overwrite that choice.
        self.previews._origin_preview.request(key, preview)

    def apply_origin_preview(self, clock: ClockMetadata | None) -> None:
        if self.analysis._origin_override:
            return
        self.view.clock_input.set_clock(clock)
        self.view.clock_input.setText(clock["origin"] if clock else "")
        self.view.clock_input.setEnabled(True)
        self.file_defaults.set_origin(clock)

    def origin_setting(self) -> AnalysisSettings:
        if not self.analysis._origin_override:
            return {"mode": "automatic"}
        entered = self.view.clock_input.text().strip()
        if not entered:
            return {"mode": "elapsed"}
        clock = self.view.clock_input._clock
        return {
            "mode": "custom",
            "clock": normalise_clock(
                {
                    "origin": entered,
                    "source": "User supplied",
                    "timezone": clock.get("timezone") if clock else None,
                }
            ),
        }

    def run_analysis(self) -> None:
        if self.jobs.worker is not None:
            return
        if self.inputs.frame is None:
            self.callbacks.show_notice("Open a recording in Data before running an analysis.")
            self.callbacks.navigate(0)
            return
        pipelines = self.selected_modules()
        if not pipelines:
            self.callbacks.show_notice("Select an analysis module.")
            self.callbacks.navigate(1)
            return
        try:
            settings = self._analysis_settings(pipelines)
        except (ValueError, KeyError) as exc:
            self.callbacks.failure(str(exc))
            return
        frame = self._initialize_analysis_run(settings)
        self._start_analysis_job(frame, settings)

    def _analysis_settings(self, pipelines: list[str]) -> AnalysisSettings:
        mapping = validate_column_mapping(self.view.mapping.mapping())
        settings: AnalysisSettings = {
            "pipelines": pipelines,
            "watch_side": self.view.side.currentText(),
            "accelerometer_units": self.view.acc.currentData(),
            "gyroscope_units": self.view.gyro.currentText(),
            "time_input_unit": self.view.time.currentText(),
            "device_orientation": ["x", "y", "z"],
            "axis_inversions": []
            if self.view.prepared.isChecked()
            else self.view.mapping.axis_inversions(),
            "column_mapping": mapping,
            "signal_columns": self.view.mapping.signal_columns(),
            "skip_preparation": self.view.prepared.isChecked(),
            "split_by_gaps": self.view.gaps.isChecked(),
            "drop_missing_samples": self.view.drop_missing.isChecked(),
            "max_gap_seconds": self.view.max_gap.value(),
            "min_segment_seconds": self.view.min_segment.value(),
        }
        settings["plot_time_origin"] = self.origin_setting()
        if self.view.prepared.isChecked():
            settings.update(
                accelerometer_units="g",
                gyroscope_units="deg/s",
                time_input_unit="relative_s",
                split_by_gaps=False,
            )
        return settings

    def _initialize_analysis_run(self, settings: AnalysisSettings) -> SensorInput:
        self.callbacks.show_notice("")
        record = new_run(self.inputs.source, settings)
        if self.inputs.recordings:
            record["sources"] = dict(self.inputs.sources)
        record["paradigma_version"] = version("paradigma")
        frame = cast(
            "SensorInput", self.inputs.recordings if self.inputs.recordings else self.inputs.frame
        )
        record["_frame"] = frame
        self.runs.runs.insert(0, record)
        self.runs.active_run = self.runs.current_run = self.runs.selected_run = record
        self.results.provenance = {
            "source": self.inputs.source,
            "paradigma_version": record["paradigma_version"],
            "settings": settings,
            "run_id": record["id"],
        }
        self.results.result_source_frame = frame
        self.results.result_timeline = None
        self.callbacks.clear_results()
        self.view.log.clear()
        self.callbacks.persist_run(record)
        self.callbacks.refresh_runs()
        self.view.status.setText("Running ParaDigMa… Review progress in Runs.")
        self.callbacks.navigate(1)
        if self.inputs.recordings:
            self.results.provenance["sources"] = dict(self.inputs.sources)
        return frame

    def _start_analysis_job(self, frame: SensorInput, settings: AnalysisSettings) -> None:
        core_settings = dict(settings)
        core_settings.pop("plot_time_origin", None)
        self.jobs._analysis_stop = Event()
        cancel = self.jobs._analysis_stop
        self.callbacks.start_job(
            lambda logger: self.services.run_isolated_analysis(
                frame, core_settings, logger, cancel
            ),
            self.callbacks.analyzed,
        )
        self.view.stop_button.setEnabled(self.jobs.worker is not None)

    def use_run_parameters(self) -> None:
        if self.runs.selected_run is None or self.jobs.worker is not None:
            return
        settings = self.runs.selected_run["settings"]
        self.file_defaults.mark_manual(
            [
                title
                for title, key in (
                    ("Acceleration units", "accelerometer_units"),
                    ("Gyroscope units", "gyroscope_units"),
                    ("Time units", "time_input_unit"),
                )
                if key in settings
            ],
            "Restored from saved run parameters.",
        )
        self.set_modules(settings.get("pipelines", ["gait"]))
        self.file_defaults.applying = True
        try:
            for widget, key in (
                (self.view.side, "watch_side"),
                (self.view.acc, "accelerometer_units"),
                (self.view.gyro, "gyroscope_units"),
                (self.view.time, "time_input_unit"),
            ):
                if key in settings:
                    value = str(settings[key])
                    index = widget.findData(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                    else:
                        widget.setCurrentText(value)
        finally:
            self.file_defaults.applying = False
        self._restore_signal_columns(settings)
        self.view.prepared.setChecked(settings.get("skip_preparation", False))
        self.view.gaps.setChecked(settings.get("split_by_gaps", False))
        self.view.drop_missing.setChecked(settings.get("drop_missing_samples", False))
        self.view.max_gap.setValue(
            settings.get("max_gap_seconds", DEFAULT_MAX_GAP_SECONDS) or DEFAULT_MAX_GAP_SECONDS
        )
        self.view.min_segment.setValue(
            settings.get("min_segment_seconds", DEFAULT_MIN_SECTION_SECONDS)
            or DEFAULT_MIN_SECTION_SECONDS
        )
        origin = settings.get("plot_time_origin", {"mode": "automatic"})
        self.analysis._origin_override = origin.get("mode") != "automatic"
        if self.analysis._origin_override:
            self.origin_edited()
        if origin.get("mode") == "custom":
            self.view.clock_input.set_clock(origin["clock"])
            self.view.clock_input.setText(origin["clock"]["origin"])
        elif origin.get("mode") == "elapsed":
            self.view.clock_input.clear()
        else:
            self.update_origin_default()
        self.preparation_changed()
        self.callbacks.navigate(1)
        self.view.status.setText(
            "Run parameters restored. Check the selected input before running."
        )

    def _restore_signal_columns(self, settings: AnalysisSettings) -> None:
        mapping = settings.get("column_mapping")
        inversions = settings.get("axis_inversions")
        if inversions is None:
            # Prepared runs never applied legacy orientation. Renaming still did.
            orientation = (
                None if settings.get("skip_preparation") else settings.get("device_orientation")
            )
            mapping, inversions = migrate_legacy_orientation(mapping, orientation)
        self.view.mapping.set_mapping(mapping, signal_columns=settings.get("signal_columns"))
        self.view.mapping.set_axis_inversions(inversions)
