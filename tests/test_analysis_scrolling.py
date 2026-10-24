"""Field wheel gestures scroll pages without changing parameter values."""

import pandas as pd
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QDateTimeEdit,
    QScrollArea,
    QStyle,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)

from paradigma_studio.column_mapping import SIGNALS
from paradigma_studio.exports import ExportDialog
from paradigma_studio.field_scrolling import PageDateTimeEdit, PageDoubleSpinBox
from paradigma_studio.widgets import combo


def send_wheel(widget, *, trackpad=False, upward=False):
    position = widget.rect().center()
    event = QWheelEvent(
        QPointF(position),
        QPointF(widget.mapToGlobal(position)),
        QPoint(0, 40 if upward else -40) if trackpad else QPoint(),
        QPoint() if trackpad else QPoint(0, 120 if upward else -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate if trackpad else Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("trackpad", [False, True])
@pytest.mark.parametrize("upward", [False, True])
def test_wheel_over_analyze_dropdowns_scrolls_page_without_changing_values(
    window, focused, trackpad, upward
):
    window.loaded(("sensor.csv", pd.DataFrame({column: [0.0, 1.0] for column in SIGNALS})))
    window.set_modules(["gait", "tremor", "pulse_rate"])
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
        send_wheel(control, trackpad=trackpad, upward=upward)
        QApplication.processEvents()
        assert control.currentIndex() == selected, control.accessibleName()
        assert changes.count() == 0
        assert bar.value() < previous if upward else bar.value() > previous, (
            control.accessibleName()
        )
    # Checkboxes and nearby actions must not swallow page scrolling either.
    for control in (
        window.gaps,
        window.drop_missing,
        *window.mapping._inversions.values(),
        *window.section_reset_buttons.values(),
    ):
        bar.setValue(bar.maximum() // 2)
        previous = bar.value()
        checked = control.isChecked()
        clicks = QSignalSpy(control.clicked)
        send_wheel(control, trackpad=trackpad, upward=upward)
        assert control.isChecked() == checked and clicks.count() == 0
        assert bar.value() < previous if upward else bar.value() > previous


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


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("trackpad", [False, True])
@pytest.mark.parametrize("upward", [False, True])
def test_analyze_numeric_and_calendar_fields_scroll_page_including_their_text_editors(
    window, focused, trackpad, upward
):
    window.navigate(1)
    window.resize(960, 650)
    window.clock_input.setText("2026-10-23T12:34:56.123456789")
    QTest.qWait(40)
    bar = window.analysis_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    fields = (window.max_gap, window.min_segment, window.clock_input.calendar)
    for field in fields:
        for receiver in (field, field.lineEdit()):
            receiver.setFocus() if focused else window.analysis_scroll.setFocus()
            assert receiver.hasFocus() == focused
            bar.setValue(bar.maximum() // 2)
            previous = bar.value()
            calendar = isinstance(field, QDateTimeEdit)
            value = field.dateTime() if calendar else field.value()
            changes = QSignalSpy(field.dateTimeChanged if calendar else field.valueChanged)
            text = window.clock_input.text()
            send_wheel(receiver, trackpad=trackpad, upward=upward)
            QApplication.processEvents()
            assert (field.dateTime() if calendar else field.value()) == value
            assert window.clock_input.text() == text
            assert changes.count() == 0
            assert bar.value() < previous if upward else bar.value() > previous, (
                field.accessibleName()
            )


@pytest.mark.parametrize("trackpad", [False, True])
def test_other_dropdowns_do_not_change_with_wheel_even_without_a_scrollable_page(window, trackpad):
    selector = combo(["first", "second", "third"])
    selector.setParent(window)
    selector.show()
    selector.setFocus()
    changes = QSignalSpy(selector.currentIndexChanged)
    send_wheel(selector, trackpad=trackpad)
    assert selector.currentText() == "first"
    assert changes.count() == 0


@pytest.mark.parametrize("trackpad", [False, True])
def test_shared_fields_discover_the_surrounding_page_and_keep_keyboard_and_click_edits(
    window, trackpad
):
    scroll = QScrollArea(window)
    scroll.setWidgetResizable(True)
    body = QWidget()
    layout = QVBoxLayout(body)
    selector, number, calendar = combo(["first", "second"]), PageDoubleSpinBox(), PageDateTimeEdit()
    number.setValue(10)
    calendar.setDisplayFormat("dd MMM yyyy HH:mm:ss")
    for field in (selector, number, calendar):
        layout.addWidget(field)
    body.setMinimumHeight(1200)
    scroll.setWidget(body)
    scroll.setGeometry(0, 0, 500, 300)
    scroll.show()
    QTest.qWait(20)
    bar = scroll.verticalScrollBar()
    for field in (selector, number, calendar):
        bar.setValue(0)
        before = field.text() if field is not selector else field.currentText()
        send_wheel(field, trackpad=trackpad)
        assert bar.value() > 0
        assert (field.text() if field is not selector else field.currentText()) == before
    scroll.ensureWidgetVisible(number)
    number.setFocus()
    QTest.keyClick(number, Qt.Key.Key_Up)
    assert number.value() == 11
    option = QStyleOptionSpinBox()
    number.initStyleOption(option)
    up = number.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, number
    )
    QTest.mouseClick(number, Qt.MouseButton.LeftButton, pos=up.center())
    assert number.value() == 12
    selector.setFocus()
    QTest.keyClick(selector, Qt.Key.Key_Down)
    assert selector.currentText() == "second"
    scroll.ensureWidgetVisible(calendar)
    calendar.setFocus()
    calendar.setCurrentSection(QDateTimeEdit.Section.SecondSection)
    before = calendar.dateTime()
    QTest.keyClick(calendar, Qt.Key.Key_Up)
    assert calendar.dateTime() == before.addSecs(1)
    scroll.deleteLater()


def test_export_format_cannot_change_accidentally_with_the_wheel(window, tremor_outputs):
    dialog = ExportDialog(tremor_outputs, window)
    dialog.show()
    QTest.qWait(20)
    before = dialog.format.currentText()
    dialog.format.setFocus()
    send_wheel(dialog.format)
    assert dialog.format.currentText() == before
    dialog.close()


@pytest.mark.parametrize("trackpad", [False, True])
@pytest.mark.parametrize("state", ["disabled", "page_end"])
def test_disabled_fields_and_page_boundaries_never_turn_wheel_gestures_into_edits(
    window, trackpad, state
):
    window.navigate(1)
    window.resize(960, 650)
    window.clock_input.setText("2026-10-23T12:34:56.123456789")
    QTest.qWait(30)
    bar = window.analysis_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    for field in (window.time, window.max_gap, window.clock_input.calendar):
        field.setEnabled(state != "disabled")
        before = window.time.currentText(), window.max_gap.value(), window.clock_input.text()
        bar.setValue(0 if state == "disabled" else bar.maximum())
        send_wheel(field, trackpad=trackpad)
        QApplication.processEvents()
        assert (
            window.time.currentText(),
            window.max_gap.value(),
            window.clock_input.text(),
        ) == before
        assert bar.value() > 0 if state == "disabled" else bar.value() == bar.maximum()


@pytest.mark.parametrize("trackpad", [False, True])
@pytest.mark.parametrize("graphs", [1, 6])
def test_pinned_graph_fields_scroll_the_graph_page_without_changing_view_or_limits(
    window, trackpad, graphs
):
    frame = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0], **{f"metric_{i}": [2.0, 3.0, 4.0] for i in range(graphs)}}
    )
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.CheckState.Checked)
    window.result_series.blockSignals(False)
    window.plot()
    if graphs == 1:
        window.results_header.setMinimumHeight(350)
        window.resize(960, 650)
    QTest.qWait(30)
    window.plot_toolbar.settings_action.setChecked(True)
    _, lower, _ = window.plot_toolbar.settings.bounds["x"]
    lower.setEnabled(True)
    for field in (window.result_graph_view, lower):
        if graphs == 1:
            assert window.graph_scroll.verticalScrollBar().maximum() == 0
        page = window._result_state.results_scroll if graphs == 1 else window.graph_scroll
        bar = page.verticalScrollBar()
        bar.setValue(0)
        assert bar.maximum() > 0
        text = field.text() if field is lower else field.currentText()
        limits = [axes.get_xlim() for axes in window.figure.axes]
        field.setFocus()
        send_wheel(field, trackpad=trackpad)
        QApplication.processEvents()
        assert bar.value() > 0
        assert (field.text() if field is lower else field.currentText()) == text
        assert [axes.get_xlim() for axes in window.figure.axes] == limits
