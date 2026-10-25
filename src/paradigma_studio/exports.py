"""Selective native-result exports and a single export chooser."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, BinaryIO, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .contracts import AnalysisResults, PathInput, Provenance
from .results_view import aggregation_tables, detail_tables, output_label, readable_key
from .serialization import (
    _spreadsheet_text,
    _write_export,
    export_results,
    export_table_csv,
    json_value,
)
from .widgets import ReadableComboBox

if TYPE_CHECKING:
    import pandas as pd


def export_items(results: AnalysisResults) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    tables = {**detail_tables(results), **aggregation_tables(results)}
    metadata = {f"metadata/{key}": value for key, value in results.get("metadata", {}).items()}
    if results.get("errors"):
        metadata["errors"] = results["errors"]
    return tables, metadata


def selected_results(results: AnalysisResults, selected: Iterable[str]) -> AnalysisResults:
    output: AnalysisResults = {
        key: {} for key in ("classifications", "quantifications", "aggregations", "metadata")
    }
    output["errors"] = []
    for name in selected:
        parts = name.split("/")
        value = results
        for part in parts:
            value = value[part]
        target = output
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return output


def export_selection(
    path: PathInput,
    results: AnalysisResults,
    provenance: Provenance,
    selected: Iterable[str],
    format: str,
    *,
    protected_sources: Iterable[PathInput] = (),
) -> str | None:
    tables, metadata = export_items(results)
    selected = list(dict.fromkeys(selected))
    if not selected or any(name not in tables and name not in metadata for name in selected):
        raise ValueError("Select at least one available table or metadata group.")
    if format == "JSON":
        return export_results(
            path,
            selected_results(results, selected),
            provenance,
            protected_sources=protected_sources,
        )
    elif format == "CSV" and len(selected) == 1 and selected[0] in tables:
        export_table_csv(
            path,
            tables[selected[0]],
            source=provenance.get("source"),
            protected_sources=protected_sources,
            provenance=provenance,
        )
    elif format == "CSV":

        def write(stream: BinaryIO) -> None:
            with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
                for index, name in enumerate(selected):
                    if name not in tables:
                        continue
                    frame = tables[name].map(_spreadsheet_text)
                    frame.columns = [_spreadsheet_text(str(column)) for column in frame.columns]
                    filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", name)
                    archive.writestr(
                        f"{index + 1:03d}_{filename}.csv",
                        frame.to_csv(index=False, quoting=csv.QUOTE_ALL),
                    )
                chosen_metadata = {name: metadata[name] for name in selected if name in metadata}
                if chosen_metadata:
                    archive.writestr(
                        "metadata.json",
                        json.dumps(json_value(chosen_metadata), indent=2, allow_nan=False),
                    )
                archive.writestr(
                    "analysis.json", json.dumps(json_value(provenance), indent=2, allow_nan=False)
                )

        _write_export(
            path,
            write,
            source=provenance.get("source"),
            protected_sources=protected_sources,
            binary=True,
        )
    else:
        raise ValueError("Choose JSON or CSV.")
    return None


class ExportDialog(QDialog):
    def __init__(self, results: AnalysisResults, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export results")
        self.resize(580, 570)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        row = QHBoxLayout()
        row.addWidget(QLabel("Format"))
        self.format = ReadableComboBox()
        self.format.addItems(["JSON", "CSV"])
        self.format.setAccessibleName("Export format")
        row.addWidget(self.format, 1)
        layout.addLayout(row)
        self.items = QTreeWidget()
        self.items.setHeaderLabel("Tables and metadata")
        self.leaves: dict[str, QTreeWidgetItem] = {}
        roots = {}
        tables, metadata = export_items(results)
        for name in [*tables, *metadata]:
            stage = name.split("/")[0]
            if stage not in roots:
                root = QTreeWidgetItem(self.items, [readable_key(stage)])
                root.setFlags(
                    root.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate
                )
                root.setExpanded(True)
                roots[stage] = root
            metadata_titles = {
                "desktop_recordings": "Recording sources",
                "desktop_preparation": "Input preparation",
                "desktop_availability": "Prepared-input availability",
                "errors": "Processing errors",
            }
            key = name.split("/")[-1]
            title = (
                output_label(name)
                if name in tables
                else metadata_titles.get(key, readable_key(key))
            )
            item = QTreeWidgetItem(roots[stage], [title])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            self.leaves[name] = item
        layout.addWidget(self.items, 1)
        selection = QHBoxLayout()
        for text, state in (
            ("Select all", Qt.CheckState.Checked),
            ("Clear selection", Qt.CheckState.Unchecked),
        ):
            control = QPushButton(text)
            control.clicked.connect(lambda checked=False, value=state: self.set_selection(value))
            selection.addWidget(control)
        selection.addStretch()
        layout.addLayout(selection)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Export…")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.format.currentTextChanged.connect(self.update_choice)
        self.items.itemChanged.connect(self.update_choice)
        self._tables = tables
        self.update_choice()

    def selected(self) -> list[str]:
        return [
            name
            for name, item in self.leaves.items()
            if item.checkState(0) == Qt.CheckState.Checked
        ]

    def set_selection(self, state: Qt.CheckState) -> None:
        for item in self.leaves.values():
            item.setCheckState(0, state)

    def extension(self) -> Literal["json", "csv", "zip"]:
        selected = self.selected()
        return (
            "json"
            if self.format.currentText() == "JSON"
            else "csv"
            if len(selected) == 1 and selected[0] in self._tables
            else "zip"
        )

    def update_choice(self, *_: object) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(bool(self.selected()))
        self.note.setText(
            "Selected outputs and analysis parameters in one JSON file."
            if self.extension() == "json"
            else "One CSV file with the original output columns."
            if self.extension() == "csv"
            else "A ZIP containing separate CSV tables, selected metadata and analysis parameters as JSON."
        )
