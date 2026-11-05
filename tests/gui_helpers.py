"""Small Qt fixtures use real widgets and bounded event delivery."""

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def dispose_widget(widget):
    """Delete owned widget trees before restoring styles or starting another case."""
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def wait_until(predicate, *, timeout=1000):
    """Wait for an observable UI condition, rather than a fixed settling delay."""
    timer = QElapsedTimer()
    timer.start()
    while True:
        QApplication.processEvents()
        if predicate():
            return
        assert not timer.hasExpired(timeout), "Qt condition did not settle within the timeout"
        QTest.qWait(10)
