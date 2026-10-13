"""Run history, lifecycle and persistence through explicit view/workflow ports."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QMessageBox

from .history import (
    RunHistory,
    load_result_export,
    merge_errors,
    now,
    run_exports,
    run_is_saved,
    run_status,
    saved_result_output,
)
from .theme import STYLESHEET, light_palette
from .widgets import RecordModel
from .workspace_state import InputState, ResultState, RunState

if TYPE_CHECKING:
    from PySide6.QtCore import QModelIndex
    from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton, QWidget

    from .widgets import ReadableTable


@dataclass(frozen=True)
class RunView:
    status: QLabel
    log: QPlainTextEdit
    run_table: ReadableTable
    run_heading: QLabel
    run_summary: QLabel
    run_details: QPlainTextEdit
    run_recordings: QPlainTextEdit
    run_warnings: QPlainTextEdit
    run_errors: QPlainTextEdit
    run_saved: QPlainTextEdit
    run_outputs: QPlainTextEdit
    open_run_button: QPushButton
    use_parameters_button: QPushButton
    delete_run_button: QPushButton
    clear_runs_button: QPushButton


@dataclass(frozen=True)
class RunCallbacks:
    show_notice: Callable[..., None]
    clear_results: Callable[[], None]
    start_job: Callable[..., None]
    analyzed: Callable[[dict], None]
    selected_export_table: Callable[[], tuple[str, Any]]
    is_busy: Callable[[], bool]
    select_run: Callable[[QModelIndex, QModelIndex | None], None]
    update_run_actions: Callable[..., None]


class RunController:
    def __init__(
        self,
        state: RunState,
        results: ResultState,
        inputs: InputState,
        history: RunHistory,
        view: RunView,
        callbacks: RunCallbacks,
        *,
        parent: QWidget | None,
    ):
        self.state, self.results, self.inputs = state, results, inputs
        self.history, self.view, self.callbacks, self.parent = history, view, callbacks, parent

    def append_log(self, message):
        if self.state.active_run is not None:
            self.state.active_run["log"] += message + "\n"
            if self.state.selected_run is self.state.active_run:
                self.view.log.appendPlainText(message)
        elif self.state.selected_run is None:
            self.view.log.appendPlainText(message)

    def capture_warning(self, message):
        if self.state.active_run is not None and message not in self.state.active_run["warnings"]:
            self.state.active_run["warnings"].append(message)
            self.update_run_problems()

    def capture_error(self, message):
        if self.state.active_run is not None and message not in self.state.active_run["errors"]:
            self.state.active_run["errors"].append(message)
            self.update_run_problems()

    def update_run_problems(self):
        record = self.state.active_run
        if self.state.selected_run is record:
            self.view.run_warnings.setPlainText(
                "\n\n".join(record["warnings"]) or "No recorded warnings."
            )
            self.view.run_errors.setPlainText(
                "\n\n".join(record["errors"]) or "No recorded errors."
            )
            self.view.run_summary.setText(self.run_summary_text(record))
        model = self.view.run_table.model()
        row = next((i for i, run in enumerate(self.state.runs) if run is record), None)
        if model is not None and row is not None:
            for name in ("Warnings", "Errors"):
                column = model.frame.columns.get_loc(name)
                model.frame.iat[row, column] = len(record[name.lower()])
                index = model.index(row, column)
                model.dataChanged.emit(index, index, [Qt.DisplayRole])

    def persist_run(self, record):
        try:
            self.history.save(record)
            return True
        except (OSError, ValueError, TypeError) as exc:
            self.callbacks.show_notice(
                f"Analysis remains available, but run history could not be saved: {exc}"
            )
            return False

    def finish_run(self, status, errors=()):
        if self.state.active_run is None:
            return
        record = self.state.active_run
        record["status"], record["finished"] = status, now()
        record["errors"] = merge_errors(record["errors"], errors)
        if record["errors"] and status == "Completed":
            record["status"] = "Partial"
        self.persist_run(record)
        self.state.active_run = None
        self.refresh_runs()

    def refresh_runs(self):
        selected_ids = {record["id"] for record in self.selected_run_records()}
        if self.state.selected_run is not None and not any(
            record is self.state.selected_run for record in self.state._run_row_records
        ):
            selected_ids = {self.state.selected_run["id"]}
        model = RecordModel(
            [
                {
                    "Started": datetime.fromisoformat(record["started"])
                    .astimezone()
                    .strftime("%d %b %Y · %H:%M"),
                    "Status": run_status(record),
                    "Input": (
                        f"{len(record['sources'])} recordings"
                        if len(record.get("sources", {})) > 1
                        else Path(record["source"]).name
                    ),
                    "Modules": ", ".join(record["settings"].get("pipelines", [])),
                    "Warnings": len(record["warnings"]),
                    "Errors": len(record.get("errors", [])),
                    "Saved": "Yes" if run_is_saved(record) else "No",
                    "Exports": len(run_exports(record)),
                }
                for record in self.state.runs
            ],
            columns=[
                "Started",
                "Status",
                "Input",
                "Modules",
                "Saved",
                "Warnings",
                "Errors",
                "Exports",
            ],
        )
        self.state._run_row_records = tuple(self.state.runs)
        self.view.run_table.setModel(model)
        self.view.run_table.setColumnWidth(0, 176)
        self.view.run_table.setColumnWidth(2, 170)
        self.view.run_table.selectionModel().currentRowChanged.connect(self.callbacks.select_run)
        self.view.run_table.selectionModel().selectionChanged.connect(
            self.callbacks.update_run_actions
        )
        if self.state.runs:
            index = next(
                (
                    i
                    for i, record in enumerate(self.state.runs)
                    if record is self.state.selected_run
                ),
                0,
            )
            selection = self.view.run_table.selectionModel()
            selection.blockSignals(True)
            selection.setCurrentIndex(
                self.view.run_table.model().index(index, 0), QItemSelectionModel.NoUpdate
            )
            rows = [
                i for i, record in enumerate(self.state.runs) if record["id"] in selected_ids
            ] or [index]
            for row in rows:
                selection.select(
                    self.view.run_table.model().index(row, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows,
                )
            selection.blockSignals(False)
            self.select_run(selection.currentIndex(), None)
        else:
            self.state.selected_run = None
        self.update_run_actions()

    def select_run(self, current, previous):
        if not current.isValid() or current.row() >= len(self.state.runs):
            return
        record = self.state.runs[current.row()]
        self.state.selected_run = record
        self.view.run_heading.setText(
            f"{run_status(record)} · "
            + (
                f"{len(record['sources'])} recordings"
                if len(record.get("sources", {})) > 1
                else Path(record["source"]).name
            )
        )
        self.view.run_heading.setToolTip(f"Run ID: {record['id']}")
        self.view.run_summary.setText(self.run_summary_text(record))
        self.view.run_recordings.setPlainText(
            "\n".join(record.get("sources", {}).values()) or record["source"]
        )
        self.view.run_details.setPlainText(
            "\n".join(
                f"{key.replace('_', ' ').capitalize()}: {json.dumps(value, ensure_ascii=False)}"
                for key, value in record["settings"].items()
            )
        )
        self.view.run_warnings.setPlainText(
            "\n\n".join(str(value) for value in record["warnings"]) or "No recorded warnings."
        )
        self.view.run_errors.setPlainText(
            "\n\n".join(record.get("errors", [])) or "No recorded errors."
        )
        self.view.run_outputs.setPlainText(
            "\n\n".join(
                f"{item.get('kind', 'Export')}: {item.get('path', '')}"
                for item in run_exports(record)
            )
            or "No exports."
        )
        saved = saved_result_output(record)
        self.view.run_saved.setPlainText(
            ("Saved locally" if run_is_saved(record) else "Saved file unavailable")
            + f"\n{saved['path']}"
            if saved is not None
            else "Not saved locally."
        )
        self.view.log.setPlainText(record.get("log", ""))
        self.update_run_actions()

    @staticmethod
    def run_summary_text(record):
        started = (
            datetime.fromisoformat(record["started"]).astimezone().strftime("%d %b %Y, %H:%M:%S")
        )
        finished = (
            datetime.fromisoformat(record["finished"]).astimezone().strftime("%H:%M:%S")
            if record.get("finished")
            else "—"
        )
        return (
            f"{started} – {finished} · ParaDigMa {record.get('paradigma_version', '—')} · "
            f"{len(record['warnings'])} warning(s), {len(record.get('errors', []))} error(s)"
        )

    def selected_run_records(self):
        selection = self.view.run_table.selectionModel()
        rows = selection.selectedRows() if selection is not None else []
        records = self.state._run_row_records
        return [
            records[index.row()]
            for index in sorted(rows, key=lambda index: index.row())
            if index.row() < len(records)
        ]

    def update_run_actions(self, *_):
        records = self.selected_run_records()
        count = len(records)
        current = self.view.run_table.currentIndex()
        desired = (
            records[0]
            if count == 1
            else (
                self.state._run_row_records[current.row()]
                if count > 1 and current.isValid()
                else None
            )
        )
        if desired is not None and self.state.selected_run is not desired:
            row = next(
                i for i, record in enumerate(self.state._run_row_records) if record is desired
            )
            self.select_run(self.view.run_table.model().index(row, 0), None)
            return
        record = self.state.selected_run
        output = self.reopen_output(record) if record is not None else None
        available = record is not None and ("_results" in record or output is not None)
        self.view.open_run_button.setText(
            "Open exported results"
            if record is not None
            and "_results" not in record
            and output is not None
            and not output.get("local")
            else "Open results"
        )
        self.view.open_run_button.setEnabled(
            bool(available) and count == 1 and not self.callbacks.is_busy()
        )
        self.view.use_parameters_button.setEnabled(
            record is not None and count == 1 and not self.callbacks.is_busy()
        )
        self.view.delete_run_button.setEnabled(count > 0 and not self.callbacks.is_busy())
        self.view.delete_run_button.setText(f"Delete {count} Runs…" if count > 1 else "Delete Run…")
        self.view.clear_runs_button.setEnabled(
            bool(self.state.runs) and not self.callbacks.is_busy()
        )

    def delete_runs(self, records, *, clear_all=False):
        """Confirm once, delete safely, and retain state after partial failures."""
        if not records or self.callbacks.is_busy():
            return
        original_runs = list(self.state.runs)
        protected = [
            self.inputs.source,
            *self.inputs.sources.values(),
            *self.results.provenance.get("sources", {}).values(),
        ]
        removed = []
        try:
            files = list(
                dict.fromkeys(
                    path
                    for record in records
                    for path in self.history.removal_files(
                        record, original_runs, protected, removing=records
                    )
                )
            )
            if not self._confirm_deletion(records, files, clear_all=clear_all):
                return
            for record in records:
                self.history.remove(record, original_runs, protected, removing=records)
                removed.append(record["id"])
            self.view.status.setText(f"{len(removed)} run(s) and associated exports deleted.")
        except (OSError, ValueError) as exc:
            self.callbacks.show_notice(
                f"Could not finish deleting runs ({len(removed)} deleted): {exc}", "error"
            )
        finally:
            if removed:
                self._forget_deleted_runs(removed)

    def _confirm_deletion(self, records, files, *, clear_all):
        warning = QMessageBox(self.parent)
        warning.setPalette(light_palette())
        warning.setStyleSheet(STYLESHEET)
        warning.setIcon(QMessageBox.Warning)
        warning.setWindowTitle(
            "Clear all runs" if clear_all else "Delete runs" if len(records) > 1 else "Delete run"
        )
        warning.setText(
            "Delete all runs and their associated exports?"
            if clear_all
            else f"Delete these {len(records)} runs and their associated exports?"
            if len(records) > 1
            else "Delete this run and its associated exports?"
        )
        warning.setInformativeText(
            f"{len(records)} history entry/entries and {len(files)} export file(s) will be permanently deleted. "
            "Original sensor files and exports referenced by runs you keep are preserved."
        )
        warning.setDetailedText(
            "\n".join(str(path) for path in files) or "No associated export files exist."
        )
        warning.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        warning.setDefaultButton(QMessageBox.Cancel)
        warning.button(QMessageBox.Yes).setText(
            "Delete all runs" if clear_all else "Delete runs" if len(records) > 1 else "Delete run"
        )
        return warning.exec() == QMessageBox.Yes

    def _forget_deleted_runs(self, removed):
        self.state.runs[:] = [record for record in self.state.runs if record["id"] not in removed]
        if self.state.selected_run is not None and self.state.selected_run["id"] in removed:
            self.state.selected_run = None
        if self.state.current_run is not None and self.state.current_run["id"] in removed:
            self.state.current_run = None
            self.results.provenance = {}
            self.results.result_source_frame = self.results.result_timeline = None
            self.callbacks.clear_results()
        self.refresh_runs()
        if not self.state.runs:
            self.view.run_heading.setText("Select a run")
            self.view.run_summary.clear()
            for view in (
                self.view.run_details,
                self.view.run_recordings,
                self.view.run_warnings,
                self.view.run_errors,
                self.view.run_saved,
                self.view.run_outputs,
                self.view.log,
            ):
                view.clear()

    def open_run(self):
        record = self.state.selected_run
        if record is None or self.callbacks.is_busy():
            return
        if "_results" in record:
            self.restore_run((record["id"], record.get("_provenance", {}), record["_results"]))
            return
        output = self.reopen_output(record)
        if output:
            self.view.status.setText("Opening exported results…")
            self.callbacks.start_job(
                lambda logger: (record["id"], *load_result_export(output["path"])), self.restore_run
            )

    @staticmethod
    def reopen_output(record):
        if run_is_saved(record):
            return saved_result_output(record)
        # Keep reopening complete legacy exports possible, but distinguish them
        # from local saves and never treat a known partial export as a full run.
        return next(
            (
                output
                for output in reversed(run_exports(record))
                if output.get("kind") == "JSON" and output.get("complete") is not False
            ),
            None,
        )

    def restore_run(self, payload):
        run_id, provenance, results = payload
        record = next(record for record in self.state.runs if record["id"] == run_id)
        self.state.current_run = record
        self.results.provenance = provenance or {
            "source": record["source"],
            "settings": record["settings"],
            "paradigma_version": record["paradigma_version"],
            "sources": record.get("sources", {}),
        }
        self.results.result_source_frame = record.get("_frame")
        self.results.result_timeline = None
        record["_results"], record["_provenance"] = results, self.results.provenance
        record.setdefault("_unsaved_results", not run_is_saved(record))
        self.callbacks.show_notice("")
        self.callbacks.analyzed(results)
        self.update_run_actions()

    def record_output(self, path, kind):
        if self.state.current_run is not None:
            name, frame = self.callbacks.selected_export_table()
            self.state.current_run["outputs"].append(
                {
                    "kind": kind,
                    "path": str(Path(path).resolve()),
                    "saved": now(),
                    "dataset": name if kind == "CSV" else "all results",
                }
            )
            if kind == "CSV":
                aggregation = name.startswith("aggregations/")
                self.state.current_run["outputs"][-1].update(
                    selected_rows=len(frame),
                    selection={"scope": "Full run"}
                    if aggregation
                    else self.results.active_selection,
                )
            self.persist_run(self.state.current_run)
            self.refresh_runs()

    def save_run_results(self, records, *, close_after=False):
        if self.callbacks.is_busy() or not records:
            return
        snapshots = [
            (dict(record), record["_results"], dict(record["_provenance"])) for record in records
        ]
        protected = [self.inputs.source, *self.inputs.sources.values()]
        self.state._close_after_save = close_after

        def write(logger):
            saved, failures = [], []
            for record, results, provenance in snapshots:
                try:
                    outputs = self.history.save_results(record, results, provenance, protected)
                    saved.append((record["id"], outputs))
                except Exception as exc:
                    failures.append(f"{Path(record['source']).name}: {exc}")
            return saved, failures

        def completed(payload):
            saved, failures = payload
            for run_id, outputs in saved:
                record = next(record for record in self.state.runs if record["id"] == run_id)
                record["outputs"] = outputs
                record["_unsaved_results"] = False
            self.refresh_runs()
            if failures:
                self.state._close_after_save = False
                self.callbacks.show_notice(
                    "Results could not be saved: " + "; ".join(failures), "error"
                )
                self.view.status.setText(
                    "Some results remain unsaved. Keep the app open and try again."
                )
            else:
                self.view.status.setText("Results saved locally. Reopen them from Runs.")
                self.callbacks.show_notice("")

        self.view.status.setText("Saving results…")
        self.callbacks.start_job(write, completed)
