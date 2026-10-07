"""Shared Qt controls and layouts; no analysis or application state."""
import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QEvent, QEasingCurve, QVariantAnimation, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QLabel, QPlainTextEdit,
    QPushButton, QTableView, QVBoxLayout, QWidget,
)
from .theme import light_palette


class HoverSidebar(QFrame):
    """A compact rail that unfolds over the workspace without moving content."""
    expandedChanged = Signal(bool)
    rail_width = 68
    expanded_width = 194

    def __init__(self, parent):
        super().__init__(parent)
        self.expanded = False
        self.setFixedWidth(self.rail_width)
        # Animate the clipping frame, never the layout inside it. Text and
        # navigation anchors keep their expanded geometry at every width.
        self.content = QWidget(self)
        self.content.setFixedWidth(self.expanded_width)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(120)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._resize)
        parent.installEventFilter(self)

    def _resize(self, width):
        self.setFixedWidth(int(width))
        self.setGeometry(0, 0, int(width), self.parentWidget().height())
        self.content.setGeometry(0, 0, self.expanded_width, self.height())
        self.raise_()

    def setExpanded(self, expanded, animated=True):
        self.animation.stop()
        self.expanded = expanded
        self.expandedChanged.emit(expanded)
        target = self.expanded_width if expanded else self.rail_width
        if animated:
            self.animation.setStartValue(self.width())
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self._resize(target)

    def enterEvent(self, event):
        self.setExpanded(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setExpanded(False)
        super().leaveEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self._resize(self.width())
        return super().eventFilter(watched, event)


class FrameModel(QAbstractTableModel):
    def __init__(self, frame, compact=False):
        super().__init__()
        self.frame = frame
        self.compact = compact

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role in (Qt.DisplayRole, Qt.ToolTipRole):
            value = self.frame.iat[index.row(), index.column()]
            if self.compact and role == Qt.DisplayRole and (value is pd.NA or value is None
                    or isinstance(value, (float, np.floating)) and np.isnan(value)):
                return "—"
            if self.compact and role == Qt.DisplayRole and isinstance(value, (float, np.floating)):
                return f"{value:.5g}"
            return str(value)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return str(self.frame.columns[section]) if orientation == Qt.Horizontal else str(section + 1)


class ReadableComboBox(QComboBox):
    def showPopup(self):
        # The outer popup owns the margins above/below the list. It does not
        # reliably inherit the list palette on Windows with a dark system theme.
        popup = self.view().window()
        palette = light_palette()
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            palette.setColor(group, QPalette.Window, palette.color(group, QPalette.Base))
        popup.setPalette(palette)
        popup.setAutoFillBackground(True)
        super().showPopup()


class ReadableTable(QTableView):
    def __init__(self):
        super().__init__()
        self._heading_widths = []
        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setTextElideMode(Qt.ElideNone)
        font = header.font()
        font.setWeight(QFont.DemiBold)
        header.setFont(font)
        # Size data columns from a small sample, never the entire sensor file.
        header.setResizeContentsPrecision(25)
        header.sectionResized.connect(self.keep_heading_readable)

    def setModel(self, model):
        self._heading_widths = []
        super().setModel(model)
        if model is not None:
            self.ensurePolished()
            self.horizontalHeader().ensurePolished()
            metrics = self.horizontalHeader().fontMetrics()
            self._heading_widths = [metrics.horizontalAdvance(str(model.headerData(i, Qt.Horizontal))) + 28
                                    for i in range(model.columnCount())]
            self.resizeColumnsToContents()

    def resizeColumnsToContents(self):
        super().resizeColumnsToContents()
        for i, width in enumerate(self._heading_widths):
            if self.columnWidth(i) < width:
                self.setColumnWidth(i, width)

    def setColumnWidth(self, column, width):
        if column < len(self._heading_widths):
            width = max(width, self._heading_widths[column])
        super().setColumnWidth(column, width)

    def keep_heading_readable(self, column, old_width, width):
        if column < len(self._heading_widths) and width < self._heading_widths[column]:
            header = self.horizontalHeader()
            previous = header.blockSignals(True)
            header.resizeSection(column, self._heading_widths[column])
            header.blockSignals(previous)


def label(text="", role=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(True)
    if role:
        widget.setObjectName(role)
    return widget


def button(text, callback=None, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    if callback:
        widget.clicked.connect(callback)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName("card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    return widget, layout


def table():
    widget = ReadableTable()
    widget.setPalette(light_palette())
    widget.horizontalHeader().setPalette(light_palette())
    widget.verticalHeader().setPalette(light_palette())
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.verticalHeader().hide()
    widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
    return widget


def readout():
    widget = QPlainTextEdit()
    widget.setReadOnly(True)
    return widget


def field(title, control):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    heading = label(title, "muted")
    heading.setBuddy(control)
    layout.addWidget(heading)
    layout.addWidget(control)
    control.setAccessibleName(title)
    return widget
