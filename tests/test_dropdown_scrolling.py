"""Long dropdowns expose a draggable scrollbar and preserve selection while scrolling."""

import pandas as pd
import pytest
from conftest import wait_for_previews
from gui_helpers import dispose_widget, wait_until
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider, QVBoxLayout, QWidget

from paradigma_studio import app as desktop
from paradigma_studio.theme import STYLESHEET
from paradigma_studio.widgets import combo


@pytest.fixture(params=["Fusion", "Windows"])
def selector(qt_app, request):
    original = qt_app.style().objectName()
    changed = original.casefold() != request.param.casefold()
    if changed:
        qt_app.setStyle(request.param)
    parent = QWidget()
    parent.setStyleSheet(STYLESHEET)
    layout = QVBoxLayout(parent)
    control = combo([f"recording_{index:03d}.csv" for index in range(100)])
    layout.addWidget(control)
    parent.resize(420, 160)
    parent.show()
    qt_app.processEvents()
    try:
        yield control
    finally:
        control.hidePopup()
        dispose_widget(parent)
        if changed:
            qt_app.setStyle(original)


def open_long_popup(control):
    control.showPopup()
    view = control.view()
    bar = view.verticalScrollBar()
    wait_until(lambda: bar.isVisible() and bar.maximum() > 0)
    assert view.height() < control.count() * view.sizeHintForRow(0)
    return view, bar


def test_long_popup_scrollbar_can_be_dragged_then_an_item_selected(selector):
    view, bar = open_long_popup(selector)
    option = QStyleOptionSlider()
    bar.initStyleOption(option)
    handle = bar.style().subControlRect(
        QStyle.ComplexControl.CC_ScrollBar, option, QStyle.SubControl.SC_ScrollBarSlider, bar
    )
    start = handle.center()
    end = start + QPoint(0, min(120, bar.height() // 2))
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(bar, end, delay=10)
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=end)
    assert bar.value() > 0 and selector.currentIndex() == 0
    QTest.keyClick(view, Qt.Key.Key_End)
    QApplication.processEvents()
    last = selector.model().index(selector.count() - 1, 0)
    point = view.visualRect(last).center()
    assert view.viewport().rect().contains(point)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert selector.currentIndex() == selector.count() - 1
    assert not view.isVisible()


@pytest.mark.parametrize("pixels", [False, True], ids=["mouse-wheel", "trackpad"])
def test_open_popup_wheel_scrolls_the_list_before_keyboard_selection(selector, pixels):
    view, bar = open_long_popup(selector)
    point = QPoint(30, 30)
    event = QWheelEvent(
        QPointF(point),
        QPointF(view.viewport().mapToGlobal(point)),
        QPoint(0, -37) if pixels else QPoint(),
        QPoint() if pixels else QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate if pixels else Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(view.viewport(), event)
    assert bar.value() > 0 and selector.currentIndex() == 0
    QTest.keyClick(view, Qt.Key.Key_End)
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert selector.currentIndex() == selector.count() - 1
    assert not view.isVisible()


def test_short_popup_has_no_unnecessary_scrollbar(selector):
    selector.clear()
    selector.addItems(["first", "second", "third"])
    selector.showPopup()
    QApplication.processEvents()
    bar = selector.view().verticalScrollBar()
    assert bar.maximum() == 0 and not bar.isVisible()


def test_data_recording_popup_reaches_the_last_recording_in_a_large_batch(window):
    frame = pd.DataFrame({"time": [0.0, 1.0, 2.0], "gyroscope_x": [1.0, 2.0, 3.0]})
    frames = {f"recording_{index:03d}": frame.copy() for index in range(100)}
    sources = {key: f"session_{index:03d}.csv" for index, key in enumerate(frames)}
    descriptions = {
        key: desktop.inspect_recording(value, "relative_s") for key, value in frames.items()
    }
    window.loaded_recordings((sources, frames, descriptions))
    wait_for_previews(window)
    window.resize(960, 650)
    view, _bar = open_long_popup(window.input_recording)
    assert window.input_recording.count() == 100
    QTest.keyClick(view, Qt.Key.Key_End)
    QTest.keyClick(view, Qt.Key.Key_Return)
    last = next(reversed(frames))
    assert window.input_recording.currentData() == last
    assert window._input_state.frame is frames[last]
    assert window._input_state.source == sources[last]
    assert window.size().toTuple() == (960, 650)
    wait_for_previews(window)
