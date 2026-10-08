"""Opening help must not reflow the Analyze labels, options or action buttons."""
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest

from paradigma_desktop.app import MainWindow


@pytest.mark.parametrize('size', [(1450, 920), (960, 650)])
@pytest.mark.parametrize('native_height, native_width', [(0, 0), (44, 0), (30, 280), (44, 280)])
def test_all_analysis_labels_and_fields_stay_fixed_when_any_help_opens(tmp_path, size, native_height, native_width):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.resize(*size)
    fields = [window.side, window.acc, window.gyro, window.time, window.orientation,
              window.mapping, window.max_gap, window.min_segment, window.clock_input,
              window.prepared, window.gaps, window.drop_missing, *window.module_buttons.values()]
    for control in fields[:5]:
        control.setMinimumHeight(native_height)
        if native_width:
            control.setMinimumWidth(native_width)
    if native_width:
        for label in window.analysis_parameter_fields.findChildren(QLabel):
            label.setMinimumHeight(28)
    window.navigate(1)
    window.show()
    app.processEvents()
    body = window.analysis_scroll.widget()
    labels = [widget for widget in body.findChildren(QLabel)
              if not window.analysis_help_panel.isAncestorOf(widget)]
    widgets = [*fields, *labels, *[info for info, _ in window.analysis_help.values()]]
    def positions():
        app.processEvents()
        return [(widget.mapTo(body, QPoint(0, 0)).x(), widget.mapTo(body, QPoint(0, 0)).y(),
                 widget.width(), widget.height()) for widget in widgets]
    baseline = positions()
    # Wrapped native fields still fit completely inside their form, including
    # the final rows; scrolling cannot reveal a clipped child of the form.
    for widget in fields:
        if window.analysis_parameter_fields.isAncestorOf(widget):
            bottom = widget.mapTo(window.analysis_parameter_fields, QPoint(0, widget.height())).y()
            assert bottom <= window.analysis_parameter_fields.height()
    center = window.mapping.mapTo(body, window.mapping.rect().center())
    window.analysis_scroll.ensureVisible(center.x(), center.y(), 0, window.mapping.height() // 2 + 8)
    app.processEvents()
    assert window.mapping.visibleRegion().boundingRect().contains(window.mapping.rect())
    actions = [window.run_button.pos(), window.stop_button.pos()]
    try:
        for title, (info, description) in window.analysis_help.items():
            info.click()
            QTest.qWait(20)
            assert positions() == baseline, title
            assert [window.run_button.pos(), window.stop_button.pos()] == actions
            assert description.isVisible()
            info.click()
            QTest.qWait(20)
            assert positions() == baseline, title
        for info, _ in window.analysis_help.values():
            info.click()
            assert positions() == baseline
        for info, _ in window.analysis_help.values():
            info.click()
            assert positions() == baseline
    finally:
        window.close()
        app.processEvents()
