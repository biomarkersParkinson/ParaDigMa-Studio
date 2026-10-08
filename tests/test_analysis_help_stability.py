"""Opening help must not reflow the Analyze labels, options or action buttons."""
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest

from paradigma_desktop.app import MainWindow


@pytest.mark.parametrize('size', [(1450, 920), (960, 650)])
@pytest.mark.parametrize('native_height', [0, 44])
def test_all_analysis_labels_and_fields_stay_fixed_when_any_help_opens(tmp_path, size, native_height):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.resize(*size)
    fields = [window.side, window.acc, window.gyro, window.time, window.orientation,
              window.mapping, window.max_gap, window.min_segment, window.clock_input,
              window.prepared, window.gaps, window.drop_missing, *window.module_buttons.values()]
    for control in fields[:5]:
        control.setMinimumHeight(native_height)
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
