"""Shared Qt controls and layouts; no analysis or application state."""

import numpy as np
from PySide6.QtCore import (
    QAbstractAnimation,
    QAbstractTableModel,
    QEasingCurve,
    QEvent,
    QModelIndex,
    QPointF,
    QRect,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPalette, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QBoxLayout,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListView,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionComboBox,
    QStyleOptionTab,
    QStyleOptionViewItem,
    QStylePainter,
    QTabBar,
    QTableView,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import light_palette, module_color


class WrappedForm(QWidget):
    """Reserve the form's actual height at its current width, including wraps.

    QWidget.sizeHint describes the preferred width. A fixed size policy based
    on that hint can clip QFormLayout.WrapLongRows at narrower Windows widths.
    Help lives outside this widget, so it cannot alter the reserved form height.
    """

    height_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fitting_height = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _fit_height(self):
        if self._fitting_height:
            return
        previous = self.minimumHeight()
        self._fitting_height = True
        try:
            layout = self.layout()
            if layout is not None:
                self._settle_layout(layout)
                layout.activate()
            self._reserve_height()
        finally:
            self._fitting_height = False
        if self.minimumHeight() != previous:
            self.height_changed.emit()

    def _settle_layout(self, layout):
        # Follow active layout items, not QObject descendants such as hidden
        # popups. Fit nested fixed-height forms before measuring their parents.
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item.isEmpty():
                continue
            if (nested := item.layout()) is not None:
                self._settle_layout(nested)
            elif (widget := item.widget()) is not None:
                if isinstance(widget, WrappedForm):
                    widget._fit_height()
                elif (nested := widget.layout()) is not None:
                    self._settle_layout(nested)
                    nested.activate()

    def _reserve_height(self):
        height = self.heightForWidth(self.width())
        if height >= 0 and (self.minimumHeight() != height or self.maximumHeight() != height):
            self.setFixedHeight(height)
        layout = self.layout()
        if layout is not None and layout.geometry() != self.contentsRect():
            # Resizing inside a layout pass can leave Qt's cached rectangle
            # at the previous height even after the widget has grown. Restore
            # its real bounds before arranging the children or painting them.
            layout.setGeometry(self.contentsRect())

    def heightForWidth(self, width):
        # Report the same height to parent layouts that we reserve locally.
        # Qt's default can report less than nested fixed-height forms need,
        # briefly placing help over the final rows during a layout pass.
        layout = self.layout()
        if layout is None:
            return -1
        height = (
            layout.totalHeightForWidth(width)
            if layout.hasHeightForWidth()
            else layout.sizeHint().height()
        )
        return max(height, layout.minimumSize().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.LayoutRequest:
            self._fit_height()
        return result


class AdaptiveFormColumns(QHBoxLayout):
    """Keep two form sections side by side when they fit, otherwise stack them.

    The minimum width is the wider individual form. Reporting the sum would
    force a scroll area's body beyond its viewport before wrapping can occur.
    Height queries do not change direction, so measuring help cannot reflow
    the fields; only the actual layout width determines their arrangement.
    """

    def __init__(self, left, right, *, right_stretch=1):
        super().__init__()
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(20)
        self.addLayout(left, 1)
        self.addLayout(right, right_stretch)

    def minimumSize(self):
        sizes = [self.itemAt(index).minimumSize() for index in range(self.count())]
        margins = self.contentsMargins()
        return QSize(
            max(size.width() for size in sizes) + margins.left() + margins.right(),
            max(size.height() for size in sizes) + margins.top() + margins.bottom(),
        )

    def _column_widths(self, width):
        minimums = [self.itemAt(index).minimumSize().width() for index in range(self.count())]
        if sum(minimums) + self.spacing() > width:
            return None
        available = width - self.spacing()
        # A field with an action gives the action its preferred width, leaving
        # the rest for the editor. Two parameter columns share available space.
        preferred_left = (
            available - self.itemAt(1).sizeHint().width()
            if self.stretch(1) == 0
            else available // 2
        )
        left = max(minimums[0], min(preferred_left, available - minimums[1]))
        return left, available - left

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        margins = self.contentsMargins()
        width -= margins.left() + margins.right()
        widths = self._column_widths(width)
        heights = []
        for index in range(self.count()):
            item = self.itemAt(index)
            child_width = width if widths is None else widths[index]
            height = (
                item.heightForWidth(child_width)
                if item.hasHeightForWidth()
                else item.sizeHint().height()
            )
            heights.append(max(height, item.minimumSize().height()))
        height = sum(heights) + self.spacing() if widths is None else max(heights)
        return height + margins.top() + margins.bottom()

    def setGeometry(self, rect):
        margins = self.contentsMargins()
        width = rect.width() - margins.left() - margins.right()
        direction = (
            QBoxLayout.TopToBottom if self._column_widths(width) is None else QBoxLayout.LeftToRight
        )
        if self.direction() != direction:
            self.setDirection(direction)
        super().setGeometry(rect)


class CheckLabelDelegate(QStyledItemDelegate):
    """Toggle a checkable row once when its checkbox or label is clicked."""

    def editorEvent(self, event, model, option, index):
        if (
            index.flags() & Qt.ItemIsUserCheckable
            and index.flags() & Qt.ItemIsEnabled
            and event.type()
            in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick)
            and event.button() == Qt.LeftButton
            and option.rect.contains(event.position().toPoint())
        ):
            if event.type() == QEvent.MouseButtonRelease:
                checked = index.data(Qt.CheckStateRole) in (Qt.Checked, Qt.Checked.value)
                return model.setData(
                    index, Qt.Unchecked if checked else Qt.Checked, Qt.CheckStateRole
                )
            return True
        return super().editorEvent(event, model, option, index)


class SeriesLabelDelegate(CheckLabelDelegate):
    """Reserve wrapped row heights instead of shortening long metric names."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.textElideMode = Qt.ElideNone
        option.features |= QStyleOptionViewItem.WrapText

    def sizeHint(self, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        tree = self.parent()
        depth, parent = 1, index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        check_width = 32 if index.data(Qt.CheckStateRole) is not None else 0
        width = max(40, tree.viewport().width() - depth * tree.indentation() - check_width - 12)
        text = styled.fontMetrics.boundingRect(
            QRect(0, 0, width, 10000), Qt.TextWordWrap, styled.text
        )
        hint = super().sizeHint(styled, index)
        return QSize(hint.width(), max(hint.height(), text.height() + 10))


class SeriesTree(QTreeWidget):
    """Module titles toggle expansion; native arrows and leaf checks still work."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(SeriesLabelDelegate(self))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scheduleDelayedItemsLayout()

    def mouseReleaseEvent(self, event):
        position = event.position().toPoint()
        item = self.itemAt(position)
        title_clicked = (
            event.button() == Qt.LeftButton
            and item is not None
            and item.parent() is None
            and self.visualItemRect(item).contains(position)
        )
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
        hint.setWidth(
            max(self.toolbar.sizeHint().width(), context_width) + margins.left() + margins.right()
        )
        return hint

    def _arrange(self):
        if self.context is None:
            return
        margins = self.layout().contentsMargins()
        available = self.width() - margins.left() - margins.right()
        required = (
            self.toolbar.sizeHint().width()
            + self.context.sizeHint().width()
            + self.primary.spacing()
        )
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
            color = (
                QColor(module_color(self.tabData(index)))
                if self.isTabEnabled(index)
                else QColor("#99A4B4")
            )
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
            if isinstance(widget, QLabel) and not widget.wordWrap():
                # Hidden branding labels can retain a stale layout-item width
                # after a font change. Reserve their current text width before
                # showing them, so unfolding never moves navigation anchors.
                widget.setMinimumWidth(max(widget.minimumWidth(), widget.minimumSizeHint().width()))
        for layout in self.content.findChildren(QLayout):
            layout.invalidate()
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
            width = (
                self.expanded_width
                if self.expanded and self.animation.state() != QAbstractAnimation.Running
                else self.width()
            )
            self._resize(width)
        return super().eventFilter(watched, event)


def precision_tooltip(value, displayed: str) -> str:
    """Expose numeric precision only when rounding hides part of the value."""
    if isinstance(value, (float, np.floating)) and np.isfinite(value):
        try:
            if float(displayed) != value:
                return str(value)
        except ValueError:
            pass
    return ""


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
        if role == Qt.ToolTipRole and not self.compact:
            return None
        if index.isValid() and role in (Qt.DisplayRole, Qt.ToolTipRole):
            column = index.column()
            if column not in self._column_values:
                self._column_values[column] = self.frame.iloc[:, column].array
            value = self._column_values[column][index.row()]
            displayed = self._display_value(value)
            return (
                precision_tooltip(value, displayed) or None if role == Qt.ToolTipRole else displayed
            )

    def _display_value(self, value):
        import pandas as pd

        if self.compact:
            if (
                value is pd.NA
                or value is None
                or isinstance(value, (float, np.floating))
                and np.isnan(value)
            ):
                return "—"
            if isinstance(value, (float, np.floating)):
                return f"{value:.5g}"
        return str(value)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return (
                str(self.frame.columns[section])
                if orientation == Qt.Horizontal
                else str(section + 1)
            )


class RecordModel(FrameModel):
    """Display metadata rows without loading the sensor-data libraries.

    Keep the FrameModel interface for existing consumers that inspect or update
    its DataFrame. Construct that view only when it is explicitly requested.
    """

    def __init__(self, records, columns):
        super().__init__(None)
        self._rows = tuple(tuple(record[column] for column in columns) for record in records)
        self._columns = tuple(columns)

    @property
    def frame(self):
        if self._frame is None:
            import pandas as pd

            self._frame = pd.DataFrame(self._rows, columns=self._columns)
        return self._frame

    @frame.setter
    def frame(self, value):
        self._frame = value

    def rowCount(self, parent=QModelIndex()):
        if self._frame is not None:
            return super().rowCount(parent)
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        if self._frame is not None:
            return super().columnCount(parent)
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index, role=Qt.DisplayRole):
        if self._frame is not None:
            return super().data(index, role)
        if index.isValid() and role == Qt.DisplayRole:
            return str(self._rows[index.row()][index.column()])

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if self._frame is not None:
            return super().headerData(section, orientation, role)
        if role == Qt.DisplayRole:
            return str(self._columns[section]) if orientation == Qt.Horizontal else str(section + 1)


