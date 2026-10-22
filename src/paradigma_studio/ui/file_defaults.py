"""Compact provenance for Analyze values supplied by supported sensor files."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from ..input_metadata import UnitDefault, unit_defaults
from ..theme import LINK_COLOR, tooltip_text

if TYPE_CHECKING:
    import pandas as pd

    from ..contracts import ClockMetadata


class FileDefaults:
    """Apply consensus values until explicitly edited; explain every value's source."""

    def __init__(
        self,
        controls: dict[str, QComboBox],
        badges: dict[str, QLabel],
        help_fields: dict[str, tuple[QPushButton, QLabel]],
        notice: QLabel,
        changed: Callable[[], None],
        reset_origin: Callable[[], None],
    ) -> None:
        self.controls, self.badges, self.notice = controls, badges, notice
        self.changed, self.reset_origin = changed, reset_origin
        self.applying = False
        self.manual: dict[str, str] = {}
        self.detected: dict[str, UnitDefault] = {}
        self.defaults = {
            title: control.currentData() or control.currentText()
            for title, control in controls.items()
        }
        self.descriptions = {title: help_fields[title][1] for title in badges}
        self.base_help = {
            title: description.text() for title, description in self.descriptions.items()
        }
        for title, control in controls.items():
            control.currentTextChanged.connect(lambda _value, title=title: self.edited(title))
            control.activated.connect(lambda _index, title=title: self.edited(title))
        for title, description in self.descriptions.items():
            description.setOpenExternalLinks(False)
            description.linkActivated.connect(lambda url, title=title: self.follow_link(title, url))
        self.render()

    def edited(self, title: str) -> None:
        if not self.applying:
            self.mark_manual([title])

    def mark_manual(self, titles: Iterable[str], source: str = "Selected manually.") -> None:
        self.manual.update(dict.fromkeys(titles, source))
        self.render()

    def refresh(
        self, recordings: Mapping[str, pd.DataFrame], choices: Mapping[str, str | None]
    ) -> None:
        if self.applying:
            return
        self.detected.update(unit_defaults(recordings, choices))
        self.applying = True
        try:
            for title in self.controls.keys() - self.manual.keys():
                self._set_value(title, self.detected[title].value or self.defaults[title])
        finally:
            self.applying = False
        issues = list(dict.fromkeys(item.issue for item in self.detected.values() if item.issue))
        self.notice.setText(" ".join(issues))
        self.notice.setVisible(bool(issues))
        self.notice.setToolTip(
            tooltip_text(
                "Shared settings require consistent units. Normalize differing inputs or analyze them separately."
            )
        )
        self.render()

    def set_origin(self, clock: ClockMetadata | None) -> None:
        self.manual.pop("Time origin", None)
        self.detected["Time origin"] = UnitDefault(
            clock["origin"] if clock else None,
            f"Read from {clock['source']}. Origin: {clock['origin']}."
            if clock
            else "No calendar time origin is available from the selected input.",
        )
        self.render()

    def restore(self, title: str) -> None:
        if title == "Time origin":
            self.reset_origin()
            return
        detected = self.detected.get(title)
        if detected is None or detected.value is None:
            return
        self.manual.pop(title, None)
        self.applying = True
        try:
            self._set_value(title, detected.value)
        finally:
            self.applying = False
        self.render()
        self.changed()

    def _set_value(self, title: str, value: str) -> None:
        control = self.controls[title]
        index = control.findData(value)
        control.setCurrentIndex(index if index >= 0 else control.findText(value))

    def follow_link(self, title: str, url: str) -> None:
        if url == "use-file-value":
            self.restore(title)
        else:
            QDesktopServices.openUrl(QUrl(url))

    def render(self) -> None:
        for title, badge in self.badges.items():
            detected = self.detected.get(title)
            manual = self.manual.get(title)
            from_file = bool(detected and detected.value is not None and manual is None)
            badge.setVisible(from_file)
            detail = self._detail(title, detected, manual)
            badge.setToolTip(tooltip_text(detail) if from_file else "")
            badge.setAccessibleDescription(detail)
            source = f"<p><b>Current value source:</b> {escape(detail)}</p>"
            if manual and ((detected and detected.value is not None) or title == "Time origin"):
                source += (
                    f'<p><a style="color: {LINK_COLOR}; text-decoration: underline;" '
                    'href="use-file-value">Use file value</a></p>'
                )
            self.descriptions[title].setText(self.base_help[title] + source)
            if title in self.controls:
                self.controls[title].setAccessibleDescription(detail)

    def _detail(self, title: str, detected: UnitDefault | None, manual: str | None) -> str:
        if manual:
            if title != "Time origin" and detected and detected.value is not None:
                return f"{manual} File value: {detected.value}. {detected.detail}"
            return manual
        if detected and detected.value is not None:
            return detected.detail
        fallback = detected.detail if detected else "Open a recording to read available metadata."
        return f"App default. {fallback}" if title in self.controls else fallback
