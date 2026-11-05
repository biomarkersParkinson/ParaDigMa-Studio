"""Platform dialog routing, menu actions and safe native-picker failures."""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from conftest import wait_for_job, wait_for_previews
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog

from paradigma_studio import data_controller
from paradigma_studio.ui import recording_dialogs, windows_folder_dialog


def test_files_use_standard_multi_file_dialog_and_supported_filters(window, monkeypatch):
    calls = []

    def choose(*args):
        calls.append(args)
        return (["one.csv", "two.CWA"], "")

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", choose)
    assert recording_dialogs.choose_recording_files(window, "C:/recordings") == [
        "one.csv",
        "two.CWA",
    ]
    assert calls[0][:3] == (window, "Open recording files for the same subject", "C:/recordings")
    assert "*.csv" in calls[0][3] and "*_meta.json" in calls[0][3]
    assert len(calls[0]) == 4  # No option forces Qt's non-native browser.


def test_windows_folders_use_system_multi_folder_picker(window, monkeypatch):
    calls = []
    monkeypatch.setattr(recording_dialogs, "sys", SimpleNamespace(platform="win32"))

    def choose(owner, directory):
        calls.append((owner, directory))
        return ["C:/recordings/a", "C:/recordings/b"]

    monkeypatch.setattr(windows_folder_dialog, "choose_windows_folders", choose)
    assert recording_dialogs.choose_recording_folders(window, "C:/recordings") == [
        "C:/recordings/a",
        "C:/recordings/b",
    ]
    assert calls == [(int(window.winId()), "C:/recordings")]


@pytest.mark.parametrize("selection", ["", "/recordings/one"])
def test_non_windows_folder_fallback_uses_standard_qt_dialog(window, monkeypatch, selection):
    monkeypatch.setattr(recording_dialogs, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: selection)
    assert recording_dialogs.choose_recording_folders(window) == ([selection] if selection else [])


def test_both_shortcuts_open_their_respective_standard_dialogs(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        data_controller, "choose_recording_files", lambda *args: calls.append("files") or []
    )
    monkeypatch.setattr(
        data_controller, "choose_recording_folders", lambda *args: calls.append("folders") or []
    )
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window)
    QTest.keyClick(window, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(
        window,
        Qt.Key.Key_O,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert calls == ["files", "folders"]


def test_single_open_button_menu_offers_file_and_folder_modes(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        data_controller, "choose_recording_files", lambda *args: calls.append("files") or []
    )
    monkeypatch.setattr(
        data_controller, "choose_recording_folders", lambda *args: calls.append("folders") or []
    )
    menu = window.open_button.menu()
    for action in menu.actions():
        menu.popup(window.open_button.mapToGlobal(QPoint(0, window.open_button.height())))
        QTest.qWait(10)
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
    assert calls == ["files", "folders"]


def test_multiple_folder_selection_loads_one_batch_and_remembers_parent(
    window, tmp_path, recording_picker
):
    paths = []
    frame = pd.DataFrame({"time": [0.0, 1.0], "gyroscope_x": [1.0, 2.0]})
    window.loaded(("previous.csv", frame))
    wait_for_previews(window)
    for name in ("first", "second"):
        folder = tmp_path / name
        folder.mkdir()
        frame.to_csv(folder / "data.csv", index=False)
        paths.append(folder)
    recording_picker(paths, folders=True)
    window._layout.open_folder_action.trigger()
    wait_for_job(window)
    assert len(window._input_state.recordings) == 2
    assert Path(window._data_controller._browser_directory) == tmp_path
    assert set(window._input_state.sources.values()) == {str(path / "data.csv") for path in paths}


def test_failed_native_picker_preserves_current_input_and_reports_the_error(window, monkeypatch):
    frame = pd.DataFrame({"time": [0.0, 1.0], "gyroscope_x": [1.0, 2.0]})
    window.loaded(("original.csv", frame))
    window.side.setCurrentText("right")

    def fail(*args):
        raise OSError("Native folder picker failed")

    monkeypatch.setattr(data_controller, "choose_recording_folders", fail)
    window._layout.open_folder_action.trigger()
    assert window._input_state.frame is frame and window.side.currentText() == "right"
    assert window._job_state.worker is None and window.open_button.isEnabled()
    assert "Could not open" in window.notice.text()
