"""Integrated Signal columns help with a proportional input-axis illustration."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..analysis_help import SIGNAL_COLUMNS_HELP_AFTER_HTML
from ..assets import DATA_DIRECTORY
from ..theme import LINK_COLOR


def signal_columns_help(description: QLabel, reference: str) -> QWidget:
    """Keep the reviewed paragraphs and illustration in one explanation panel."""
    panel = QWidget()
    panel.setObjectName("signalColumnsHelp")
    content = QVBoxLayout(panel)
    content.setContentsMargins(10, 10, 10, 10)
    content.setSpacing(10)
    description.setObjectName("signalColumnsHelpText")
    content.addWidget(description)
    figure = InputAxisFigure()
    figure.setMaximumWidth(figure.maximum_image_width)
    content.addWidget(figure, alignment=Qt.AlignmentFlag.AlignHCenter)
    continuation = QLabel(
        f'{SIGNAL_COLUMNS_HELP_AFTER_HTML}<p><a style="color: {LINK_COLOR}; '
        f'text-decoration: underline;" href="{escape(reference, quote=True)}">'
        "ParaDigMa documentation · Coordinate System guide</a></p>"
    )
    continuation.setObjectName("signalColumnsHelpText")
    continuation.setAccessibleName("Help: Signal columns (continued)")
    continuation.setWordWrap(True)
    continuation.setTextFormat(Qt.TextFormat.RichText)
    continuation.setOpenExternalLinks(True)
    continuation.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    content.addWidget(continuation)
    return panel


class InputAxisFigure(QWidget):
    """Paint the bundled figure without making its source width a layout minimum."""

    maximum_image_width = 900

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = QPixmap(str(DATA_DIRECTORY / "input-axis-orientation.png"))
        self.setObjectName("inputAxisFigure")
        self.setAccessibleName("Expected input sensor orientation: left and right arm")
        self.setAccessibleDescription(
            "Positive input axes shown on watches worn on the left and right wrist, "
            "before ParaDigMa applies its wrist-side adjustment."
        )
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def heightForWidth(self, width: int) -> int:
        if self._image.isNull():
            return 0
        width = min(max(0, width), self.maximum_image_width)
        return round(width * self._image.height() / self._image.width())

    def sizeHint(self) -> QSize:
        width = self.maximum_image_width
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        width = min(self.width(), self.maximum_image_width)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(
            QRect(0, 0, width, self.heightForWidth(width)), self._image, self._image.rect()
        )
