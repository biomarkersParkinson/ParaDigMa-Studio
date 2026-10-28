"""Capture current guide illustrations through a real public-example workflow."""

import argparse
import os
import shutil
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from paradigma_studio.app import MainWindow
from paradigma_studio.core import load_sensor_file
from paradigma_studio.history import run_is_saved

ROOT = Path(__file__).resolve().parents[1]


def wait_until(app, ready, timeout=180):
    deadline = time.monotonic() + timeout
    while not ready():
        if time.monotonic() >= deadline:
            raise TimeoutError("The screenshot workflow did not finish.")
        app.processEvents()
        QTest.qWait(20)
    app.processEvents()


def wait_for_previews(window, app):
    previews = (window._origin_preview, window._time_preview, window._sensor_preview)
    wait_until(app, lambda: not any(preview.pending for preview in previews))


def snapshot(window, app, destination):
    # Move away from the hover navigation and let native layouts/plots settle.
    QTest.mouseMove(window, QPoint(window.width() - 20, 20))
    window._layout.sidebar.setExpanded(False, animated=False)
    QToolTip.hideText()
    app.processEvents()
    QTest.qWait(150)
    if not window.grab().save(str(destination)):
        raise OSError(f"Could not save screenshot: {destination}")
    print(f"Captured {destination.name}", flush=True)


def capture(output):
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    with tempfile.TemporaryDirectory(prefix="paradigma-guide-") as directory:
        temporary = Path(directory)
        source = temporary / "test_data.CWA"
        shutil.copyfile(ROOT / "src/paradigma_studio/data/test_data.CWA", source)
        window = MainWindow(history_dir=temporary / "runs")
        window.resize(1450, 1000)
        window.show()
        try:
            window.loaded((str(source), load_sensor_file(source)))
            wait_for_previews(window, app)
            snapshot(window, app, output / "data.png")

            window.data_tabs.setCurrentIndex(1)
            window.set_input_channels(["accelerometer_x", "gyroscope_x"])
            window.data_toolbar._actions["zoom_in"].trigger()
            snapshot(window, app, output / "data-graphs.png")
            window.data_toolbar.home()

            window.navigate(1)
            window.set_modules(["gait"])
            wait_for_previews(window, app)
            snapshot(window, app, output / "analyze.png")

            print("Running official gait analysis…", flush=True)
            window._analysis_controller.run_analysis()
            wait_until(app, lambda: window._job_state.worker is None)
            run = window._run_state.current_run
            if run is None or run["status"] != "Completed" or run["errors"]:
                raise RuntimeError(f"The example analysis failed: {window.status.text()}")
            if window._result_state.tables["quantifications/gait/unfiltered"].empty:
                raise RuntimeError("The example produced no gait quantifications.")
            window._export_controller.save_results()
            wait_until(app, lambda: window._job_state.worker is None)
            if not run_is_saved(run):
                raise RuntimeError("The example results were not saved.")
            snapshot(window, app, output / "results.png")

            window.result_tabs.setCurrentIndex(1)
            window._result_state._series_items[
                ("quantifications/gait/unfiltered", "range_of_motion")
            ].setCheckState(0, Qt.CheckState.Checked)
            snapshot(window, app, output / "results-graphs.png")

            window.dataset.setCurrentText("quantifications/gait/unfiltered")
            window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
            window.inspect_sensor_context()
            window.set_sensor_channels(["accelerometer_x", "gyroscope_x"])
            snapshot(window, app, output / "sensor-context.png")

            window.navigate(3)
            window._layout.run_detail_tabs.setCurrentIndex(1)
            snapshot(window, app, output / "runs.png")
        finally:
            if window._job_state.worker is not None:
                window._job_controller.stop_analysis()
                wait_until(app, lambda: window._job_state.worker is None)
            # History and outputs belong to this temporary capture session only.
            window.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/images/user-guide")
    args = parser.parse_args()
    config = Path(os.path.relpath(ROOT / "tests/data/qt-offscreen.json")).as_posix()
    os.environ.setdefault("QT_QPA_PLATFORM", f"offscreen:configfile={config}")
    os.environ["QT_SCALE_FACTOR"] = "1"
    capture(args.output.resolve())
