"""Result exports, saved-result actions and safe window closing."""

from __future__ import annotations

import traceback
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QObject
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QWidget,
)

from .contracts import AnalysisResults, PathInput, Provenance, RunRecord, StartJobCallback
from .history import RunHistory, now, run_is_saved
from .theme import STYLESHEET, light_palette
from .workspace_state import (
    InputState,
    JobState,
    PreviewServices,
    ResultState,
    RunState,
    ShellState,
)

if TYPE_CHECKING:
    import logging

    import pandas as pd
    from PySide6.QtGui import QCloseEvent


class ResultExporter(Protocol):
    def __call__(
        self,
        path: PathInput,
        results: AnalysisResults,
        provenance: Provenance,
        *,
        protected_sources: Iterable[PathInput] = (),
    ) -> None: ...


class TableExporter(Protocol):
    def __call__(
        self,
        path: PathInput,
        frame: pd.DataFrame,
        *,
        source: PathInput | None = None,
        protected_sources: Iterable[PathInput] = (),
    ) -> None: ...


class SaveRunResultsCallback(Protocol):
    def __call__(self, records: list[RunRecord], *, close_after: bool = False) -> None: ...


@dataclass(frozen=True)
class ExportView:
    parent: QWidget
    status: QLabel


@dataclass(frozen=True)
class ExportCallbacks:
    append_log: Callable[[str], None]
    failure: Callable[[str], None]
    persist_run: Callable[[RunRecord], None]
    record_output: Callable[[str, str], None]
    refresh_runs: Callable[[], None]
    save_run_results: SaveRunResultsCallback
    selected_export_table: Callable[[], tuple[str, pd.DataFrame | None]]
    start_job: StartJobCallback


@dataclass(frozen=True)
class ExportServices:
    export_results: ResultExporter
    export_table_csv: TableExporter


