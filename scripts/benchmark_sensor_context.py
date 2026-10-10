"""Measure context opening and raw plotting with a long synthetic recording."""

import argparse
import json
import platform
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication

from paradigma_desktop.app import MainWindow


def benchmark(report_path, samples=3_000_000):
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    report = {
        "platform": platform.platform(),
        "qt_platform": app.platformName(),
        "samples": samples,
        "conditions": "Source UI, Fusion, 1450x920; synthetic 100 Hz gyroscope recording, Amsterdam clock, no profiler; includes queued Qt painting. Context displays 20 seconds; Data displays the full recording.",
        "context_seconds": [],
        "data_seconds": [],
    }
    with tempfile.TemporaryDirectory(prefix="paradigma-context-benchmark-") as directory:
        window = MainWindow(Path(directory) / "runs")
        window.resize(1450, 920)
        window.show()
        times = np.arange(samples) / 100
        window.frame = pd.DataFrame(
            {
                "time": times,
                "gyroscope_x": np.sin(times),
                "gyroscope_y": np.cos(times),
                "gyroscope_z": np.sin(times / 2),
            }
        )
        window.provenance = {
            "settings": {"skip_preparation": True},
            "display_clock": {
                "origin": "2026-10-10T00:00:00+02:00",
                "timezone": "Europe/Amsterdam",
            },
        }
        window.analyzed(
            {
                "quantifications": {
                    "tremor": pd.DataFrame(
                        {
                            "time": [120.0, 180.0, 300.0],
                            "tremor_power": [1.0, 2.0, 3.0],
                        }
                    )
                }
            }
        )
        window.navigate(2)
        app.processEvents()
        for row in range(3):
            window.result_table.setCurrentIndex(window.result_table.model().index(row, 0))
            started = time.perf_counter()
            window.inspect_sensor_context()
            app.processEvents()
            report["context_seconds"].append(time.perf_counter() - started)
        window.data_time_channel.addItem("time", "time")
        window.populate_input_channels()
        window.navigate(0)
        window.data_tabs.setCurrentIndex(1)
        app.processEvents()
        for _ in range(3):
            started = time.perf_counter()
            window.plot_input()
            app.processEvents()
            report["data_seconds"].append(time.perf_counter() - started)
        window.close()
        app.processEvents()
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=3_000_000)
    args = parser.parse_args()
    benchmark(args.report, args.samples)
