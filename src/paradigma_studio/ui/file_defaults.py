"""Compact provenance for Analyze values supplied by supported sensor files."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from html import escape
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from ..input_metadata import UnitDefault, unit_defaults
from ..theme import tooltip_text

if TYPE_CHECKING:
    import pandas as pd

    from ..contracts import ClockMetadata


class FileDefaults:
    """Apply consensus values until explicitly edited; explain every value's source."""

    def __init__(
        self,
        controls: dict[str, QComboBox],
        badges: dict[str, QLabel],
        buttons: dict[str, QPushButton],
        help_fields: dict[str, tuple[QPushButton, QLabel]],
        notice: QLabel,
        restored: Callable[[str, bool], None],
    ) -> None:
        self.controls, self.badges, self.notice = controls, badges, notice
        self.buttons = buttons
        self.restored = restored
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
        for title, reset in buttons.items():
            reset.clicked.connect(lambda _checked=False, title=title: self.restore(title))
        self.render()

    def edited(self, title: str) -> None:
        if not self.applying:
            self.mark_manual([title])

    def mark_manual(self, titles: Iterable[str], source: str = "Selected manually.") -> None:
        self.manual.update(dict.fromkeys(titles, source))
        self.render()

    def reset(self) -> None:
        """Clear provenance and edits while the owner blocks reset signals."""
        self.manual.clear()
        self.detected.clear()
        for title, value in self.defaults.items():
            self._set_value(title, value)
        self.notice.clear()
        self.notice.setToolTip("")
        self.notice.hide()
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
        detected = self.detected.get(title)
        if detected is None or detected.value is None:
            return
        control = self.controls[title]
        previous = control.currentData() or control.currentText()
        self.manual.pop(title, None)
        self.applying = True
        try:
            self._set_value(title, detected.value)
        finally:
            self.applying = False
        self.render()
        changed = (control.currentData() or control.currentText()) != previous
        self.restored(title, changed)

    def _set_value(self, title: str, value: str) -> None:
        control = self.controls[title]
        index = control.findData(value)
        control.setCurrentIndex(index if index >= 0 else control.findText(value))

    def render(self) -> None:
        for title, badge in self.badges.items():
            detected = self.detected.get(title)
            from_file, detail = self.value_source(title)
            badge.setVisible(from_file)
            badge.setToolTip(tooltip_text(detail) if from_file else "")
            badge.setAccessibleDescription(detail)
            source = f"<p><b>Current value source:</b> {escape(detail)}</p>"
            if title in self.buttons:
                reset = self.buttons[title]
                available = bool(detected and detected.value is not None)
                reset.setVisible(available)
                reset.setToolTip(
                    tooltip_text(f"Restore the file value. {detected.detail}")
                    if available and detected
                    else ""
                )
            self.descriptions[title].setText(self.base_help[title] + source)
            if title in self.controls:
                self.controls[title].setAccessibleDescription(detail)

    def value_source(self, title: str) -> tuple[bool, str]:
        detected, manual = self.detected.get(title), self.manual.get(title)
        return (
            bool(detected and detected.value is not None and manual is None),
            self._detail(title, detected, manual),
        )

    def _detail(self, title: str, detected: UnitDefault | None, manual: str | None) -> str:
        if manual:
            if title != "Time origin" and detected and detected.value is not None:
                return f"{manual} File value: {detected.value}. {detected.detail}"
            return manual
        if detected and detected.value is not None:
            return detected.detail
        fallback = detected.detail if detected else "Open a recording to read available metadata."
        return f"App default. {fallback}" if title in self.controls else fallback
