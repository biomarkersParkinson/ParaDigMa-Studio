import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtWidgets import QApplication
from paradigma_desktop.app import MainWindow, Worker
from paradigma_desktop import app as desktop_app


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