class ReadableComboBox(QComboBox):
    wheel_scroll_target: QAbstractScrollArea | None = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        target = self.wheel_scroll_target
        if target is None:
            super().wheelEvent(event)
            return
        pixels = event.pixelDelta()
        if not pixels.isNull():
            for bar, delta in (
                (target.horizontalScrollBar(), pixels.x()),
                (target.verticalScrollBar(), pixels.y()),
            ):
                bar.setValue(bar.value() - delta)
            event.accept()
            return
        viewport = target.viewport()
        forwarded = QWheelEvent(
            QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
            event.globalPosition(),
            event.pixelDelta(),
            event.angleDelta(),
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
            event.source(),
            event.pointingDevice(),
        )
        QApplication.sendEvent(viewport, forwarded)
        event.setAccepted(forwarded.isAccepted())

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


class ContextComboBox(ReadableComboBox):
    """Hide an irrelevant value while retaining the user's parameter choice."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._relevant = True

    def set_relevant(self, relevant: bool) -> None:
        self._relevant = relevant
        self.setEnabled(relevant)
        self.update()

    def paintEvent(self, event):
        if self._relevant:
            return super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)


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
            self._heading_widths = [
                metrics.horizontalAdvance(str(model.headerData(i, Qt.Horizontal))) + 28
                for i in range(model.columnCount())
            ]
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


def combo(items=(), *, combo_type=ReadableComboBox):
    combo = combo_type()
    # A Qt list view and explicit palette avoid native dark-theme popups
    # combining dark selection backgrounds with inherited dark text.
    view = QListView()
    view.setUniformItemSizes(True)
    view.setPalette(light_palette())
    combo.setView(view)
    combo.setPalette(light_palette())
    combo.setMaxVisibleItems(12)
    combo.addItems(items)
    return combo


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
