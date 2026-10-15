"""Construct graph widgets on first use, without importing the plotting stack at launch."""

from collections.abc import Callable

from PySide6.QtWidgets import QWidget


class DeferredWidget(QWidget):
    """Keep a tab's place in the layout until it is shown or explicitly accessed."""

    def __init__(self, initialize: Callable[[], None], parent=None):
        super().__init__(parent)
        self._initialize = initialize
        self.initialized = False

    def initialize(self):
        if self.initialized:
            return
        # Builders may access an attribute they have already installed. Mark
        # initialization before calling them so that access cannot reenter it.
        self.initialized = True
        try:
            self._initialize()
        except Exception:
            self.initialized = False
            raise

    def showEvent(self, event):
        self.initialize()
        super().showEvent(event)


class deferred_attribute:
    """Preserve the window's graph API while its widgets are built on demand.

    The builder assigns the real attribute to the window, replacing this
    non-data descriptor. Subsequent reads have no dispatch overhead.
    """

    def __init__(self, widget_name: str):
        self.widget_name = widget_name

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, window, owner=None):
        if window is None:
            return self
        getattr(window, self.widget_name).initialize()
        return vars(window)[self.name]