class ExportController(QObject):
    """Own export behavior through explicit state, frozen views and callbacks."""

    def __init__(
        self,
        inputs: InputState,
        jobs: JobState,
        results: ResultState,
        runs: RunState,
        shell: ShellState,
        view: ExportView,
        callbacks: ExportCallbacks,
        services: ExportServices,
        previews: PreviewServices,
        history: RunHistory,
    ) -> None:
        super().__init__(view.parent)
        self.inputs = inputs
        self.jobs = jobs
        self.results = results
        self.runs = runs
        self.shell = shell
        self.view = view
        self.callbacks = callbacks
        self.services = services
        self.previews = previews
        self.history = history

    def export(self) -> None:
        if self.results.results is None or self.jobs.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self.view.parent, "Export complete results", "paradigma-results.json", "JSON (*.json)"
        )
        if path:
            try:
                self.history.validate_export_destination(path, self.runs.runs)
                self.services.export_results(
                    path,
                    self.results.results,
                    self.results.provenance,
                    protected_sources=[
                        *self.inputs.sources.values(),
                        *self.results.provenance.get("sources", {}).values(),
                    ],
                )
                self.callbacks.record_output(path, "JSON")
                self.view.status.setText(f"Results exported to {path}")
            except Exception as exc:  # noqa: BLE001 -- Final export UI error reporting.
                # Final UI boundary for file writers and run-history callbacks.
                self.callbacks.append_log(traceback.format_exc())
                self.callbacks.failure(str(exc))

    def choose_export(self) -> None:
        if self.results.results is None or self.jobs.worker is not None:
            return
        from .exports import ExportDialog, export_items, export_selection

        dialog = ExportDialog(self.results.results, self.view.parent)
        if not dialog.exec():
            return
        extension = dialog.extension()
        path, _ = QFileDialog.getSaveFileName(
            self.view.parent,
            "Export results",
            f"paradigma-results.{extension}",
            f"{extension.upper()} (*.{extension})",
        )
        if not path:
            return
        selected, format_name = dialog.selected(), dialog.format.currentText()
        results, provenance, run = (
            self.results.results,
            self.results.provenance,
            self.runs.current_run,
        )
        tables, metadata = export_items(results)
        complete = format_name == "JSON" and set(selected) == set(tables) | set(metadata)
        protected = [*self.inputs.sources.values(), *provenance.get("sources", {}).values()]

        def write(logger: logging.Logger) -> str:
            self.history.validate_export_destination(path, self.runs.runs)
            export_selection(
                path, results, provenance, selected, format_name, protected_sources=protected
            )
            return str(Path(path).resolve())

        def completed(output_path: str) -> None:
            if run is not None:
                run["outputs"].append(
                    {
                        "kind": format_name,
                        "path": output_path,
                        "saved": now(),
                        "selected": selected,
                        "complete": complete,
                    }
                )
                self.callbacks.persist_run(run)
                self.callbacks.refresh_runs()
            self.view.status.setText(f"Results exported to {output_path}")

        self.view.status.setText("Exporting results…")
        self.callbacks.start_job(write, completed)

    def export_csv(self) -> None:
        name, frame = self.callbacks.selected_export_table()
        if frame is None or self.jobs.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self.view.parent, "Export selected rows", "output.csv", "CSV (*.csv)"
        )
        if path:
            try:
                self.history.validate_export_destination(path, self.runs.runs)
                self.services.export_table_csv(
                    path,
                    frame,
                    source=self.results.provenance.get("source", self.inputs.source),
                    protected_sources=[
                        *self.inputs.sources.values(),
                        *self.results.provenance.get("sources", {}).values(),
                    ],
                )
                self.callbacks.record_output(path, "CSV")
                self.view.status.setText(f"{len(frame):,} rows from {name} exported to {path}")
            except Exception as exc:  # noqa: BLE001 -- Final export UI error reporting.
                # Final UI boundary for file writers and run-history callbacks.
                self.callbacks.append_log(traceback.format_exc())
                self.callbacks.failure(str(exc))

    def unsaved_result_runs(self) -> list[RunRecord]:
        return [
            record
            for record in self.runs.runs
            if "_results" in record and (record.get("_unsaved_results") or not run_is_saved(record))
        ]

    def save_results(self) -> None:
        if (
            self.jobs.worker is not None
            or self.runs.current_run is None
            or self.results.results is None
        ):
            return
        self.runs.current_run["_results"] = self.results.results
        self.runs.current_run["_provenance"] = dict(self.results.provenance)
        self.callbacks.save_run_results([self.runs.current_run])

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.jobs.worker is not None:
            QMessageBox.information(
                self.view.parent,
                "Processing in progress",
                "Wait for processing to finish before closing.",
            )
            event.ignore()
        else:
            unsaved = self.unsaved_result_runs()
            if unsaved:
                warning = QMessageBox(self.view.parent)
                warning.setObjectName("unsavedResults")
                warning.setPalette(light_palette())
                warning.setStyleSheet(STYLESHEET)
                warning.setIcon(QMessageBox.Icon.Warning)
                warning.setWindowTitle("Unsaved results")
                warning.setText("Save results before closing?")
                warning.setInformativeText(
                    f"{len(unsaved)} run(s) have unsaved results. Closing without saving loses "
                    "these results; run history alone cannot restore them."
                )
                warning.setDetailedText(
                    "\n".join(
                        f"{record['started']} · {Path(record['source']).name}" for record in unsaved
                    )
                )
                warning.setStandardButtons(
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel
                )
                warning.setDefaultButton(QMessageBox.StandardButton.Cancel)
                warning.button(QMessageBox.StandardButton.Save).setText(
                    "Save all" if len(unsaved) > 1 else "Save"
                )
                answer = warning.exec()
                if answer != QMessageBox.StandardButton.Discard:
                    event.ignore()
                    if answer == QMessageBox.StandardButton.Save:
                        self.callbacks.save_run_results(unsaved, close_after=True)
                    return
            self.previews._origin_preview.shutdown()
            self.previews._time_preview.shutdown()
            self.previews._sensor_preview.shutdown()
            if self.shell._acknowledgements_dialog is not None:
                self.shell._acknowledgements_dialog.close()
            event.accept()
