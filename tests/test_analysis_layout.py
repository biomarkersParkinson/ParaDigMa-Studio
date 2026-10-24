"""Analyze layout, compact-window reachability and native control regressions."""

import pandas as pd
import pytest
from analysis_helpers import assert_fully_visible, configure_native_analysis_sizes
from conftest import wait_for_job
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from paradigma_studio.app import MainWindow
from paradigma_studio.theme import LINK_COLOR


@pytest.fixture(params=[None, "Windows"], ids=["native-style", "Windows-style"])
def native_analysis_window(tmp_path, request):
    app = QApplication.instance() or QApplication([])
    original_style = app.style().objectName()
    if request.param is not None:
        app.setStyle(request.param)
    widget = MainWindow(history_dir=tmp_path / "runs")
    try:
        yield widget
    finally:
        wait_for_job(widget)
        widget.close()
        app.processEvents()
        app.setStyle(original_style)


def test_run_button_remains_visible_in_compact_analysis_workspace(window):
    app = QApplication.instance()
    window.navigate(1)
    window.sidebar.setExpanded(False, animated=False)
    window.resize(1050, 720)
    window.show()
    app.processEvents()
    assert window.run_button.isVisible()
    assert window.run_button.parentWidget() is window.status_row
    assert not window.pages.widget(1).isAncestorOf(window.run_button)
    assert window.run_button.geometry().bottom() < window.status_row.height()
    assert (
        window.run_button.mapTo(window, window.run_button.rect().center()).y()
        == window.status.mapTo(window, window.status.rect().center()).y()
    )


