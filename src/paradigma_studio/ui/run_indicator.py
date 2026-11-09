"""A compact, keyboard-accessible reference to the run owning displayed results."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QKeyEvent, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..theme import tooltip_text


class RunIndicator(QLabel):
    """Elide only the displayed text; retain full context for hover and accessibility."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._run_id = ""
        self.setObjectName("muted")
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(False)
        self.setOpenExternalLinks(False)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.clear()

    def set_reference(self, text: str, tooltip: str, run_id: str = "") -> None:
        self._full_text, self._run_id = text, run_id
        self.setToolTip(tooltip_text(tooltip))
        self.setAccessibleName(text)
        self.setAccessibleDescription("Open this run in Runs." if run_id else "")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if run_id else Qt.FocusPolicy.NoFocus)
        self._render()
        self.show()

    def clear(self) -> None:
        self._full_text = self._run_id = ""
        super().clear()
        self.setToolTip("")
        self.setAccessibleName("")
        self.setAccessibleDescription("")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()

    def _render(self) -> None:
        if not self._full_text:
            return
        text = escape(
            self.fontMetrics().elidedText(
                self._full_text, Qt.TextElideMode.ElideRight, self.contentsRect().width()
            )
        )
        if self._run_id:
            color = self.palette().color(self.foregroundRole()).name()
            text = (
                f'<a href="{escape(self._run_id, quote=True)}" '
                f'style="color: {color}; text-decoration: none;">{text}</a>'
            )
        super().setText(text)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._run_id and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.linkActivated.emit(self._run_id)
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
            QEvent.Type.PaletteChange,
        ):
            self._render()

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())
