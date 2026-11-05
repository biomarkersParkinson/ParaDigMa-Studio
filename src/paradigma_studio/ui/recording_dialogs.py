"""Use the platform's standard file and folder selection windows."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QFileDialog, QWidget

from ..recordings import SENSOR_FILE_PATTERNS


def choose_recording_files(parent: QWidget, directory: str = "") -> list[str]:
    paths, _ = QFileDialog.getOpenFileNames(
        parent,
        "Open recording files for the same subject",
        directory,
        f"Sensor recordings ({' '.join(SENSOR_FILE_PATTERNS)})",
    )
    return paths


def choose_recording_folders(parent: QWidget, directory: str = "") -> list[str]:
    if sys.platform == "win32":
        from .windows_folder_dialog import choose_windows_folders

        return choose_windows_folders(int(parent.winId()), directory)
    # Qt exposes one folder on other platforms; the distributed Windows app
    # uses IFileOpenDialog's native multi-folder mode above.
    folder = QFileDialog.getExistingDirectory(
        parent, "Open a recording folder for the same subject", directory
    )
    return [folder] if folder else []
