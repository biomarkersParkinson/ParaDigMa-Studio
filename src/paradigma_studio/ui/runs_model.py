"""Run metadata with a small, selection-independent displayed-results marker."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from ..theme import LINK_COLOR
from ..widgets import RecordModel

DISPLAYED_RUN_DESCRIPTION = "Currently displayed in Results"


@lru_cache(maxsize=1)
def _marker_icons() -> tuple[QIcon, QIcon]:
    # Render at twice the logical size for crisp outlines on scaled displays.
    image = QPixmap(32, 32)
    image.setDevicePixelRatio(2)
    image.fill(Qt.GlobalColor.transparent)
    spacer = QIcon(image)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(LINK_COLOR)
    painter.setPen(QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    outline = QPainterPath(QPointF(1.5, 8))
    outline.cubicTo(5, 2, 11, 2, 14.5, 8)
    outline.cubicTo(11, 14, 5, 14, 1.5, 8)
    painter.drawPath(outline)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QPointF(8, 8), 2.2, 2.2)
    painter.end()
    eye = QIcon()
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active, QIcon.Mode.Disabled):
        eye.addPixmap(image, mode)
    return eye, spacer


class RunsModel(RecordModel):
    def __init__(
        self,
        rows: Sequence[Mapping[str, object]],
        run_ids: Sequence[str],
        displayed_run_id: str | None,
    ) -> None:
        super().__init__(
            rows,
            columns=[
                "Started",
                "Status",
                "Input",
                "Modules",
                "Saved",
                "Warnings",
                "Errors",
                "Exports",
            ],
        )
        self._run_ids = tuple(run_ids)
        self._displayed_run_id: str | None = None
        self.set_displayed_run(displayed_run_id)

    def set_displayed_run(self, run_id: str | None) -> None:
        run_id = run_id if run_id in self._run_ids else None
        previous = self._displayed_run_id
        if previous == run_id:
            return
        self._displayed_run_id = run_id
        roles = [
            Qt.ItemDataRole.DecorationRole,
            Qt.ItemDataRole.ToolTipRole,
            Qt.ItemDataRole.AccessibleDescriptionRole,
            Qt.ItemDataRole.AccessibleTextRole,
        ]
        for changed in (previous, run_id):
            if changed is not None:
                index = self.index(self._run_ids.index(changed), 0)
                self.dataChanged.emit(index, index, roles)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if index.isValid() and index.column() == 0:
            displayed = self._run_ids[index.row()] == self._displayed_run_id
            if role == Qt.ItemDataRole.DecorationRole:
                eye, spacer = _marker_icons()
                return eye if displayed else spacer
            if displayed:
                if role in (Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.AccessibleDescriptionRole):
                    return DISPLAYED_RUN_DESCRIPTION
                if role == Qt.ItemDataRole.AccessibleTextRole:
                    return f"{super().data(index)}, {DISPLAYED_RUN_DESCRIPTION}"
        return super().data(index, role)
