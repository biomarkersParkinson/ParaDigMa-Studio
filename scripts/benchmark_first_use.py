"""Measure deferred graph creation separately from warm UI workflow timings."""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path


def benchmark(report_path: Path, graph: str = "data") -> None:
    if graph not in {"data", "results"}:
        raise ValueError("graph must be data or results")
    started = time.perf_counter()
    # Keep the import boundary intact: this probe starts without scientific or
    # plotting imports, unlike the deliberately warm workflow benchmark.
    from PySide6.QtWidgets import QApplication

    from paradigma_studio.app import MainWindow

    imported = time.perf_counter()
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    report = {
        "conditions": "Fresh source process; Fusion 1450x920; warm OS/font caches. Initial paint includes app imports and construction; first graph includes deferred Matplotlib imports and queued painting. Empty history and recordings.",
        "qt_platform": app.platformName(),
        "import_seconds": imported - started,
        "graph": graph,
        "measurements": {},
    }
    with tempfile.TemporaryDirectory(prefix="paradigma-first-use-") as directory:
        window = MainWindow(directory)
        window.resize(1450, 920)
        window.show()
        app.processEvents()
        report["initial_paint_seconds"] = time.perf_counter() - started

        def measure(name, operation):
            before = time.perf_counter()
            operation()
            app.processEvents()
            report["measurements"][name] = time.perf_counter() - before

        try:
            measure("first_analyze", lambda: window.navigate(1))
            measure("first_runs", lambda: window.navigate(3))
            measure("first_results_overview", lambda: window.navigate(2))
            report["heavy_imports_before_graphs"] = [
                name
                for name in ("pandas", "pyarrow", "matplotlib", "paradigma", "scipy", "sklearn")
                if name in sys.modules
            ]
            if report["heavy_imports_before_graphs"]:
                raise AssertionError(report["heavy_imports_before_graphs"])
            if graph == "data":
                window.navigate(0)
                measure("first_graph", lambda: window.data_tabs.setCurrentIndex(1))
                canvas = window.data_canvas
            else:
                measure("first_graph", lambda: window.result_tabs.setCurrentIndex(1))
                canvas = window.canvas
            measure(
                "navigate_120",
                lambda: [(window.navigate(index % 4), app.processEvents()) for index in range(120)],
            )
            retained = (window.data_canvas if graph == "data" else window.canvas) is canvas
            if not retained:
                raise AssertionError("Navigation replaced the initialized graph canvas")
            report["retained_canvas"] = retained
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--graph", choices=("data", "results"), default="data")
    args = parser.parse_args()
    benchmark(args.report, args.graph)
