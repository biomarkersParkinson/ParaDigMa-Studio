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
    QSpacerItem,
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
        self._file_badges: dict[str, QLabel] = {}
        self._name_spacers: list[tuple[QVBoxLayout, QSpacerItem]] = []
        self._inversions: dict[str, QCheckBox] = {}
        self._choice_sources: dict[str, tuple[str | None, str]] = {}
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
        # Focus belongs to the embedded controls, not to the table's current cell.
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setTabKeyNavigation(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header = self.table.horizontalHeader()
        for column in (0, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        delegate = _CellControls(self.table)
        for column in range(3):
            self.table.setItemDelegateForColumn(column, delegate)
        for row, (target, title) in enumerate(SIGNALS.items()):
            self._labels[target] = QTableWidgetItem(title)
            self._labels[target].setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            self.table.setItem(row, 0, self._labels[target])
            self.table.setCellWidget(row, 0, self._signal_field(target))
            source = combo()
            source.setMinimumWidth(80)
            source.setMinimumContentsLength(8)
            source.setPlaceholderText("Select a column…")
            source.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            source.setAccessibleName(f"Column for {title}")
            source.currentIndexChanged.connect(lambda _index, target=target: self._choose(target))
            source.activated.connect(lambda _index, target=target: self._confirm_choice(target))
            self._combos[target] = source
            self.table.setCellWidget(row, 1, self._source_field(target, source))
            self._axis_field(row, target)

    def _signal_field(self, target: str) -> QWidget:
        field = QWidget()
        layout = QVBoxLayout(field)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # The table paints the signal name above this transparent spacer.
        spacer = QSpacerItem(
            0,
            self.table.fontMetrics().height(),
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Fixed,
        )
        layout.addItem(spacer)
        self._name_spacers.append((layout, spacer))
        badge = label("From file", "muted")
        badge.setObjectName("fileDefaultBadge")
        badge.setWordWrap(False)
        badge.setAccessibleName(f"{SIGNALS[target]}: from file")
        policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        policy.setRetainSizeWhenHidden(True)
        badge.setSizePolicy(policy)
        badge.hide()
        self._file_badges[target] = badge
        layout.addWidget(badge)
        field.installEventFilter(self)
        return field

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
        # A custom pixmap keeps the warning visible without Qt's Windows alert sound.
        dialog.setIconPixmap(dialog.iconPixmap())
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(warning.accessibleDescription())
        dialog.exec()
        dialog.deleteLater()

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        self.default_button = button("Default", self.auto_match)
        self.default_button.setAccessibleName("Restore signal columns from file")
        self.optional_button = button("Show optional signals", self._toggle_optional)
        self.details_button = button("Show details", self._toggle_details)
        self.details_button.setCheckable(True)
        for control in (
            self.default_button,
            self.optional_button,
            self.details_button,
        ):
            actions.addWidget(control)
        actions.addStretch()
        return actions

    def mapping(self) -> dict[str, str]:
        return self.model.mapping()

    def signal_columns(self) -> dict[str, str | None]:
        return self.model.signal_columns()

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

    def set_mapping(
        self,
        mapping: Mapping[str, str] | None,
        *,
        signal_columns: dict[str, str | None] | None = None,
    ) -> None:
        self.model.set_mapping(mapping, signal_columns=signal_columns)
        self._choice_sources = {
            target: (self.model.choices[target], "Explicit mapping")
            for target in SIGNALS
            if signal_columns is not None or target in (mapping or {}).values()
        }
        self._refresh()
        self.changed.emit()

    def set_recordings(
        self, schemas: Mapping[str, Sequence[str]], names: Mapping[str, str]
    ) -> None:
        # Loading already refreshes origin and raw plots in their existing order.
        initial = not self.model.schemas and not self._choice_sources
        self.model.set_recordings(schemas, names)
        if initial:
            self.model.auto_match()
            self._record_file_sources()
        self._refresh()

    def set_modules(self, modules: Iterable[str]) -> None:
        self._modules = list(modules)
        self._refresh_status()

    def auto_match(self) -> None:
        self.model.auto_match()
        self._record_file_sources()
        self._refresh()
        self.changed.emit()

    def _record_file_sources(self) -> None:
        self._choice_sources = {
            target: (
                source,
                (
                    "From file: exact column name"
                    if source == target
                    else "From file: recognized alias"
                )
                if source is not None
                else "No unambiguous match",
            )
            for target, source in self.model.choices.items()
        }

    def reset(self) -> None:
        self.model.reset()
        self._choice_sources.clear()
        self._refresh()
        self.changed.emit()

    def reset_for_input(self) -> None:
        self._expanded = False
        self.optional_button.setText("Show optional signals")
        self.details_button.setChecked(False)
        self.details_button.setText("Show details")
        self.model.reset()
        self.auto_match()

    def _choose(self, target: str) -> None:
        self.model.choose(target, self._combos[target].currentData())
        self._choice_sources[target] = (self.model.choices[target], "Selected manually")
        self._refresh()
        self.changed.emit()

    def _confirm_choice(self, target: str) -> None:
        # Selecting the existing file value is still an explicit manual choice.
        if self._selection_source(target, self.model.choices[target]) != "Selected manually":
            self._choose(target)

    def _refresh(self) -> None:
        self._refresh_inversions()
        columns = self.model.columns
        for target, source in self._combos.items():
            selected = self.model.choices[target]
            source.blockSignals(True)
            source.clear()
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
        automatic = self.model.automatic_choices()
        for row, target in enumerate(SIGNALS):
            self.table.setRowHidden(row, target not in required and not self._expanded)
            self._labels[target].setText(SIGNALS[target])
            self._labels[target].setToolTip(
                "Required by the selected modules."
                if target in required
                else "Optional for the selected modules."
            )
            selected = self.model.choices[target]
            reason = self._selection_source(target, selected)
            from_file = (
                selected is not None
                and selected == automatic[target]
                and reason.startswith("From file:")
            )
            badge = self._file_badges[target]
            badge.setVisible(from_file)
            detail = f"{reason}. Column: {selected}. Shared by all {total} recording(s)."
            badge.setToolTip(tooltip_text(detail) if from_file else "")
            badge.setAccessibleDescription(detail if from_file else "")
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
        if total:
            if lines:
                lines.append("")
            lines.extend(["Column selections:", *self._selection_details()])
        self.details.setText("\n".join(lines))
        self.details_button.setVisible(bool(lines))
        self.details.setVisible(bool(lines) and self.details_button.isChecked())
        self.default_button.setEnabled(bool(total))
        self.default_button.setToolTip(
            tooltip_text(
                "Restore all signal columns from names shared by every recording, including optional signals. "
                "Replace manual selections and clear fields without an unambiguous match. "
                "Axis inversion choices are kept."
                if total
                else "Open recordings to read their signal columns."
            )
        )
        self.optional_button.setVisible(len(required) < len(SIGNALS))
        self._fit_table()

    def _selection_details(self) -> list[str]:
        return [
            f"{SIGNALS[target]}: {source or 'Not included'} "
            f"({self._selection_source(target, source)})"
            for target, source in self.model.choices.items()
        ]

    def _selection_source(self, target: str, source: str | None) -> str:
        fallback = "From file: exact column name" if source == target else "Not assigned"
        previous, reason = self._choice_sources.get(target, (source, fallback))
        return reason if previous == source else fallback

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
                ("Suggested", f"Default can restore {suggestion} from the file columns.")
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
        for layout, spacer in self._name_spacers:
            height = self.table.fontMetrics().height()
            if spacer.sizeHint().height() != height:
                spacer.changeSize(0, height, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
                layout.invalidate()
        controls = [
            cell
            for row in range(self.table.rowCount())
            for column in range(3)
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
        # Only source cells contribute to the source column's minimum width.
        # Provenance shares the signal-name column instead of widening editors.
        source_width = max(
            128,
            *(
                self.table.cellWidget(row, 1).minimumSizeHint().width()
                for row in range(len(SIGNALS))
            ),
        )
        self.table.setMinimumWidth(
            max(470, header.sectionSize(0) + header.sectionSize(2) + source_width)
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.LayoutRequest and hasattr(self, "summary"):
            self._fit_table()
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and self._combos:
            self._fit_table()
