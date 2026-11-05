"""Real file/folder selection, navigation and modal batch import."""

import time
from pathlib import Path

import pandas as pd
import pytest
from conftest import wait_for_job, wait_for_previews
from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from paradigma_studio.ui.recording_browser import RecordingBrowser


def wait_for_entries(browser, names):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        QApplication.processEvents()
        parent = browser.entries.rootIndex()
        found = {
            browser.model.fileName(browser.model.index(row, 0, parent))
            for row in range(browser.model.rowCount(parent))
        }
        if found == set(names):
            browser.entries.doItemsLayout()
            QApplication.processEvents()
            return
        time.sleep(0.01)
    assert found == set(names)


def select_paths(browser, paths):
    browser.entries.clearSelection()
    for path in paths:
        index = browser.model.index(str(path))
        assert index.isValid()
        browser.entries.selectionModel().select(
            index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        )


@pytest.fixture
def browser(window, tmp_path):
    for name in ("one.csv", "two.CWA", "IMU_meta.JSON", "ignored.json", "IMU_time.bin"):
        (tmp_path / name).touch()
    for name in ("folder A", "folder B"):
        (tmp_path / name).mkdir()
    (tmp_path / "folder A" / "nested.parquet").touch()
    dialog = RecordingBrowser(window, str(tmp_path))
    dialog.show()
    wait_for_entries(dialog, ["folder A", "folder B", "one.csv", "two.CWA", "IMU_meta.JSON"])
    yield dialog
    dialog.close()
    dialog.deleteLater()


@pytest.mark.parametrize(
    "names,summary",
    [
        (["one.csv", "two.CWA"], "2 files selected."),
        (["folder A", "folder B"], "2 folders selected."),
        (["one.csv", "folder A", "folder B"], "1 file and 2 folders selected."),
    ],
    ids=["files", "folders", "mixed"],
)
def test_browser_accepts_each_selection_with_a_fixed_load_button(browser, tmp_path, names, summary):
    assert browser.load_button.text() == "Load" and not browser.load_button.isEnabled()
    paths = [tmp_path / name for name in names]
    select_paths(browser, paths)
    assert browser.summary.text() == summary
    assert browser.load_button.text() == "Load" and browser.load_button.isEnabled()
    browser.load_button.click()
    assert browser.result() == QDialog.DialogCode.Accepted
    assert set(browser._paths) == set(paths)
    assert all(path.exists() for path in paths)


def test_ctrl_and_shift_clicks_select_multiple_folders_and_a_file(browser, tmp_path):
    def click(name, modifiers=Qt.KeyboardModifier.NoModifier):
        index = browser.model.index(str(tmp_path / name))
        browser.entries.scrollTo(index)
        QTest.mouseClick(
            browser.entries.viewport(),
            Qt.MouseButton.LeftButton,
            modifiers,
            browser.entries.visualRect(index).center(),
        )

    click("folder A")
    click("folder B", Qt.KeyboardModifier.ShiftModifier)
    click("one.csv", Qt.KeyboardModifier.ControlModifier)
    assert browser.summary.text() == "1 file and 2 folders selected."
    assert browser.load_button.isEnabled() and browser.load_button.text() == "Load"


def test_folder_activation_navigates_without_loading_and_clears_selection(browser, tmp_path):
    select_paths(browser, [tmp_path / "one.csv"])
    index = browser.model.index(str(tmp_path / "folder A"))
    QTest.mouseClick(
        browser.entries.viewport(),
        Qt.MouseButton.LeftButton,
        pos=browser.entries.visualRect(index).center(),
    )
    QTest.mouseDClick(
        browser.entries.viewport(),
        Qt.MouseButton.LeftButton,
        pos=browser.entries.visualRect(index).center(),
    )
    wait_for_entries(browser, ["nested.parquet"])
    assert Path(browser.directory) == tmp_path / "folder A"
    assert browser.isVisible() and browser.result() != QDialog.DialogCode.Accepted
    assert not browser.load_button.isEnabled()
    browser.back_button.click()
    wait_for_entries(browser, ["folder A", "folder B", "one.csv", "two.CWA", "IMU_meta.JSON"])
    assert Path(browser.directory) == tmp_path
    browser.up_button.click()
    assert Path(browser.directory) == tmp_path.parent


