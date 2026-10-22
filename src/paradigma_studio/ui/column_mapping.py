"""Signal-column dropdowns with a header-only mapping model and one change signal."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..axis_mapping import IMU_COLUMNS
from ..column_mapping import SIGNALS, ColumnMapping, required_signals
from ..theme import light_palette, tooltip_text
from ..widgets import button, combo, label


class _CellControls(QStyledItemDelegate):
    """Give embedded controls the whole cell; their layouts own the padding."""

    def updateEditorGeometry(
        self,
        editor: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        editor.setGeometry(option.rect)


class ColumnMappingEditor(QWidget):
    """Own only mapping controls; controllers supply schemas and selected modules."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = ColumnMapping()
        self._modules = ["gait"]
        self._expanded = False
        self._combos: dict[str, QComboBox] = {}
        self._labels: dict[str, QTableWidgetItem] = {}
        self._warnings: dict[str, QToolButton] = {}
        self._inversions: dict[str, QCheckBox] = {}
        self._fitting_table = False
        content = QVBoxLayout(self)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(6)
        self._build_table()
        content.addWidget(self.table)
        self.summary = label("Open recordings to select signal columns.", "muted")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        content.addWidget(self.summary)
        actions = self._build_actions()
        content.addLayout(actions)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.hide()
        content.addWidget(self.details)
        self._refresh()

    def _build_table(self) -> None:
        self.table = QTableWidget(len(SIGNALS), 3)
        self.table.setHorizontalHeaderLabels(["Signal", "Column in your files", "Invert axis"])
        self.table.verticalHeader().hide()
        self.table.setPalette(light_palette())
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header = self.table.horizontalHeader()
        for column in (0, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        delegate = _CellControls(self.table)
        for column in (1, 2):
            self.table.setItemDelegateForColumn(column, delegate)
        for row, (target, title) in enumerate(SIGNALS.items()):
            self._labels[target] = QTableWidgetItem(title)
            self.table.setItem(row, 0, self._labels[target])
            source = combo()
            source.setMinimumWidth(80)
            source.setMinimumContentsLength(8)
            source.setPlaceholderText("Select a column…")
            source.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            source.setAccessibleName(f"Column for {title}")
            source.currentIndexChanged.connect(lambda _index, target=target: self._choose(target))
            self._combos[target] = source
            self.table.setCellWidget(row, 1, self._source_field(target, source))
            self._axis_field(row, target)

    def _source_field(self, target: str, source: QComboBox) -> QWidget:
        field = QWidget()
        layout = QHBoxLayout(field)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        layout.addWidget(source, 1)
        warning = QToolButton()
        warning.setAutoRaise(True)
        warning.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
        warning.setFixedWidth(24)
        policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        policy.setRetainSizeWhenHidden(True)
        warning.setSizePolicy(policy)
        warning.setAccessibleName(f"Column warning: {SIGNALS[target]}")
        warning.clicked.connect(lambda: self._show_warning(target))
        warning.hide()
        self._warnings[target] = warning
        layout.addWidget(warning)
        field.installEventFilter(self)
        return field

    def _axis_field(self, row: int, target: str) -> None:
        if target not in IMU_COLUMNS:
            item = QTableWidgetItem("—")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, item)
            return
        field = QWidget()
        layout = QHBoxLayout(field)
        layout.setContentsMargins(0, 4, 0, 4)
        checkbox = QCheckBox()
        checkbox.setPalette(light_palette())
        checkbox.setAccessibleName(f"Invert {SIGNALS[target]}")
        checkbox.setToolTip(
            tooltip_text("Reverse this signal's direction (multiply by −1) during preparation.")
        )
        checkbox.toggled.connect(lambda checked: self.model.invert(target, checked))
        self._inversions[target] = checkbox
        layout.addWidget(checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        field.installEventFilter(self)
        self.table.setCellWidget(row, 2, field)

    def _show_warning(self, target: str) -> None:
        warning = self._warnings[target]
        dialog = QMessageBox(QMessageBox.Icon.Warning, warning.accessibleName(), "", parent=self)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(warning.accessibleDescription())
        dialog.exec()
        dialog.deleteLater()

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        self.auto_button = button("Auto-match", self.auto_match)
        self.reset_button = button("Reset", self.reset)
        self.optional_button = button("Show optional signals", self._toggle_optional)
        self.details_button = button("Show details", self._toggle_details)
        self.details_button.setCheckable(True)
        for control in (
            self.auto_button,
            self.reset_button,
            self.optional_button,
            self.details_button,
        ):
            actions.addWidget(control)
        actions.addStretch()
        return actions

    def mapping(self) -> dict[str, str]:
        return self.model.mapping()

    def axis_inversions(self) -> list[str]:
        return self.model.axis_inversions()

    def set_axis_inversions(self, inversions: object) -> None:
        self.model.set_axis_inversions(inversions)
        self._refresh_inversions()

    def set_preparation_enabled(self, enabled: bool) -> None:
        for checkbox in self._inversions.values():
            checkbox.setEnabled(enabled)

    def _refresh_inversions(self) -> None:
        for target, checkbox in self._inversions.items():
            blocked = checkbox.blockSignals(True)
            checkbox.setChecked(target in self.model.inversions)
            checkbox.blockSignals(blocked)

    def set_mapping(self, mapping: Mapping[str, str] | None) -> None:
        self.model.set_mapping(mapping)
        self._refresh()
        self.changed.emit()

    def set_recordings(
        self, schemas: Mapping[str, Sequence[str]], names: Mapping[str, str]
    ) -> None:
        # Loading already refreshes origin and raw plots in their existing order.
        self.model.set_recordings(schemas, names)
        self._refresh()

    def set_modules(self, modules: Iterable[str]) -> None:
        self._modules = list(modules)
        self._refresh_status()

    def auto_match(self) -> None:
        self.model.auto_match()
        self._refresh()
        self.changed.emit()

    def reset(self) -> None:
        self.model.reset()
        self._refresh()
        self.changed.emit()

    def _choose(self, target: str) -> None:
        self.model.choose(target, self._combos[target].currentData())
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        self._refresh_inversions()
        columns = self.model.columns
        for target, source in self._combos.items():
            selected = self.model.choices[target]
            source.blockSignals(True)
            source.clear()
            if target not in columns:
                source.addItem("Not included", None)
            ordered = (
                [target, *(column for column in columns if column != target)]
                if target in columns
                else columns
            )
            for column in ordered:
                source.addItem(column, column)
            source.setCurrentIndex(source.findData(selected))
            source.blockSignals(False)
        self._refresh_status()

    def _refresh_status(self) -> None:
        required = required_signals(self._modules)
        suggestions = self.model.suggestions()
        conflicts = self.model.source_conflicts()
        self._target_conflicts = self.model.target_conflicts()
        total = len(self.model.schemas)
        for row, target in enumerate(SIGNALS):
            self.table.setRowHidden(row, target not in required and not self._expanded)
            self._labels[target].setText(
                SIGNALS[target] + ("" if target in required else " (optional)")
            )
            selected = self.model.choices[target]
            status, tooltip = self._status(target, selected, total, conflicts, suggestions)
            warning = self._warnings[target]
            text = tooltip_text(f"{status}\n{tooltip}")
            warning.setToolTip(text)
            warning.setAccessibleDescription(f"{status}\n{tooltip}")
            warning.setVisible(
                bool(total)
                and (
                    status in {"Assigned twice", "Name conflict"}
                    or status.startswith("Missing")
                    or (selected is None and target in required)
                )
            )
            self._combos[target].setToolTip(text)
        validation = self.model.validate(self._modules)
        self.summary.setText(
            f"Compatible with {validation.compatible} of {total} recordings. One mapping applies to all."
            if total
            else "Open recordings to select signal columns."
        )
        lines = list(validation.details)
        if self.model.extra:
            lines.append("Other saved mappings (preserved):")
            lines.extend(f"{source} → {target}" for source, target in self.model.extra.items())
        self.details.setText("\n".join(lines))
        self.details_button.setVisible(bool(lines))
        self.details.setVisible(bool(lines) and self.details_button.isChecked())
        self.auto_button.setEnabled(not self.model.matches_automatic())
        self.auto_button.setToolTip(tooltip_text(self._auto_match_help()))
        self.optional_button.setVisible(len(required) < len(SIGNALS))
        self._fit_table()

    def _auto_match_help(self) -> str:
        if not self.auto_button.isEnabled():
            return "Every signal already matches the automatic result." + (
                " Open recordings to match their columns." if not self.model.schemas else ""
            )
        return (
            "Match all signals, including optional ones, using column names shared by every recording. "
            "Replace manual selections and clear fields without an unambiguous match. "
            "Axis inversion choices are kept."
        )

    def _status(
        self,
        target: str,
        source: str | None,
        total: int,
        conflicts: set[str],
        suggestions: dict[str, str],
    ) -> tuple[str, str]:
        if source in conflicts:
            return "Assigned twice", "Choose a different column for each signal."
        if target in self._target_conflicts:
            return "Name conflict", (
                f"Multiple columns become this signal in "
                f"{len(self._target_conflicts[target])} of {total} recordings."
            )
        if source is None:
            suggestion = suggestions.get(target)
            return (
                ("Suggested", f"Auto-match can select {suggestion}.")
                if suggestion
                else ("Not mapped", "Select a column from the loaded recordings.")
            )
        missing = sum(source not in columns for columns in self.model.schemas.values())
        if missing:
            return (
                f"Missing in {missing}/{total}",
                f"Selected column: {source}\nMissing in {missing} of {total} recordings.",
            )
        return ("Available", source) if total else ("No recording", source)

    def _toggle_optional(self) -> None:
        self._expanded = not self._expanded
        self.optional_button.setText(
            "Hide optional signals" if self._expanded else "Show optional signals"
        )
        self._refresh_status()

    def _toggle_details(self) -> None:
        self.details.setVisible(self.details_button.isChecked())
        self.details_button.setText(
            "Hide details" if self.details_button.isChecked() else "Show details"
        )

    def _fit_table(self) -> None:
        if self._fitting_table:
            return
        self._fitting_table = True
        try:
            self._size_table()
        finally:
            self._fitting_table = False

    def _size_table(self) -> None:
        controls = [
            cell
            for row in range(self.table.rowCount())
            for column in (1, 2)
            if (cell := self.table.cellWidget(row, column)) is not None
        ]
        for cell in controls:
            for control in cell.findChildren(QWidget):
                control.ensurePolished()
        row_height = max(
            30,
            max(
                max(cell.sizeHint().height(), cell.minimumSizeHint().height(), cell.minimumHeight())
                for cell in controls
            ),
        )
        self.table.verticalHeader().setDefaultSectionSize(row_height)
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, row_height)
        count = sum(not self.table.isRowHidden(row) for row in range(self.table.rowCount()))
        self.table.setFixedHeight(
            self.table.horizontalHeader().sizeHint().height()
            + count * row_height
            + 2 * self.table.frameWidth()
        )
        header = self.table.horizontalHeader()
        self.table.setMinimumWidth(max(470, header.sectionSize(0) + header.sectionSize(2) + 128))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.LayoutRequest and hasattr(self, "summary"):
            self._fit_table()
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and self._combos:
            self._fit_table()
