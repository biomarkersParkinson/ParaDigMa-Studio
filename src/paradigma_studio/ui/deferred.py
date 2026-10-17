"""Construct graph widgets on first use, without importing the plotting stack at launch."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from PySide6.QtGui import QShowEvent


class DeferredWidget(QWidget):
    """Keep a tab's place in the layout until it is shown or explicitly accessed."""

    def __init__(self, initialize: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._initialize = initialize
        self.initialized = False

    def initialize(self) -> None:
        if self.initialized:
            return
        # Builders may access an attribute they have already installed. Mark
        # initialization before calling them so that access cannot reenter it.
        self.initialized = True
        initialized = False
        try:
            self._initialize()
            initialized = True
        finally:
            self.initialized = initialized

    def showEvent(self, event: QShowEvent) -> None:
        self.initialize()
        super().showEvent(event)


class deferred_attribute:
    """Preserve the window's graph API while its widgets are built on demand.

    The builder assigns the real attribute to the window, replacing this
    non-data descriptor. Subsequent reads have no dispatch overhead.
    """

    def __init__(self, widget_name: str) -> None:
        self.widget_name = widget_name

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, window: Any, owner: type | None = None) -> Any:
        if window is None:
            return self
        getattr(window, self.widget_name).initialize()
        return vars(window)[self.name]
