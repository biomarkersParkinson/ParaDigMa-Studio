"""Shared Qt controls and layouts; no analysis or application state."""
import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractAnimation, QAbstractTableModel, QModelIndex, Qt, QEvent, QEasingCurve, QVariantAnimation, Signal
from PySide6.QtGui import QFont, QPalette, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QLabel, QPlainTextEdit,
    QPushButton, QTableView, QVBoxLayout, QHBoxLayout, QWidget, QTabBar, QStylePainter, QStyleOptionTab, QStyle, QSizePolicy, QTreeWidget,
)
from .theme import light_palette, module_color


class WrappedForm(QWidget):
    """Reserve the form's actual height at its current width, including wraps.

    QWidget.sizeHint describes the preferred width. A fixed size policy based
    on that hint can clip QFormLayout.WrapLongRows at narrower Windows widths.
    Help lives outside this widget, so it cannot alter the reserved form height.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _fit_height(self):
        layout = self.layout()
        if layout is None:
            return
        height = layout.totalHeightForWidth(self.width()) if layout.hasHeightForWidth() else layout.sizeHint().height()
        height = max(height, layout.minimumSize().height())
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.LayoutRequest:
            self._fit_height()
        return result


class SeriesTree(QTreeWidget):
    """Module titles toggle expansion; native arrows and leaf checks still work."""
    def mouseReleaseEvent(self, event):
        position = event.position().toPoint()
        item = self.itemAt(position)
        title_clicked = (event.button() == Qt.LeftButton and item is not None and item.parent() is None
                         and self.visualItemRect(item).contains(position))
        expanded = item.isExpanded() if item is not None else False
        super().mouseReleaseEvent(event)
        if title_clicked:
            item.setExpanded(not expanded)


class FigureActionBar(QWidget):
    """Keep the complete toolbar visible; wrap context controls when needed."""
    def __init__(self, toolbar, parent=None):
        super().__init__(parent)
        self.toolbar, self.context = toolbar, None
        toolbar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)
        self.primary = QHBoxLayout()
        self.primary.addWidget(toolbar)
        self.primary.addStretch()
        layout.addLayout(self.primary)
        self.secondary = QWidget()
        self.secondary_layout = QHBoxLayout(self.secondary)
        self.secondary_layout.setContentsMargins(0, 0, 0, 0)
        self.secondary_layout.addStretch()
        layout.addWidget(self.secondary)
        self.secondary.hide()

    def set_context(self, widget):
        self.context = widget
        self.primary.addWidget(widget, alignment=Qt.AlignRight)
        self._arrange()

    def remove_context(self, widget):
        self.primary.removeWidget(widget)
        self.secondary_layout.removeWidget(widget)
        self.context = None
        self.secondary.hide()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        margins = self.layout().contentsMargins()
        context_width = self.context.minimumSizeHint().width() if self.context is not None else 0
        hint.setWidth(max(self.toolbar.sizeHint().width(), context_width) + margins.left() + margins.right())
        return hint

    def _arrange(self):
        if self.context is None:
            return
        margins = self.layout().contentsMargins()
        available = self.width() - margins.left() - margins.right()
        required = self.toolbar.sizeHint().width() + self.context.sizeHint().width() + self.primary.spacing()
        wrapped = required > available
        target = self.secondary_layout if wrapped else self.primary
        if target.indexOf(self.context) < 0:
            visible = not self.context.isHidden()
            self.primary.removeWidget(self.context)
            self.secondary_layout.removeWidget(self.context)
            target.addWidget(self.context, alignment=Qt.AlignRight)
            self.context.setVisible(visible)
        self.secondary.setVisible(wrapped)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.LayoutRequest:
            self._arrange()
        return result


class ModuleTabBar(QTabBar):
    """Keep module text and selected underline in the same module colors."""
    def paintEvent(self, event):
        painter = QStylePainter(self)
        for index in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            text = option.text
            option.text = ""
            painter.drawControl(QStyle.CE_TabBarTabShape, option)
            color = QColor(module_color(self.tabData(index))) if self.isTabEnabled(index) else QColor("#99A4B4")
            font = self.font()
            font.setBold(index == self.currentIndex())
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(option.rect, Qt.AlignCenter, text)
            if index == self.currentIndex():
                painter.fillRect(option.rect.adjusted(0, option.rect.height() - 2, 0, 0), color)


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

    def fit_content(self):
        # Native font metrics differ between Windows and the headless tests.
        # Reserve enough space before animating the clipping frame. Keep the
        # width when labels are hidden/shortened on collapse so anchors stay put.
        self.content.ensurePolished()
        for widget in self.content.findChildren(QWidget):
            widget.ensurePolished()
        self.expanded_width = max(self.expanded_width, self.content.minimumSizeHint().width())
        self.content.setFixedWidth(self.expanded_width)

    def _resize(self, width):
        self.setFixedWidth(int(width))
        self.setGeometry(0, 0, int(width), self.parentWidget().height())
        self.content.setGeometry(0, 0, self.expanded_width, self.height())
        self.raise_()

    def setExpanded(self, expanded, animated=True):
        self.animation.stop()
        self.expanded = expanded
        self.expandedChanged.emit(expanded)
        self.fit_content()
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
            self.fit_content()
            width = self.expanded_width if self.expanded and self.animation.state() != QAbstractAnimation.Running else self.width()
            self._resize(width)
        return super().eventFilter(watched, event)


class FrameModel(QAbstractTableModel):
    def __init__(self, frame, compact=False):
        super().__init__()
        self.frame = frame
        self.compact = compact
        self._column_values = {}
        self.dataChanged.connect(self._forget_values)
        self.modelReset.connect(self._forget_values)

    def _forget_values(self, *_):
        self._column_values.clear()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role in (Qt.DisplayRole, Qt.ToolTipRole):
            column = index.column()
            if column not in self._column_values:
                self._column_values[column] = self.frame.iloc[:, column].array
            value = self._column_values[column][index.row()]
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
