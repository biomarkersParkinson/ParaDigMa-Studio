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
def release_closed_desktop_windows(monkeypatch):
    """Qt signal cycles otherwise keep closed windows and styles alive in CI."""
    from PySide6.QtWidgets import QMessageBox

    execute = QMessageBox.exec

    def discard_test_results(dialog):
        # Normal tests discard their temporary run outputs on teardown. Tests
        # of the close warning override this response to exercise each choice.
        if dialog.objectName() == "unsavedResults":
            return QMessageBox.Discard
        return execute(dialog)

    monkeypatch.setattr(QMessageBox, "exec", discard_test_results)
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


@pytest.fixture
def window(tmp_path):
    """Visible window for UI tests; modules override this for special Qt cases."""
    from PySide6.QtWidgets import QApplication

    from paradigma_studio.app import MainWindow

    application = QApplication.instance() or QApplication([])
    widget = MainWindow(history_dir=tmp_path / "runs")
    widget.show()
    try:
        yield widget
    finally:
        import time

        deadline = time.monotonic() + 10
        from PySide6.QtTest import QTest

        while widget.worker is not None and time.monotonic() < deadline:
            QTest.qWait(20)
        assert widget.worker is None, "Background operation did not finish"
        widget.close()
        application.processEvents()


@pytest.fixture
def synthetic_imu():
    """Fresh, seeded 120-second gyroscope recording shared by preparation tests."""
    import numpy as np
    import pandas as pd

    time = np.arange(12000) / 100
    random = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "time": time,
            **{
                f"gyroscope_{axis}": 0.1 * np.sin(2 * np.pi * 5 * time)
                + random.normal(0, 0.02, len(time))
                for axis in "xyz"
            },
        }
    )


@pytest.fixture
def tremor_outputs():
    """Fresh output tables with missing power, binary states and a large integer."""
    import numpy as np
    import pandas as pd

    return {
        "classifications": {
            "tremor": pd.DataFrame({"time": [0.0, 4.0, 8.0], "pred_tremor_checked": [1, 0, 1]})
        },
        "quantifications": {
            "tremor": pd.DataFrame({"time": [0.0, 4.0, 8.0], "tremor_power": [2.0, np.nan, 5.0]})
        },
        "aggregations": {"tremor": {"perc_windows_tremor": 2 / 3 * 100, "count": 2**60 + 1}},
        "metadata": {"tremor": {"windows": 3}},
        "errors": [],
    }


def select_plot_metric(window, dataset, metric):
    """Select a metric through Plot series, retaining selections in other modules."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTreeWidgetItemIterator

    window.result_tabs.setCurrentIndex(1)
    iterator = QTreeWidgetItemIterator(window.result_series)
    entries = []
    while iterator.value() is not None:
        item = iterator.value()
        key = item.data(0, Qt.UserRole)
        if key is not None:
            entries.append((key, item))
        iterator += 1
    chosen = next(item for key, item in entries if key == (dataset, metric))
    chosen.parent().setExpanded(True)
    chosen.setCheckState(0, Qt.Checked)
    for key, item in entries:
        if key[0] == dataset and item is not chosen:
            item.setCheckState(0, Qt.Unchecked)
    window.result_series.setCurrentItem(chosen)
    window.result_series.scrollToItem(chosen)
