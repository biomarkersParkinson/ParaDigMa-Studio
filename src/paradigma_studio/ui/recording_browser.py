"""Read-only browser for selecting recording files and folders together."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Qt
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileSystemModel,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..recordings import SENSOR_FILE_PATTERNS
from ..theme import light_palette
from ..widgets import button, label


@dataclass(frozen=True)
class RecordingSelection:
    paths: tuple[Path, ...]
    directory: str


class RecordingBrowser(QDialog):
    """Choose siblings with standard extended selection; folders open on activation."""

    def __init__(self, parent: QWidget | None = None, directory: str | None = None) -> None:
        super().__init__(parent)
        self.setPalette(light_palette())
        self.setWindowTitle("Open recordings")
        self.resize(900, 580)
        self.setMinimumSize(620, 420)
        self.directory = ""
        self._history: list[str] = []
        self._paths: tuple[Path, ...] = ()
        self.model = QFileSystemModel(self)
        self.model.setReadOnly(True)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.model.setNameFilters(list(SENSOR_FILE_PATTERNS))
        self.model.setNameFilterDisables(False)
        self.model.setOption(QFileSystemModel.Option.DontUseCustomDirectoryIcons, True)
        self.model.setRootPath(QDir.rootPath())
        content = QVBoxLayout(self)
        content.setContentsMargins(18, 18, 18, 18)
        content.setSpacing(12)
        content.addWidget(label("Choose recordings for the same subject", "sectionTitle"))
        content.addWidget(
            label("Select files and folders with Ctrl or Shift. Double-click a folder to open it.")
        )
        self._build_navigation(content)
        self._build_entries(content)
        content.addWidget(
            label("Selected folders include supported recordings in all subfolders.", "muted")
        )
        self.summary = label("Select at least one file or folder.", "muted")
        self.summary.setAccessibleName("Recording selection summary")
        content.addWidget(self.summary)
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = button("Cancel", self.reject)
        self.load_button = button("Load", self.accept, primary=True)
        self.load_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.load_button)
        content.addLayout(actions)
        for control in self.findChildren(QPushButton):
            control.setAutoDefault(False)
        self.navigate(
            directory if directory is not None else QDir.homePath(),
            remember=False,
        )
        self._shortcuts = [
            QShortcut(key, self, callback)
            for key, callback in (
                ("Alt+Left", self.go_back),
                ("Alt+Up", self.go_up),
                ("Ctrl+L", self.focus_location),
            )
        ]

    def _build_navigation(self, content: QVBoxLayout) -> None:
        navigation = QHBoxLayout()
        self.back_button = button("Back", self.go_back)
        self.up_button = button("Up", self.go_up)
        self.computer_button = button("Computer", lambda: self.navigate(""))
        self.location = QLineEdit()
        self.location.setAccessibleName("Folder location")
        self.location.setPlaceholderText("Enter a folder location")
        self.location.returnPressed.connect(lambda: self.navigate(self.location.text()))
        self.go_button = button("Go", lambda: self.navigate(self.location.text()))
        for control in (self.back_button, self.up_button, self.computer_button):
            navigation.addWidget(control)
        navigation.addWidget(self.location, 1)
        navigation.addWidget(self.go_button)
        content.addLayout(navigation)

    def _build_entries(self, content: QVBoxLayout) -> None:
        self.entries = QTreeView()
        self.entries.setObjectName("recordingFiles")
        self.entries.setAccessibleName("Recording files and folders")
        self.entries.setModel(self.model)
        self.entries.setRootIsDecorated(False)
        self.entries.setItemsExpandable(False)
        self.entries.setUniformRowHeights(True)
        self.entries.setAlternatingRowColors(True)
        self.entries.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.entries.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.entries.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.entries.setSortingEnabled(True)
        self.entries.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        header = self.entries.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.entries.selectionModel().selectionChanged.connect(self._selection_changed)
        self.entries.activated.connect(self._activate)
        content.addWidget(self.entries, 1)

    def navigate(self, path: str, *, remember: bool = True) -> None:
        self.entries.clearSelection()
        if path:
            path = QDir.fromNativeSeparators(os.path.expanduser(path))
            if not QDir.isAbsolutePath(path):
                path = QDir(self.directory or QDir.rootPath()).absoluteFilePath(path)
            path = QDir.cleanPath(path)
            index = self.model.index(path)
            if not index.isValid() or not self.model.isDir(index):
                self.summary.setText("Folder unavailable. Check the location and try again.")
                return
        else:
            index = QModelIndex()
        if remember and path != self.directory:
            self._history.append(self.directory)
        self.directory = path
        self.model.setRootPath(path)
        self.entries.setRootIndex(index)
        self.location.setText(QDir.toNativeSeparators(path))
        self.back_button.setEnabled(bool(self._history))
        self.up_button.setEnabled(bool(path))
        self._selection_changed()
        self.entries.setFocus()

    def go_back(self) -> None:
        if self._history:
            self.navigate(self._history.pop(), remember=False)

    def go_up(self) -> None:
        if self.directory:
            parent = QDir(self.directory)
            self.navigate(parent.absolutePath() if parent.cdUp() else "")

    def focus_location(self) -> None:
        self.location.setFocus()
        self.location.selectAll()

    def _activate(self, index: QModelIndex) -> None:
        if self.model.isDir(index):
            self.navigate(self.model.filePath(index))

    def _selection_changed(self) -> None:
        indexes = self.entries.selectionModel().selectedRows()
        folders = sum(self.model.isDir(index) for index in indexes)
        files = len(indexes) - folders
        parts = [
            f"{count} {singular if count == 1 else plural}"
            for count, singular, plural in (
                (files, "file", "files"),
                (folders, "folder", "folders"),
            )
            if count
        ]
        self.summary.setText(
            " and ".join(parts) + " selected." if parts else "Select at least one file or folder."
        )
        self.load_button.setEnabled(bool(indexes))

    def accept(self) -> None:
        indexes = self.entries.selectionModel().selectedRows()
        if indexes:
            self._paths = tuple(Path(self.model.filePath(index)) for index in indexes)
            super().accept()

    @classmethod
    def choose(cls, parent: QWidget, directory: str | None = None) -> RecordingSelection | None:
        dialog = cls(parent, directory)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                return RecordingSelection(dialog._paths, dialog.directory)
            return None
        finally:
            dialog.deleteLater()
