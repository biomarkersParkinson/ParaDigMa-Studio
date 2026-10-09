"""Give headless Qt tests enough screen space for the desktop workspace."""

import os
from pathlib import Path
import pytest


def wait_for_previews(window):
    """Process Qt delivery while read-only recording previews finish in workers."""
    import time
    from PySide6.QtWidgets import QApplication

    previews = (window._origin_preview, window._time_preview, window._sensor_preview)
    deadline = time.monotonic() + 10
    while any(preview.pending for preview in previews) and time.monotonic() < deadline:
        QApplication.instance().processEvents()
        time.sleep(0.01)  # Let Python imports/scans in the executor acquire the GIL.
    assert not any(preview.pending for preview in previews), "Recording previews did not finish"
    QApplication.instance().processEvents()


# Qt's default offscreen screen is 800x800, smaller than the app's minimum
# width. On Windows this can clip a button's visible region at the screen edge.
# Qt separates platform options at colons, so a Windows drive letter cannot
# appear in the configfile option. The test process keeps its original cwd;
# startup/smoke subprocesses already select their own offscreen platform.
if os.environ.get("QT_QPA_PLATFORM", "offscreen") == "offscreen":
    config = Path(__file__).parent / "data" / "qt-offscreen.json"
    relative = Path(os.path.relpath(config, Path.cwd())).as_posix()
    os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={relative}"


@pytest.fixture(autouse=True)
def release_closed_desktop_windows():
    """Qt signal cycles otherwise keep closed windows and styles alive in CI."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        for widget in app.topLevelWidgets():
            if type(widget).__name__ == "MainWindow" and widget.worker is None:
                widget.close()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def bar_values(axes):
    import numpy as np

    return np.array([path.vertices[1, 1] for path in axes.collections[0].get_paths()])


def bar_starts(axes):
    import numpy as np

    return np.array(
        [
            path.vertices[:, 0].min() - np.ptp(path.vertices[:, 0]) * 0.08 / 0.84
            for path in axes.collections[0].get_paths()
        ]
    )


def bar_centers(axes):
    import numpy as np

    return np.array(
        [
            (path.vertices[:, 0].min() + path.vertices[:, 0].max()) / 2
            for path in axes.collections[0].get_paths()
        ]
    )
