"""Measure deferred graph creation separately from warm UI workflow timings."""

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def benchmark(report_path: Path, graph: str = "data", pixel_ratio: int = 1) -> None:
    if graph not in {"data", "results"}:
        raise ValueError("graph must be data or results")
    started = time.perf_counter()
    os.environ["QT_SCALE_FACTOR"] = str(pixel_ratio)
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
        "pixel_ratio": pixel_ratio,
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
            # Record the first display at the requested scale separately from
            # deferred workspace imports/construction. Keep that boundary clear.
            canvas._set_device_pixel_ratio(pixel_ratio)
            if graph == "results":
                window.time_axis._set_device_pixel_ratio(pixel_ratio)
            measure("first_scaled_draw", canvas.draw)
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


def repeated_benchmark(report_path: Path, graph: str, pixel_ratio: int, repeats: int) -> None:
    """Every launch is a new process; no inherited Matplotlib/pandas imports."""
    samples = []
    with tempfile.TemporaryDirectory(prefix="paradigma-first-use-samples-") as directory:
        for index in range(repeats):
            path = Path(directory) / f"sample-{index}.json"
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--graph",
                    graph,
                    "--pixel-ratio",
                    str(pixel_ratio),
                    "--report",
                    str(path),
                ],
                check=True,
            )
            samples.append(json.loads(path.read_text(encoding="utf-8")))
    report = {
        "conditions": "Fresh subprocess per sample; warm OS/font caches; no profiler or allocation tracing.",
        "samples": samples,
        "summary": {
            name: {
                "median_seconds": statistics.median(s["measurements"][name] for s in samples),
                "p95_seconds": _percentile95([s["measurements"][name] for s in samples]),
            }
            for name in samples[0]["measurements"]
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    index = 0.95 * (len(ordered) - 1)
    lower = int(index)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (
        index - lower
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--graph", choices=("data", "results"), default="data")
    parser.add_argument("--pixel-ratio", type=int, choices=(1, 2), default=1)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("Use at least one repeat")
    if args.repeats == 1:
        benchmark(args.report, args.graph, args.pixel_ratio)
    else:
        repeated_benchmark(args.report, args.graph, args.pixel_ratio, args.repeats)
