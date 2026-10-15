"""Opt-in first-window probe; never opens recordings or starts an analysis."""

import json
import sys
import tempfile
import time
import traceback
from pathlib import Path


def startup_test(report_path, started, *, history_dir=None):
    report_path = Path(report_path).resolve()
    try:
        from PySide6.QtCore import QEvent, QObject, QTimer

        from . import app as workspace
        from .app import MainWindow, QApplication

        imported = time.perf_counter()
        app = QApplication([])
        app.setStyle("Fusion")
        report = {"status": "failed", "error": "Window did not paint within 30 seconds."}

        class FirstPaint(QObject):
            painted = False

            def eventFilter(self, widget, event):
                if event.type() == QEvent.Paint and not self.painted:
                    self.painted = True
                    # Report after Qt finishes this paint and returns to its
                    # event loop, rather than only timing MainWindow.show().
                    QTimer.singleShot(0, self.ready)
                return False

            def ready(self):
                report.clear()
                report.update(
                    status="passed",
                    import_seconds=imported - started,
                    first_paint_seconds=time.perf_counter() - started,
                    qt_platform=app.platformName(),
                    empty_history=not window.runs,
                    run_history_count=len(window.runs),
                    data_modules_loaded=[
                        name for name in ("pandas", "pyarrow") if name in sys.modules
                    ],
                    plotting_modules_loaded=[
                        name for name in ("matplotlib",) if name in sys.modules
                    ],
                    graph_workspaces_created=[
                        name
                        for name, widget in (
                            ("data", window._data_graph),
                            ("results", window.graph_view),
                            ("sensor", window._sensor_graph),
                        )
                        if widget.initialized
                    ],
                    persistent_font_cache=getattr(workspace, "PLOT_CACHE_DIRECTORY", None)
                    is not None,
                    analysis_modules_loaded=[
                        name
                        for name in ("paradigma", "sklearn", "scipy", "openmovement")
                        if name in sys.modules
                    ],
                )
                temporary = report_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
                temporary.replace(report_path)
                app.quit()

        with tempfile.TemporaryDirectory(prefix="paradigma-startup-") as directory:
            window = MainWindow(history_dir=history_dir if history_dir is not None else directory)
            observer = FirstPaint(window)
            window.installEventFilter(observer)
            window.show()
            QTimer.singleShot(30000, app.quit)
            app.exec()
            window.close()
        if report["status"] != "passed":
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0 if report["status"] == "passed" else 1
    except Exception:
        report_path.write_text(
            json.dumps({"status": "failed", "error": traceback.format_exc()}, indent=2),
            encoding="utf-8",
        )
        return 1
