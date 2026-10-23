"""Wheel gestures over input fields scroll the page instead of editing values."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QDateTimeEdit,
    QDoubleSpinBox,
    QLineEdit,
    QScrollArea,
    QWidget,
)


def _surrounding_page(field: QWidget) -> QScrollArea | None:
    parent = field.parentWidget()
    while parent is not None:
        # A mapping table is an input container, not the surrounding page.
        if isinstance(parent, QScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


def _wheel_target(
    field: QWidget, event: QWheelEvent, target: QAbstractScrollArea | None
) -> QAbstractScrollArea | None:
    target = target if target is not None else _surrounding_page(field)
    delta = event.pixelDelta().y() or event.angleDelta().y()
    while target is not None and delta:
        bar = target.verticalScrollBar()
        if delta > 0 and bar.value() > bar.minimum() or delta < 0 and bar.value() < bar.maximum():
            break
        outer = _surrounding_page(target)
        if outer is None:
            break
        target = outer
    return target


def scroll_field_wheel(
    field: QWidget, event: QWheelEvent, target: QAbstractScrollArea | None = None
) -> None:
    target = _wheel_target(field, event, target)
    if target is None:
        event.ignore()
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


class FieldWheelFilter(QObject):
    """Route wheels before native controls or their text editors consume them."""

    def __init__(self, field: QWidget, target: QAbstractScrollArea | None = None) -> None:
        super().__init__(field)
        self.field, self.target = field, target
        field.installEventFilter(self)
        if isinstance(field, QAbstractSpinBox):
            field.lineEdit().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(event, QWheelEvent):
            scroll_field_wheel(self.field, event, self.target)
            return True
        return super().eventFilter(watched, event)


class PageDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wheel_filter = FieldWheelFilter(self)


class PageDateTimeEdit(QDateTimeEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wheel_filter = FieldWheelFilter(self)


class PageLineEdit(QLineEdit):
    wheel_scroll_target: QAbstractScrollArea | None = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        scroll_field_wheel(self, event, self.wheel_scroll_target)
