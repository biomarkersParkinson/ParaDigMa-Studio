import os
import time
from importlib.resources import files
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from paradigma_desktop.app import MainWindow, Worker
from paradigma_desktop import app as desktop_app


@pytest.fixture(autouse=True)
def isolate_local_run_history(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_app.QStandardPaths, "writableLocation", lambda location: str(tmp_path))


def test_window_results_and_plot(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    frame = pd.DataFrame({"time": [0., 1., 2.], "tremor_power": [1., 2., 3.]})
    window.loaded((str(tmp_path / "sensor.csv"), frame))
    window.analyzed({"quantifications": {"tremor": frame}, "errors": []})
    window.show()
    app.processEvents()
    assert window.result_table.model().rowCount() == 3
    assert len(window.figure.axes[0].lines) == 1
    assert window.export_button.isEnabled()
    window.canvas.draw()
    window.close()


def test_worker_failure_is_delivered():
    app = QApplication.instance() or QApplication([])
    errors = []
    def fail(logger):
        raise ValueError("bad recording")
    worker = Worker(fail)
    worker.failed.connect(errors.append)
    worker.start()
    assert worker.wait(5000)
    app.processEvents()
    assert errors == ["ValueError: bad recording"]


def test_declining_pickle_warning_never_starts_loading(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    monkeypatch.setattr(desktop_app.QFileDialog, "getOpenFileName", lambda *args: (str(tmp_path / "sensor.pkl"), ""))
    monkeypatch.setattr(desktop_app.QMessageBox, "warning", lambda *args: desktop_app.QMessageBox.No)
    started = []
    monkeypatch.setattr(window, "start_job", lambda *args: started.append(args))
    window.open_file()
    assert started == []
    assert window.worker is None
    window.close()


def test_time_plot_handles_numeric_metric_names_without_using_row_numbers_as_time():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    frame = pd.DataFrame({"time": [10., 20., 30.], 0: [1., 2., 3.], "Row number": [100., 200., 300.]}, index=["a", "b", "c"])
    window.analyzed({"quantifications": {"test": frame}, "errors": []})
    window.y_column.setCurrentIndex(window.y_column.findData(0))
    assert list(window.figure.axes[0].lines[0].get_xdata()) == [10., 20., 30.]
    assert list(window.figure.axes[0].lines[0].get_ydata()) == [1., 2., 3.]
    pd.testing.assert_frame_equal(window.result_table.model().frame[frame.columns], frame)
    window.close()


def test_prepared_mode_disables_and_does_not_record_unused_conversions(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(history_dir=tmp_path / "runs")
    window.loaded(("sensor.csv", pd.DataFrame({"time": [0., 1.], "gyroscope_x": [1., 2.]})))
    window.set_modules(["tremor"])
    window.time.setCurrentText("relative_ms")
    window.gyro.setCurrentText("rad/s")
    window.orientation.setText("--x,y,z")
    window.prepared.setChecked(True)
    assert not window.time.isEnabled()
    assert not window.gyro.isEnabled()
    assert not window.orientation.isEnabled()
    monkeypatch.setattr(window, "start_job", lambda *args: None)
    window.run_analysis()
    settings = window.provenance["settings"]
    assert settings["time_input_unit"] == "relative_s"
    assert settings["gyroscope_units"] == "deg/s"
    assert settings["device_orientation"] == ["x", "y", "z"]
    window.prepared.setChecked(False)
    assert window.time.isEnabled()
    window.close()


def test_background_pipeline_failure_is_shown_and_controls_recover(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    warnings = []
    monkeypatch.setattr(desktop_app.QMessageBox, "warning", lambda *args: warnings.append(args))
    t = np.arange(30) / 100
    frame = pd.DataFrame({"time": t, **{f"gyroscope_{axis}": np.sin(t) for axis in "xyz"}})
    window.loaded(("short.csv", frame))
    window.set_modules(["tremor"])
    window.gaps.setChecked(False)  # Exercise the classifier's short-input failure.
    window.run_analysis()
    assert not window.run_button.isEnabled()
    deadline = time.monotonic() + 10
    while window.worker is not None and time.monotonic() < deadline:
        QTest.qWait(20)
    assert window.worker is None
    assert window.results["errors"]
    assert warnings == []  # Processing errors are reported inline, without a modal.
    assert "processing error" in window.notice.text()
    assert window.runs[0]["status"] == "Partial"
    assert window.runs[0]["errors"]
    assert window.run_button.isEnabled()
    assert not window.progress.isVisible()
    assert "processing error" in window.status.text()
    assert window.export_button.isEnabled()
    window.close()


def test_empatica_opens_in_background_without_gyro(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    source = str(files("paradigma_desktop") / "data" / "test_data.avro")
    errors = []
    monkeypatch.setattr(desktop_app.QFileDialog, "getOpenFileName", lambda *args: (source, ""))
    monkeypatch.setattr(desktop_app.QMessageBox, "critical", lambda *args: errors.append(args))
    window.open_file()
    deadline = time.monotonic() + 10
    while window.worker is not None and time.monotonic() < deadline:
        QTest.qWait(20)
    assert window.worker is None
    assert errors == []
    assert window.input_table.model().rowCount() == 115904
    assert "require gyroscope data" in window.status.text()
    assert window.open_button.isEnabled()
    window.close()
