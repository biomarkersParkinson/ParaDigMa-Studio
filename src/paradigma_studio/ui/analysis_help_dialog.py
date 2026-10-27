"""Scrollable Analyze explanations in ordinary, non-modal help windows."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..widgets import label
from .analysis_figure import signal_columns_help


class AnalysisHelpDialog(QDialog):
    """Keep long text and the input-axis figure readable without moving fields."""

    def __init__(
        self, title: str, description: QLabel, reference: str, parent: QWidget | None
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.setWindowTitle(f"{title} — Help")
        self.setAccessibleName(f"Information: {title}")
        content = QVBoxLayout(self)
        content.setContentsMargins(18, 18, 18, 18)
        content.setSpacing(12)
        content.addWidget(label(title, "sectionTitle"))
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setAccessibleName(f"{title} explanation")
        body = QWidget()
        explanation = QVBoxLayout(body)
        explanation.setContentsMargins(0, 0, 0, 0)
        explanation.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        explanation.addWidget(
            signal_columns_help(description, reference)
            if title == "Signal columns"
            else description
        )
        explanation.addStretch()
        self.scroll_area.setWidget(body)
        content.addWidget(self.scroll_area, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        content.addWidget(self.buttons)

    def present(self) -> None:
        if not self.isVisible():
            screen = self.screen()
            width, height = (1000, 900) if self.title == "Signal columns" else (680, 380)
            if screen is not None:
                available = screen.availableGeometry()
                width, height = (
                    min(width, available.width() - 48),
                    min(height, available.height() - 80),
                )
            self.resize(width, height)
            self.scroll_area.verticalScrollBar().setValue(0)
        self.show()
        self.raise_()
        self.activateWindow()
