"""Result exports, saved-result actions and safe window closing."""

from __future__ import annotations

import traceback
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from PySide6.QtCore import QObject
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QWidget,
)

from .contracts import (
    AnalysisResults,
    OutputKind,
    PathInput,
    Provenance,
    RunOutput,
    RunRecord,
    StartJobCallback,
)
from .history import RunHistory, now, run_is_saved
from .provenance import provenance_for_record
from .result_integrity import provenance_for_run, validate_checksum, validate_run_id
from .serialization import csv_metadata_path
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
    ) -> str: ...


class TableExporter(Protocol):
    def __call__(
        self,
        path: PathInput,
        frame: pd.DataFrame,
        *,
        source: PathInput | None = None,
        protected_sources: Iterable[PathInput] = (),
        provenance: Provenance | None = None,
    ) -> None: ...


class SaveRunResultsCallback(Protocol):
    def __call__(self, records: list[RunRecord], *, close_after: bool = False) -> None: ...


class RecordOutputCallback(Protocol):
    def __call__(
        self,
        path: str,
        kind: OutputKind,
        *,
        checksum: str | None = None,
        metadata_path: PathInput | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class ExportView:
    parent: QWidget
    status: QLabel


@dataclass(frozen=True)
class ExportCallbacks:
    append_log: Callable[[str], None]
    failure: Callable[[str], None]
    persist_run: Callable[[RunRecord], None]
    record_output: RecordOutputCallback
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
                checksum = self.services.export_results(
                    path,
                    self.results.results,
                    self._owned_provenance(self.results.provenance, self.runs.current_run),
                    protected_sources=[
                        *self.inputs.sources.values(),
                        *self.results.provenance.get("sources", {}).values(),
                    ],
                )
                self.callbacks.record_output(path, "JSON", checksum=validate_checksum(checksum))
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
        selected = dialog.selected()
        # The non-editable chooser contains exactly the two supported output kinds.
        format_name = cast(OutputKind, dialog.format.currentText())
        results, provenance, run = (
            self.results.results,
            self.results.provenance,
            self.runs.current_run,
        )
        tables, metadata = export_items(results)
        complete = format_name == "JSON" and set(selected) == set(tables) | set(metadata)
        companion = (
            csv_metadata_path(path)
            if format_name == "CSV" and len(selected) == 1 and selected[0] in tables
            else None
        )
        protected = [*self.inputs.sources.values(), *provenance.get("sources", {}).values()]

        def write(logger: logging.Logger) -> tuple[str, str | None]:
            self.history.validate_export_destination(path, self.runs.runs)
            if companion is not None:
                self.history.validate_export_destination(companion, self.runs.runs)
            checksum = export_selection(
                path,
                results,
                self._owned_provenance(provenance, run)
                if run is not None or format_name == "JSON"
                else provenance,
                selected,
                format_name,
                protected_sources=protected,
            )
            if format_name == "JSON":
                checksum = validate_checksum(checksum)
            return str(Path(path).resolve()), checksum

        def completed(payload: tuple[str, str | None]) -> None:
            self._complete_selection_export(
                payload, run, format_name, selected, complete, companion
            )

        self.view.status.setText("Exporting results…")
        self.callbacks.start_job(write, completed)

    def _complete_selection_export(
        self,
        payload: tuple[str, str | None],
        run: RunRecord | None,
        format_name: OutputKind,
        selected: list[str],
        complete: bool,
        companion: Path | None,
    ) -> None:
        output_path, checksum = payload
        if run is not None:
            output: RunOutput = {
                "kind": format_name,
                "path": output_path,
                "saved": now(),
                "selected": selected,
                "complete": complete,
            }
            if checksum is not None:
                output["sha256"] = checksum
            if companion is not None:
                output["metadata_path"] = str(companion.resolve())
            run["outputs"].append(output)
            self.callbacks.persist_run(run)
            self.callbacks.refresh_runs()
        self.view.status.setText(
            f"Results exported to {output_path}"
            + (f" (metadata: {companion.name})" if companion is not None else "")
        )

    @staticmethod
    def _owned_provenance(provenance: Provenance, run: RunRecord | None) -> Provenance:
        if run is not None:
            return provenance_for_record(provenance, run)
        return provenance_for_run(provenance, validate_run_id(provenance.get("run_id")))

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
                companion = csv_metadata_path(path)
                self.history.validate_export_destination(companion, self.runs.runs)
                provenance = self.results.provenance
                if self.runs.current_run is not None:
                    provenance = self._owned_provenance(provenance, self.runs.current_run)
                self.services.export_table_csv(
                    path,
                    frame,
                    source=self.results.provenance.get("source", self.inputs.source),
                    protected_sources=[
                        *self.inputs.sources.values(),
                        *self.results.provenance.get("sources", {}).values(),
                    ],
                    provenance=provenance,
                )
                self.callbacks.record_output(path, "CSV", metadata_path=companion)
                self.view.status.setText(
                    f"{len(frame):,} rows from {name} exported to {path} (metadata: {companion.name})"
                )
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
