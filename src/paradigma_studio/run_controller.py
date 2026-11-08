"""Run history, lifecycle and persistence through explicit view/workflow ports."""

from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Callable, Iterable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import get_ident
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QMessageBox

from .contracts import (
    AnalysisError,
    AnalysisResults,
    AnalysisSettings,
    NoticeCallback,
    Provenance,
    RunOutput,
    RunStatus,
    SensorInput,
    StartJobCallback,
)
from .error_reporting import append_error
from .history import (
    RunHistory,
    merge_errors,
    now,
    run_exports,
    run_is_saved,
    run_status,
    saved_result_output,
)
from .provenance import provenance_for_record, run_provenance
from .result_integrity import provenance_for_run, validate_checksum
from .result_preparation import PreparedResults
from .result_reopening import load_saved_results
from .run_lifecycle import analysis_record, close_loading, new_loading_run
from .theme import STYLESHEET, light_palette
from .ui.runs_model import RunsModel
from .widgets import FrameModel
from .workspace_state import InputState, ResultState, RunState

if TYPE_CHECKING:
    import pandas as pd
    from PySide6.QtCore import QModelIndex
    from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton, QTabWidget, QWidget

    from .contracts import OutputKind, PathInput, RunOutput, RunRecord
    from .widgets import ReadableTable


SaveProblem: TypeAlias = tuple[str, int, str, str]
SaveOutcome: TypeAlias = tuple[
    list[tuple[str, list[RunOutput]]], list[tuple[str, str, str]], list[SaveProblem]
]


class _SaveProblems(logging.Handler):
    """Retain each bulk-save problem with the run currently being written."""

    def __init__(self, run_id: str, problems: list[tuple[str, int, str, str]]) -> None:
        super().__init__(logging.WARNING)
        self.run_id, self.problems, self.thread_id = run_id, problems, get_ident()

    def emit(self, event: logging.LogRecord) -> None:
        if event.thread == self.thread_id:
            self.problems.append(
                (self.run_id, event.levelno, event.getMessage(), self.format(event))
            )


def _phase_duration(start: str | None, finish: str | None) -> str | None:
    if not start or not finish:
        return None
    seconds = (
        datetime.fromisoformat(finish).astimezone(UTC)
        - datetime.fromisoformat(start).astimezone(UTC)
    ).total_seconds()
    if seconds < 0:
        return None
    remaining = int(seconds)
    parts = []
    for size, unit in ((86400, "d"), (3600, "h"), (60, "min"), (1, "s")):
        value, remaining = divmod(remaining, size)
        if value:
            parts.append(f"{value} {unit}")
    return " ".join(parts) or "0 s"


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
    run_detail_tabs: QTabWidget
    run_saved: QPlainTextEdit
    run_outputs: QPlainTextEdit
    open_run_button: QPushButton
    use_parameters_button: QPushButton
    delete_run_button: QPushButton
    clear_runs_button: QPushButton


