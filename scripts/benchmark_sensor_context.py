"""Measure context opening and raw plotting with a long synthetic recording."""

import argparse
import hashlib
import json
import platform
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication

from paradigma_studio.app import MainWindow


def _benchmark_raw_detail(window, app, report, times):
    """Include actual source-rate zooms and a full retained-input checksum."""
    from matplotlib.lines import Line2D

    source = window._input_state.frame
    checksum = hashlib.sha256(pd.util.hash_pandas_object(source, index=True).to_numpy().tobytes())
    report["raw_input_sha256"] = checksum.hexdigest()
    report["raw_zoom_seconds"], report["raw_visible_samples"] = [], []
    drawn = []
    original = Line2D.draw

    def capture(line, renderer):
        if line.get_label() == "gyroscope_x":
            drawn.append(line.get_xydata().copy())
        return original(line, renderer)

    axes = window.data_figure.axes[0]
    radius = min(1000, max(1, len(times) // 8))
    with patch.object(Line2D, "draw", capture):
        for fraction in (0.25, 0.5, 0.75):
            center = int((len(times) - 1) * fraction)
            begin, end = max(0, center - radius), min(len(times) - 1, center + radius)
            low, high = times[begin], times[end]
            started = time.perf_counter()
            axes.set_xlim(low, high)
            window.data_canvas.draw()
            app.processEvents()
            report["raw_zoom_seconds"].append(time.perf_counter() - started)
            actual = drawn[-1]
            visible = actual[(actual[:, 0] >= low) & (actual[:, 0] <= high)]
            np.testing.assert_array_equal(visible[:, 0], times[begin : end + 1])
            np.testing.assert_array_equal(visible[:, 1], source.gyroscope_x.iloc[begin : end + 1])
            report["raw_visible_samples"].append(len(visible))
    checksum = hashlib.sha256(pd.util.hash_pandas_object(source, index=True).to_numpy().tobytes())
    assert checksum.hexdigest() == report["raw_input_sha256"], "Raw plotting changed source samples"


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
        window._input_state.frame = pd.DataFrame(
            {
                "time": times,
                "gyroscope_x": np.sin(times),
                "gyroscope_y": np.cos(times),
                "gyroscope_z": np.sin(times / 2),
            }
        )
        window._result_state.provenance = {
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
        blocked = window.data_time_channel.blockSignals(True)
        window.data_time_channel.addItem("time", "time")
        window.data_time_channel.setCurrentIndex(window.data_time_channel.findData("time"))
        window.data_time_channel.blockSignals(blocked)
        window.populate_input_channels()
        window.navigate(0)
        window.data_tabs.setCurrentIndex(1)
        app.processEvents()
        for _ in range(3):
            started = time.perf_counter()
            window.plot_input()
            app.processEvents()
            report["data_seconds"].append(time.perf_counter() - started)
        _benchmark_raw_detail(window, app, report, times)
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