def test_location_entry_supports_spaces_and_reports_unavailable_folders(browser, tmp_path):
    browser.focus_location()
    browser.location.setText(str(tmp_path / "folder A"))
    QTest.keyClick(browser.location, Qt.Key.Key_Return)
    wait_for_entries(browser, ["nested.parquet"])
    assert browser.isVisible() and not browser.load_button.isEnabled()
    select_paths(browser, [tmp_path / "folder A" / "nested.parquet"])
    browser.location.setText(str(tmp_path / "missing"))
    browser.go_button.click()
    assert Path(browser.directory) == tmp_path / "folder A"
    assert "unavailable" in browser.summary.text() and not browser.load_button.isEnabled()
    browser.location.setText("..")
    browser.go_button.click()
    assert Path(browser.directory) == tmp_path
    browser.computer_button.click()
    assert browser.directory == "" and not browser.up_button.isEnabled()
    browser.go_back()
    assert Path(browser.directory) == tmp_path


def test_escape_cancels_even_with_a_valid_mixed_selection(browser, tmp_path):
    select_paths(browser, [tmp_path / "one.csv", tmp_path / "folder B"])
    QTest.keyClick(browser, Qt.Key.Key_Escape)
    assert browser.result() == QDialog.DialogCode.Rejected and browser._paths == ()
    assert not browser.isVisible()


@pytest.mark.parametrize("name", ["$BROWSER_LITERAL", "%BROWSER_LITERAL%"])
def test_folder_names_remain_literal_when_an_environment_variable_matches(
    browser, tmp_path, monkeypatch, name
):
    monkeypatch.setenv("BROWSER_LITERAL", "another_location")
    folder = tmp_path / name
    folder.mkdir()
    browser.navigate(str(folder))
    assert Path(browser.directory) == folder


def test_real_modal_browser_loads_files_and_multiple_folders_and_remembers_location(
    window, tmp_path
):
    root = tmp_path / "inputs"
    root.mkdir()
    frame = pd.DataFrame({"time": [0.0, 1.0, 2.0], "gyroscope_x": [1.0, 2.0, 3.0]})
    window.loaded(("previous.csv", frame.copy()))
    wait_for_previews(window)
    direct = root / "direct.csv"
    frame.to_csv(direct, index=False)
    for name in ("folder A", "folder B"):
        folder = root / name
        folder.mkdir()
        frame.to_csv(folder / "sensor.csv", index=False)
    window._data_controller._browser_directory = str(tmp_path)
    failures = []

    def choose_mixed():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, RecordingBrowser)
            dialog.navigate(str(root))
            wait_for_entries(dialog, ["direct.csv", "folder A", "folder B"])
            select_paths(dialog, [direct, root / "folder A", root / "folder B"])
            dialog.load_button.click()
        except (AssertionError, AttributeError) as error:
            failures.append(str(error))
            if isinstance(dialog, QDialog):
                dialog.reject()

    QTimer.singleShot(0, choose_mixed)
    window.open_button.click()
    assert not failures
    wait_for_job(window)
    wait_for_previews(window)
    assert len(window._input_state.recordings) == 3
    for loaded in window._input_state.recordings.values():
        pd.testing.assert_frame_equal(loaded, frame)
    assert Path(window._data_controller._browser_directory) == root
    assert_reopens_via_shortcuts(window, root)
    assert len(window._input_state.recordings) == 3


def assert_reopens_via_shortcuts(window, root):
    failures = []
    reopened = []

    def cancel_reopened():
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            return
        try:
            assert isinstance(dialog, RecordingBrowser)
            assert Path(dialog.directory) == root
            reopened.append(dialog.directory)
        except (AssertionError, AttributeError) as error:
            failures.append(str(error))
        finally:
            if isinstance(dialog, QDialog):
                dialog.reject()

    timer = QTimer(window)
    timer.setInterval(5)
    timer.timeout.connect(cancel_reopened)
    for count, modifiers in enumerate(
        (
            Qt.KeyboardModifier.ControlModifier,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        ),
        start=1,
    ):
        window.activateWindow()
        assert QTest.qWaitForWindowActive(window)
        timer.start()
        try:
            QTest.keyClick(window, Qt.Key.Key_O, modifiers)
        finally:
            timer.stop()
        QApplication.processEvents()
        assert not failures and len(reopened) == count


@pytest.mark.parametrize("style,font_size", [("Fusion", 13), ("Windows", 18)])
def test_browser_controls_fit_compact_windows(window, tmp_path, style, font_size):
    app = QApplication.instance()
    original = app.style().objectName()
    app.setStyle(style)
    window.setStyleSheet(window.styleSheet() + f"\nQWidget {{ font-size: {font_size}px; }}")
    dialog = RecordingBrowser(window, str(tmp_path))
    try:
        dialog.resize(760, 520)
        dialog.show()
        app.processEvents()
        assert dialog.size().toTuple() == (760, 520)
        for control in (
            dialog.location,
            dialog.go_button,
            dialog.cancel_button,
            dialog.load_button,
        ):
            assert control.visibleRegion().boundingRect().contains(control.rect())
    finally:
        dialog.close()
        dialog.deleteLater()
        app.setStyle(original)
