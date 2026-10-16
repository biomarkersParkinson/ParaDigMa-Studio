"""Result exports, saved-result actions and safe window closing."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QWidget,
)

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


@dataclass(frozen=True)
class ExportView:
    parent: QWidget
    status: QLabel


@dataclass(frozen=True)
class ExportCallbacks:
    append_log: Callable[..., Any]
    failure: Callable[..., Any]
    persist_run: Callable[..., Any]
    record_output: Callable[..., Any]
    refresh_runs: Callable[..., Any]
    save_run_results: Callable[..., Any]
    selected_export_table: Callable[..., Any]
    start_job: Callable[..., Any]


@dataclass(frozen=True)
class ExportServices:
    export_results: Callable[..., Any]
    export_table_csv: Callable[..., Any]


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

    def export(self):
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
            except Exception as exc:
                # Final UI boundary for file writers and run-history callbacks.
                self.callbacks.append_log(traceback.format_exc())
                self.callbacks.failure(str(exc))

    def choose_export(self):
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

        def write(logger):
            self.history.validate_export_destination(path, self.runs.runs)
            export_selection(
                path, results, provenance, selected, format_name, protected_sources=protected
            )
            return str(Path(path).resolve())

        def completed(output_path):
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

    def export_csv(self):
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
            except Exception as exc:
                # Final UI boundary for file writers and run-history callbacks.
                self.callbacks.append_log(traceback.format_exc())
                self.callbacks.failure(str(exc))

    def unsaved_result_runs(self):
        return [
            record
            for record in self.runs.runs
            if "_results" in record and (record.get("_unsaved_results") or not run_is_saved(record))
        ]

    def save_results(self):
        if (
            self.jobs.worker is not None
            or self.runs.current_run is None
            or self.results.results is None
        ):
            return
        self.runs.current_run["_results"] = self.results.results
        self.runs.current_run["_provenance"] = dict(self.results.provenance)
        self.callbacks.save_run_results([self.runs.current_run])

    def closeEvent(self, event):
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
                warning.setIcon(QMessageBox.Warning)
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
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
                )
                warning.setDefaultButton(QMessageBox.Cancel)
                warning.button(QMessageBox.Save).setText("Save all" if len(unsaved) > 1 else "Save")
                answer = warning.exec()
                if answer != QMessageBox.Discard:
                    event.ignore()
                    if answer == QMessageBox.Save:
                        self.callbacks.save_run_results(unsaved, close_after=True)
                    return
            self.previews._origin_preview.shutdown()
            self.previews._time_preview.shutdown()
            self.previews._sensor_preview.shutdown()
            if getattr(self.shell, "_acknowledgements_dialog", None) is not None:
                self.shell._acknowledgements_dialog.close()
            event.accept()
