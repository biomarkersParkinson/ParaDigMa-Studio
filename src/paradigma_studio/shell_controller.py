"""Workspace navigation, notices and About dialog lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget, QTabWidget, QWidget

from .workspace_state import ShellState


@dataclass(frozen=True)
class ShellView:
    parent: QWidget
    continue_button: QPushButton
    data_tabs: QTabWidget
    nav_buttons: list[QPushButton]
    notice: QLabel
    page_title: QLabel
    pages: QStackedWidget
    run_button: QPushButton
    stop_button: QPushButton


@dataclass(frozen=True)
class ShellCallbacks:
    data_tab_changed: Callable[..., Any]


class ShellController(QObject):
    """Own shell behavior through explicit state, frozen views and callbacks."""

    def __init__(
        self,
        shell: ShellState,
        view: ShellView,
        callbacks: ShellCallbacks,
        sections: tuple[str, ...],
    ) -> None:
        super().__init__(view.parent)
        self.shell = shell
        self.view = view
        self.callbacks = callbacks
        self.sections = sections

    def navigate(self, index):
        self.view.pages.setCurrentIndex(index)
        self.view.continue_button.setVisible(index == 0)
        self.view.stop_button.setVisible(index == 1)
        self.view.run_button.setVisible(index == 1)
        self.view.page_title.setText(self.sections[index])
        for i, item in enumerate(self.view.nav_buttons):
            item.setChecked(i == index)
        if index == 0:
            self.callbacks.data_tab_changed(self.view.data_tabs.currentIndex())

    def show_acknowledgements(self):
        if getattr(self.shell, "_acknowledgements_dialog", None) is None:
            from .acknowledgements import AcknowledgementsDialog

            self.shell._acknowledgements_dialog = AcknowledgementsDialog(self.view.parent)
        self.shell._acknowledgements_dialog.show()
        self.shell._acknowledgements_dialog.raise_()
        self.shell._acknowledgements_dialog.activateWindow()

    def show_notice(self, message, severity="warning"):
        self.view.notice.setProperty("severity", severity)
        self.view.notice.style().unpolish(self.view.notice)
        self.view.notice.style().polish(self.view.notice)
        self.view.notice.setText(message)
        self.view.notice.setVisible(bool(message))