@dataclass(frozen=True)
class RunCallbacks:
    navigate: Callable[[int], None]
    show_notice: NoticeCallback
    clear_results: Callable[[], None]
    start_job: StartJobCallback
    prepare_results: Callable[[AnalysisResults, Provenance, SensorInput | None], PreparedResults]
    install_prepared: Callable[[PreparedResults], None]
    selected_export_table: Callable[[], tuple[str, pd.DataFrame | None]]
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
    ) -> None:
        self.state, self.results, self.inputs = state, results, inputs
        self.history, self.view, self.callbacks, self.parent = history, view, callbacks, parent
        self._preview_persistence: set[str] = set()

    def error_messages(self, run_id: str) -> list[str] | None:
        record = next((record for record in self.state.runs if record["id"] == run_id), None)
        return list(record["errors"]) if record is not None else None

    def show_errors(self, run_id: str) -> None:
        self.show_run(run_id, errors=True)

    def show_run(self, run_id: str, *, errors: bool = False) -> None:
        if self.error_messages(run_id) is None:
            self.callbacks.show_notice("This run is no longer available in Runs.")
            return
        self.refresh_runs()
        row = next(
            i for i, record in enumerate(self.state._run_row_records) if record["id"] == run_id
        )
        self.view.run_table.selectionModel().setCurrentIndex(
            self.view.run_table.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        if errors:
            self.view.run_detail_tabs.setCurrentWidget(self.view.run_errors)
        self.callbacks.navigate(3)

    def append_log(self, message: str, *, owner: RunRecord | None = None) -> None:
        record = owner or self.state.active_run
        if record is not None:
            record["log"] += message + "\n"
            record["_history_dirty"] = True
            if self.state.selected_run is record:
                self.view.log.appendPlainText(message)
        elif self.state.selected_run is None:
            self.view.log.appendPlainText(message)

    def capture_warning(self, message: str, *, owner: RunRecord | None = None) -> None:
        record = owner or self.state.active_run
        if record is not None and message not in record["warnings"]:
            record["warnings"].append(message)
            record["_history_dirty"] = True
            self.update_run_problems(record)

    def capture_error(self, message: str, *, owner: RunRecord | None = None) -> None:
        record = owner or self.state.active_run
        if record is not None and message not in record["errors"]:
            errors = append_error(record["errors"], message)
            if errors != record["errors"]:
                record["errors"] = errors
                record["_history_dirty"] = True
                self.update_run_problems(record)

    def update_run_problems(self, record: RunRecord | None = None) -> None:
        record = record or self.state.active_run
        if record is None:
            return
        if self.state.selected_run is record:
            self.view.run_warnings.setPlainText(
                "\n\n".join(record["warnings"]) or "No recorded warnings."
            )
            self.view.run_errors.setPlainText(
                "\n\n".join(record["errors"]) or "No recorded errors."
            )
            self.view.run_summary.setText(self.run_summary_text(record))
            suffix = self.view.run_heading.text().partition(" · ")[2]
            self.view.run_heading.setText(f"{run_status(record)} · {suffix}")
        model = cast("FrameModel | None", self.view.run_table.model())
        row = next((i for i, run in enumerate(self.state._run_row_records) if run is record), None)
        if model is not None and row is not None:
            for name in ("Status", "Warnings", "Errors"):
                column = model.frame.columns.get_loc(name)
                value = (
                    run_status(record)
                    if name == "Status"
                    else len(record["warnings"] if name == "Warnings" else record["errors"])
                )
                if model.frame.iat[row, column] == value:
                    continue
                model.frame.iat[row, column] = value
                index = model.index(row, column)
                model.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

    def persist_run(self, record: RunRecord) -> bool:
        try:
            self.history.save(record)
            record.pop("_history_dirty", None)
            return True
        except (OSError, ValueError, TypeError) as exc:
            self.callbacks.show_notice(f"Run history could not be saved: {exc}")
            return False

    def persist_diagnostics(self, record: RunRecord | None) -> None:
        if record is not None and record.get("_history_dirty"):
            self.persist_run(record)

    def finish_operation(self, owner: RunRecord | None) -> None:
        self.persist_diagnostics(owner)
        pending, self._preview_persistence = self._preview_persistence, set()
        for record in self.state.runs:
            if record is not owner and record["id"] in pending:
                self.persist_diagnostics(record)

    def input_installed(self) -> None:
        active = self.state.active_run
        self.inputs.load_run_id = (
            active["id"] if active is not None and active["status"] == "Loading" else None
        )
        self.inputs.loading = None

    def preview_context(self) -> RunRecord | None:
        return next(
            (record for record in self.state.runs if record["id"] == self.inputs.load_run_id), None
        )

    def preview_failure(
        self, context: object, message: str, diagnostic: str, current: bool
    ) -> None:
        owner = next((record for record in self.state.runs if record is context), None)
        if owner is not None:
            self.append_log(diagnostic, owner=owner)
            if current:
                self.capture_warning(f"Recording preview unavailable: {message}", owner=owner)
            if self.callbacks.is_busy():
                # A snapshot writer may still publish an earlier history copy.
                self._preview_persistence.add(owner["id"])
            else:
                self.persist_diagnostics(owner)
        else:
            logging.getLogger(__name__).warning("%s\n%s", message, diagnostic)
        if current:
            self.callbacks.show_notice(f"Recording preview unavailable: {message}")

    def start_loading(self, selections: list[str]) -> RunRecord:
        record = new_loading_run(selections)
        self.state.runs.insert(0, record)
        self.state.active_run = self.state.selected_run = record
        self.persist_run(record)
        self.refresh_runs()
        return record

    def prepare_loading(self, paths: list[PathInput]) -> RunRecord:
        selected = list(dict.fromkeys(map(str, paths)))
        record = self.state.active_run
        if record is None or record["status"] != "Loading":
            record = self.start_loading(selected)
        record["source"] = selected[0]
        record["sources"] = {
            f"recording_{index:03d}": path for index, path in enumerate(selected, 1)
        }
        self.persist_run(record)
        self.refresh_runs()
        return record

    def finish_loading(self) -> None:
        record = self.state.active_run
        if record is None or record["status"] != "Loading":
            self.inputs.load_run_id, self.inputs.loading = None, None
            return
        record["source"], record["sources"] = self.inputs.source, dict(self.inputs.sources)
        close_loading(record, now())
        record["status"] = "Loaded"
        self.inputs.load_run_id = record["id"]
        self.inputs.loading = deepcopy(record["loading"])
        self.persist_run(record)
        self.state.active_run = None
        self.refresh_runs()

    def begin_analysis(self, settings: AnalysisSettings) -> RunRecord:
        pending = next(
            (record for record in self.state.runs if record["id"] == self.inputs.load_run_id), None
        )
        record = analysis_record(pending, self.inputs.source, settings, self.inputs.loading)
        if not any(existing is record for existing in self.state.runs):
            self.state.runs.insert(0, record)
        return record

    def finish_run(self, status: RunStatus, errors: Iterable[AnalysisError] = ()) -> None:
        if self.state.active_run is None:
            return
        record = self.state.active_run
        record["status"], record["finished"] = status, now()
        record["errors"] = merge_errors(record["errors"], errors)
        if "loading" in record and "analysis_started" not in record:
            close_loading(record, cast(str, record["finished"]))
        if record["errors"] and status == "Completed":
            record["status"] = "Partial"
        self.persist_run(record)
        self.state.active_run = None
        self.refresh_runs()

    def refresh_runs(self) -> None:
        selected_ids = {record["id"] for record in self.selected_run_records()}
        if self.state.selected_run is not None and not any(
            record is self.state.selected_run for record in self.state._run_row_records
        ):
            selected_ids = {self.state.selected_run["id"]}
        self._install_run_model()
        if self.state.runs:
            self._restore_run_selection(selected_ids)
        else:
            self.state.selected_run = None
        self.update_run_actions()

    @staticmethod
    def _run_row(record: RunRecord) -> dict[str, Any]:
        return {
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

    def _install_run_model(self) -> None:
        model = RunsModel(
            [self._run_row(record) for record in self.state.runs],
            [record["id"] for record in self.state.runs],
            self.results.provenance.get("run_id") if self.results.results is not None else None,
        )
        self.state._run_row_records = tuple(self.state.runs)
        self.view.run_table.setModel(model)
        self.view.run_table.setColumnWidth(0, max(196, self.view.run_table.sizeHintForColumn(0)))
        self.view.run_table.setColumnWidth(2, 170)
        self.view.run_table.selectionModel().currentRowChanged.connect(self.callbacks.select_run)
        self.view.run_table.selectionModel().selectionChanged.connect(
            self.callbacks.update_run_actions
        )

    def update_displayed_run(self) -> None:
        model = self.view.run_table.model()
        if isinstance(model, RunsModel):
            model.set_displayed_run(
                self.results.provenance.get("run_id") if self.results.results is not None else None
            )

    def _restore_run_selection(self, selected_ids: set[str]) -> None:
        index = next(
            (i for i, record in enumerate(self.state.runs) if record is self.state.selected_run),
            0,
        )
        selection = self.view.run_table.selectionModel()
        selection.blockSignals(True)
        selection.setCurrentIndex(
            self.view.run_table.model().index(index, 0), QItemSelectionModel.SelectionFlag.NoUpdate
        )
        rows = [i for i, record in enumerate(self.state.runs) if record["id"] in selected_ids] or [
            index
        ]
        for row in rows:
            selection.select(
                self.view.run_table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
        selection.blockSignals(False)
        self.select_run(selection.currentIndex(), None)

    def select_run(self, current: QModelIndex, previous: QModelIndex | None) -> None:
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
            "\n".join(record.get("sources", {}).values())
            or "\n".join(record.get("loading", {}).get("selections", []))
            or record["source"]
        )
        self.view.run_details.setPlainText(
            "\n".join(
                f"{key.replace('_', ' ').capitalize()}: {json.dumps(value, ensure_ascii=False)}"
                for key, value in record["settings"].items()
            )
            or "Analysis has not started. Parameters are recorded when Run Analysis starts."
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
                + (f"\nMetadata: {item['metadata_path']}" if "metadata_path" in item else "")
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
    def run_summary_text(record: RunRecord) -> str:
        warnings, errors = len(record["warnings"]), len(record.get("errors", []))
        parts = [
            f"Studio {record['studio_version']}",
            f"ParaDigMa {record['paradigma_version']}",
            f"{warnings} warning{'' if warnings == 1 else 's'}, {errors} error{'' if errors == 1 else 's'}",
        ]
        loading = record.get("loading", {})
        loaded = _phase_duration(loading.get("started"), loading.get("finished"))
        if loaded is not None:
            parts.append(f"Loading {loaded}")
        began = record.get("analysis_started") or (record["started"] if not loading else None)
        analyzed = _phase_duration(began, record.get("finished"))
        if analyzed is not None:
            parts.append(f"Analysis {analyzed}")
        return " · ".join(parts)

    def selected_run_records(self) -> list[RunRecord]:
        selection = self.view.run_table.selectionModel()
        rows = selection.selectedRows() if selection is not None else []
        records = self.state._run_row_records
        return [
            records[index.row()]
            for index in sorted(rows, key=lambda index: index.row())
            if index.row() < len(records)
        ]

    def update_run_actions(self, *_: object) -> None:
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
            record is not None
            and bool(record["settings"])
            and count == 1
            and not self.callbacks.is_busy()
        )
        self.view.delete_run_button.setEnabled(count > 0 and not self.callbacks.is_busy())
        self.view.delete_run_button.setText(f"Delete {count} Runs…" if count > 1 else "Delete Run…")
        self.view.clear_runs_button.setEnabled(
            bool(self.state.runs) and not self.callbacks.is_busy()
        )

    def delete_run(self) -> None:
        return self.delete_runs(self.selected_run_records())

    def clear_runs(self) -> None:
        return self.delete_runs(list(self.state.runs), clear_all=True)

    def delete_runs(self, records: list[RunRecord], *, clear_all: bool = False) -> None:
        """Confirm once, delete safely, and retain state after partial failures."""
        if (
            not records
            or self.callbacks.is_busy()
            or any(record is self.state.active_run for record in records)
        ):
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

    def _confirm_deletion(
        self, records: Sequence[RunRecord], files: Sequence[Path], *, clear_all: bool
    ) -> bool:
        warning = QMessageBox(self.parent)
        warning.setPalette(light_palette())
        warning.setStyleSheet(STYLESHEET)
        warning.setIcon(QMessageBox.Icon.Warning)
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
        warning.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        warning.setDefaultButton(QMessageBox.StandardButton.Cancel)
        warning.button(QMessageBox.StandardButton.Yes).setText(
            "Delete all runs" if clear_all else "Delete runs" if len(records) > 1 else "Delete run"
        )
        return warning.exec() == QMessageBox.StandardButton.Yes

    def _forget_deleted_runs(self, removed: Sequence[str]) -> None:
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

    def open_run(self) -> None:
        record = self.state.selected_run
        if record is None or self.callbacks.is_busy():
            return
        cached = record.get("_results")
        output = None if cached is not None else self.reopen_output(record)
        if cached is None and output is None:
            return
        run_id, source_frame = record["id"], record.get("_frame")
        provenance = dict(record.get("_provenance") or self._run_provenance(record))
        self.view.status.setText("Opening saved results…")

        def read(logger: logging.Logger) -> tuple[str, PreparedResults]:
            values, origin = cached, provenance
            if values is None:
                origin, values = load_saved_results(
                    cast("RunOutput", output)["path"],
                    logger,
                    run_id=run_id,
                    checksum=cast("RunOutput", output).get("sha256"),
                )
            else:
                origin = provenance_for_run(origin, run_id)
            return run_id, self.callbacks.prepare_results(values, origin, source_frame)

        self.callbacks.start_job(
            read, self._restore_prepared_run, owner=record, context="Open results"
        )

    @staticmethod
    def _run_provenance(record: RunRecord) -> Provenance:
        return run_provenance(record)

    def _restore_prepared_run(self, payload: tuple[str, PreparedResults]) -> None:
        run_id, prepared = payload
        self._restore_record(run_id, prepared.provenance, prepared.results)
        self.callbacks.install_prepared(prepared)
        self.update_run_actions()

    @staticmethod
    def reopen_output(record: RunRecord) -> RunOutput | None:
        if run_is_saved(record):
            return saved_result_output(record)
        # Complete exports are candidates; the reader checks identity and hash.
        return next(
            (
                output
                for output in reversed(run_exports(record))
                if output.get("kind") == "JSON" and output.get("complete") is True
            ),
            None,
        )

    def restore_run(self, payload: tuple[str, Provenance, AnalysisResults]) -> None:
        run_id, provenance, results = payload
        self._restore_record(run_id, provenance, results)
        self.callbacks.install_prepared(
            self.callbacks.prepare_results(
                results, self.results.provenance, self.results.result_source_frame
            )
        )
        self.update_run_actions()

    def _restore_record(
        self, run_id: str, provenance: Provenance, results: AnalysisResults
    ) -> None:
        record = next(record for record in self.state.runs if record["id"] == run_id)
        provenance = provenance_for_record(provenance or self._run_provenance(record), record)
        self.state.current_run = record
        self.results.provenance = provenance
        self.results.result_source_frame = record.get("_frame")
        self.results.result_timeline = None
        record["_results"], record["_provenance"] = results, self.results.provenance
        record.setdefault("_unsaved_results", not run_is_saved(record))
        self.callbacks.show_notice("")

    def record_output(
        self,
        path: PathInput,
        kind: OutputKind,
        *,
        checksum: str | None = None,
        metadata_path: PathInput | None = None,
    ) -> None:
        if self.state.current_run is not None:
            if kind == "JSON":
                validate_checksum(checksum)
            name, frame = self.callbacks.selected_export_table()
            self.state.current_run["outputs"].append(
                {
                    "kind": kind,
                    "path": str(Path(path).resolve()),
                    "saved": now(),
                    "dataset": name if kind == "CSV" else "all results",
                    "complete": kind == "JSON",
                }
            )
            if kind == "JSON":
                self.state.current_run["outputs"][-1].update(
                    {"sha256": validate_checksum(checksum), "complete": True}
                )
            if kind == "CSV":
                if metadata_path is not None:
                    self.state.current_run["outputs"][-1]["metadata_path"] = str(
                        Path(metadata_path).resolve()
                    )
                aggregation = name.startswith("aggregations/")
                self.state.current_run["outputs"][-1].update(
                    {
                        "selected_rows": len(cast("pd.DataFrame", frame)),
                        "selection": {"scope": "Full run"}
                        if aggregation
                        else self.results.active_selection,
                    }
                )
            self.persist_run(self.state.current_run)
            self.refresh_runs()

    def _capture_save_problems(
        self, records: Sequence[RunRecord], problems: Sequence[SaveProblem]
    ) -> None:
        # Single-run diagnostics already arrive through the owned worker signals.
        if len(records) == 1:
            return
        for run_id, level, message, diagnostic in problems:
            record = next(record for record in self.state.runs if record["id"] == run_id)
            self.append_log(diagnostic, owner=record)
            capture = self.capture_error if level >= logging.ERROR else self.capture_warning
            capture(f"Save results: {message}", owner=record)
            self.persist_diagnostics(record)

    def save_run_results(self, records: list[RunRecord], *, close_after: bool = False) -> None:
        if self.callbacks.is_busy() or not records:
            return
        snapshots = [
            (record.copy(), record["_results"], dict(record["_provenance"])) for record in records
        ]
        protected = [self.inputs.source, *self.inputs.sources.values()]
        self.state._close_after_save = close_after

        def write(logger: logging.Logger) -> SaveOutcome:
            saved: list[tuple[str, list[RunOutput]]] = []
            failures: list[tuple[str, str, str]] = []
            problems: list[SaveProblem] = []
            for record, results, provenance in snapshots:
                handler = _SaveProblems(record["id"], problems)
                package_logger = logging.getLogger("paradigma")
                package_logger.addHandler(handler)
                try:
                    outputs = self.history.save_results(record, results, provenance, protected)
                    saved.append((record["id"], outputs))
                except Exception as exc:  # noqa: BLE001 -- Route independent save failures on the GUI.
                    # Continue saving independent runs, including serialization failures.
                    failures.append(
                        (
                            record["id"],
                            f"{Path(record['source']).name}: {exc}",
                            traceback.format_exc(),
                        )
                    )
                finally:
                    package_logger.removeHandler(handler)
                    handler.close()
            return saved, failures, problems

        def completed(payload: SaveOutcome) -> None:
            saved, failures, problems = payload
            for run_id, outputs in saved:
                record = next(record for record in self.state.runs if record["id"] == run_id)
                record["outputs"] = outputs
                record["_unsaved_results"] = False
            self._capture_save_problems(records, problems)
            messages = []
            for run_id, message, diagnostic in failures:
                record = next(record for record in self.state.runs if record["id"] == run_id)
                self.append_log(diagnostic, owner=record)
                self.capture_error(f"Save results: {message}", owner=record)
                self.persist_diagnostics(record)
                messages.append(message)
            self.refresh_runs()
            if failures:
                self.state._close_after_save = False
                self.callbacks.show_notice(
                    "Results could not be saved: " + "; ".join(messages), "error"
                )
                self.view.status.setText(
                    "Some results remain unsaved. Keep the app open and try again."
                )
            else:
                self.view.status.setText("Results saved locally. Reopen them from Runs.")
                self.callbacks.show_notice("")

        self.view.status.setText("Saving results…")
        self.callbacks.start_job(
            write,
            completed,
            owner=records[0] if len(records) == 1 else None,
            context="Save results",
        )
