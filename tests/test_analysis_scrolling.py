"""Analyze wheels move the page without changing closed dropdown selections."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from paradigma_studio.column_mapping import SIGNALS
from paradigma_studio.widgets import combo


def send_wheel(widget, *, trackpad=False):
    position = widget.rect().center()
    event = QWheelEvent(
        QPointF(position),
        QPointF(widget.mapToGlobal(position)),
        QPoint(0, -40) if trackpad else QPoint(),
        QPoint() if trackpad else QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate if trackpad else Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("trackpad", [False, True])
def test_wheel_over_analyze_dropdowns_scrolls_page_without_changing_values(
    window, focused, trackpad
):
    window.set_modules(["gait", "tremor", "pulse_rate"])
    window.mapping.set_recordings({"one": list(SIGNALS)}, {})
    window.navigate(1)
    window.resize(960, 650)
    QTest.qWait(40)
    bar = window.analysis_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    controls = (window.side, window.acc, window.gyro, window.time, *window.mapping._combos.values())
    for control in controls:
        control.setFocus() if focused else window.analysis_scroll.setFocus()
        assert control.hasFocus() == focused
        bar.setValue(bar.maximum() // 2)
        previous = bar.value()
        selected = control.currentIndex()
        changes = QSignalSpy(control.currentIndexChanged)
        send_wheel(control, trackpad=trackpad)
        QApplication.processEvents()
        assert control.currentIndex() == selected, control.accessibleName()
        assert changes.count() == 0
        assert bar.value() > previous, control.accessibleName()


def test_open_analyze_dropdown_list_scrolls_and_keyboard_selection_still_works(window):
    columns = [*SIGNALS, *(f"extra_{index}" for index in range(40))]
    window.mapping.set_recordings({"one": columns}, {})
    window.navigate(1)
    selector = window.mapping._combos["time"]
    selector.showPopup()
    QTest.qWait(30)
    try:
        view = selector.view()
        bar = view.verticalScrollBar()
        assert bar.maximum() > 0
        previous = bar.value()
        send_wheel(view.viewport())
        QTest.qWait(20)
        assert bar.value() > previous
    finally:
        selector.hidePopup()
    selected = window.time.currentIndex()
    changes = QSignalSpy(window.time.currentIndexChanged)
    window.time.setFocus()
    QTest.keyClick(window.time, Qt.Key.Key_Down)
    assert window.time.currentIndex() == selected + 1
    assert changes.count() == 1


def test_other_dropdowns_keep_normal_wheel_selection(window):
    selector = combo(["first", "second", "third"])
    selector.setParent(window)
    selector.show()
    selector.setFocus()
    changes = QSignalSpy(selector.currentIndexChanged)
    send_wheel(selector)
    assert selector.currentText() == "second"
    assert changes.count() == 1
