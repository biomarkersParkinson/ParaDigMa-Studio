"""Analyze info buttons open readable help windows without changing settings."""

import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel

from paradigma_studio.input_metadata import METADATA_KEY
from paradigma_studio.ui.analysis_help_dialog import AnalysisHelpDialog


def test_info_buttons_open_one_reusable_non_modal_window_without_changing_the_page(window):
    window.navigate(1)
    window.resize(1450, 1000)
    QTest.qWait(30)
    view = window._analysis_controller.view
    body = window.analysis_scroll.widget()
    before = (
        body.size(),
        window.analysis_controls.size(),
        window.analysis_scroll.verticalScrollBar().maximum(),
    )
    for title, (info, description) in window.analysis_help.items():
        info.click()
        dialog = view.analysis_help_dialogs[title]
        assert isinstance(dialog, AnalysisHelpDialog)
        assert dialog.isVisible() and not dialog.isModal()
        assert description.window() is dialog and description.isVisible()
        assert title in dialog.windowTitle()
        assert info.accessibleName() == f"Information: {title}" and not info.isCheckable()
        assert sum(item.isVisible() for item in view.analysis_help_dialogs.values()) == 1
        info.click()
        assert dialog.isVisible()
        assert (
            body.size(),
            window.analysis_controls.size(),
            window.analysis_scroll.verticalScrollBar().maximum(),
        ) == before
    assert len(window.findChildren(AnalysisHelpDialog)) == len(window.analysis_help)


@pytest.mark.parametrize("close_method", ["button", "escape", "window"])
def test_help_closes_and_reopens_using_mouse_and_keyboard(window, close_method):
    window.navigate(1)
    info, description = window.analysis_help["Time units"]
    QTest.mouseClick(info, Qt.MouseButton.LeftButton)
    dialog = window._analysis_controller.view.analysis_help_dialogs["Time units"]
    assert dialog.isVisible()
    if close_method == "button":
        QTest.mouseClick(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Close), Qt.MouseButton.LeftButton
        )
    elif close_method == "escape":
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    else:
        dialog.close()
    assert not dialog.isVisible()
    info.setFocus()
    activated = QSignalSpy(info.clicked)
    QTest.keyClick(info, Qt.Key.Key_Space)
    assert activated.count() or activated.wait(1000)
    assert dialog.isVisible() and description.isVisible()


@pytest.mark.parametrize("style", ["Fusion", "Windows"])
@pytest.mark.parametrize("font_size", [13, 18])
def test_help_text_links_and_close_button_remain_reachable_in_compact_windows(
    window, style, font_size
):
    app = QApplication.instance()
    original_style = app.style().objectName()
    app.setStyle(style)
    window.setStyleSheet(window.styleSheet() + f"\nQWidget {{ font-size: {font_size}px; }}")
    window.navigate(1)
    try:
        for title, (info, description) in window.analysis_help.items():
            info.click()
            dialog = window._analysis_controller.view.analysis_help_dialogs[title]
            QTest.qWait(10)
            assert dialog.width() <= dialog.screen().availableGeometry().width()
            assert dialog.height() <= dialog.screen().availableGeometry().height()
            dialog.resize(500, 360)
            QTest.qWait(10)
            scroll = dialog.scroll_area
            assert scroll.horizontalScrollBar().maximum() == 0, title
            assert description.height() >= description.heightForWidth(description.width()), title
            close = dialog.buttons.button(QDialogButtonBox.StandardButton.Close)
            assert close.visibleRegion().boundingRect().contains(close.rect()), title
            link = next(
                label
                for label in dialog.findChildren(QLabel)
                if "ParaDigMa documentation" in label.text()
            )
            scroll.ensureWidgetVisible(link, 0, 0)
            app.processEvents()
            assert link.openExternalLinks()
            assert not link.visibleRegion().isEmpty()
            dialog.close()
    finally:
        app.setStyle(original_style)


def test_open_help_keeps_the_current_file_and_manual_value_source_up_to_date(window):
    frame = pd.DataFrame({"time": [0, 10, 20], "gyroscope_x": [2, 3, 4]})
    frame.attrs[METADATA_KEY] = {"format": "tsdf", "units": {"time": "relative_ms"}}
    window.loaded(("sensor.json", frame))
    window.navigate(1)
    info, description = window.analysis_help["Time units"]
    info.click()
    dialog = window._analysis_controller.view.analysis_help_dialogs["Time units"]
    assert "TSDF channel metadata" in description.text()
    window.time.setCurrentText("relative_s")
    assert dialog.isVisible()
    assert (
        "Selected manually" in description.text()
        and "File value: relative_ms" in description.text()
    )


def test_closing_the_main_window_hides_its_open_help(window):
    window.analysis_help["Signal columns"][0].click()
    dialog = window._analysis_controller.view.analysis_help_dialogs["Signal columns"]
    assert dialog.isVisible()
    window.close()
    QApplication.instance().processEvents()
    assert not dialog.isVisible()