@pytest.mark.parametrize(
    "control_minimum_height, larger_surrounding_controls",
    [(0, False), (40, False), (44, False), (44, True)],
)
def test_analysis_preserves_spacing_accessible_fields_and_uniform_help_across_window_sizes(
    native_analysis_window, control_minimum_height, larger_surrounding_controls
):
    window = native_analysis_window
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0.0, 1.0], "gyroscope_x": [1.0, 2.0]})))
    window.set_modules(["gait", "tremor", "pulse_rate"])
    configure_native_analysis_sizes(window, control_minimum_height, larger_surrounding_controls)
    window.navigate(1)
    # The mapping table adds rows; larger native labels/buttons need more height
    # for this all-visible check, within the 1080-pixel offscreen desktop.
    # Compact-window reachability is checked below.
    window.resize(1200, 1050 if larger_surrounding_controls else 900)
    window.show()
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() == 0, (
        window.analysis_scroll.viewport().size(),
        window.analysis_scroll.widget().size(),
        window.analysis_scroll.widget().minimumSize(),
        window.analysis_controls.size(),
        window.analysis_controls.heightForWidth(window.analysis_controls.width()),
    )
    controls = (
        window.side,
        window.acc,
        window.gyro,
        window.time,
        window.drop_missing,
        window.gaps,
        window.max_gap,
        window.min_segment,
        window.mapping,
        *window.section_reset_buttons.values(),
    )
    for control in controls:
        assert_fully_visible(control)
    for previous, following in zip(
        (window.side, window.acc, window.gyro), (window.acc, window.gyro, window.time), strict=False
    ):
        bottom = previous.mapTo(window.settings_panel, QPoint(0, previous.height())).y()
        top = following.mapTo(window.settings_panel, QPoint(0, 0)).y()
        assert top - bottom >= 8, "Parameter rows must retain comfortable separation"
    help_buttons = [info for info, description in window.analysis_help.values()]
    assert {(info.width(), info.height()) for info in help_buttons} == {(22, 22)}
    assert all(info.objectName() == "helpInfo" and info.isCheckable() for info in help_buttons)
    # Small windows may scroll rather than compressing controls and whitespace.
    # Every field remains reachable and the action stays outside the scroll area.
    window.resize(960, 650)
    QTest.qWait(30)
    small_scroll_maximum = window.analysis_scroll.verticalScrollBar().maximum()
    if larger_surrounding_controls:
        assert small_scroll_maximum > 0
    for control in controls:
        # Text editors' ensureWidgetVisible follows their cursor rectangle;
        # scroll the whole control into view to check complete accessibility.
        center = control.mapTo(window.analysis_scroll.widget(), control.rect().center())
        window.analysis_scroll.ensureVisible(center.x(), center.y(), 0, control.height() // 2 + 8)
        QApplication.instance().processEvents()
        assert_fully_visible(control)
        assert_fully_visible(window.run_button)
    for info in help_buttons:
        info.click()
        assert sum(button.isChecked() for button in help_buttons) == 1
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() > small_scroll_maximum
    for info in help_buttons:
        if info.isChecked():
            info.click()
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() == small_scroll_maximum
    assert window.analysis_help_panel.isHidden()
    window.resize(1200, 1050 if larger_surrounding_controls else 900)
    QTest.qWait(30)
    assert window.analysis_scroll.verticalScrollBar().maximum() == 0


def test_axis_and_mapping_fields_follow_their_columns_with_readable_official_guide(window):
    window.navigate(1)
    window.resize(1450, 920)
    QTest.qWait(30)
    fields = [window.side, window.acc, window.gyro, window.time]
    assert len({field.mapTo(window, field.rect().topLeft()).x() for field in fields}) == 1
    mapping_right = window.mapping.mapTo(window, window.mapping.rect().topRight()).x()
    for field in (
        *fields,
        window.clock_input,
        window.drop_missing,
        window.gaps,
        window.max_gap,
        window.min_segment,
        *window.section_reset_buttons.values(),
    ):
        assert field.mapTo(window, field.rect().topLeft()).x() > mapping_right
    assert window.drop_missing.mapTo(window, window.drop_missing.rect().topLeft()).y() > (
        window.time.mapTo(window, window.time.rect().bottomLeft()).y()
    )
    for _info, description in window.analysis_help.values():
        assert f"color: {LINK_COLOR}" in description.text()
    info, description = window.analysis_help["Signal columns"]
    info.click()
    assert '<img src="' in description.text() and "directions_axes.png" in description.text()
    assert (
        "https://biomarkersparkinson.github.io/paradigma/guides/coordinate_system.html"
        in description.text()
    )


def test_mapping_label_and_editor_stay_together_when_neighboring_help_expands(window):
    window.navigate(1)
    window.resize(1450, 920)
    heading = next(
        label
        for label in window.settings_panel.findChildren(QLabel)
        if label.text() == "Signal columns"
    )

    def positions():
        QTest.qWait(30)
        return heading.mapTo(window, heading.rect().topLeft()).y(), window.mapping.mapTo(
            window, window.mapping.rect().topLeft()
        ).y()

    initial = positions()
    for name in ("Watch side", "Minimum section duration", "Signal columns"):
        window.analysis_help[name][0].click()
        label_y, editor_y = positions()
        assert 0 <= editor_y - label_y - heading.height() <= 8
        assert editor_y - initial[1] == pytest.approx(label_y - initial[0], abs=2)


@pytest.mark.parametrize("editor_minimum_width", [0, 382])
def test_analyze_origin_calendar_remains_readable_at_windows_control_widths(
    window, editor_minimum_width
):
    field = window.clock_input
    field.calendar.setMinimumWidth(editor_minimum_width)
    field.seconds.setMinimumWidth(editor_minimum_width)
    window.navigate(1)
    window.resize(960, 720)
    QTest.qWait(50)
    window.analysis_scroll.ensureWidgetVisible(field, 0, 0)
    QTest.qWait(20)
    assert field.editors.currentWidget().height() >= 38
    assert (
        field.editors.currentWidget().width()
        >= field.editors.currentWidget().minimumSizeHint().width()
    )
    assert_fully_visible(field)
    assert window.analysis_scroll.isAncestorOf(field)
    assert not window.result_tabs.isAncestorOf(field)
