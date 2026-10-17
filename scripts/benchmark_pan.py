"""Measure Results time navigation and raw panning with queued Qt painting."""

import argparse
import json
import platform
import statistics
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backend_bases import MouseEvent
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paradigma_studio.app import MainWindow


def benchmark(report_path, *, frames=8, repeats=3):
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    report = {
        "platform": platform.platform(),
        "app_version": version("paradigma-studio"),
        "qt_platform": app.platformName(),
        "conditions": "Source app; Fusion, 1450x920; warm caches; Results scrollbar drags and interval selection, raw toolbar pans and queued Qt paints, without a profiler. Synthetic data only. Release redraw is measured separately.",
        "frames_per_drag": frames,
        "repeats": repeats,
        "measurements": {},
    }
    with tempfile.TemporaryDirectory(prefix="paradigma-pan-review-") as directory:
        window = MainWindow(Path(directory) / "runs")
        window.resize(1450, 920)
        window.show()
        output, full = _prepare_result_scroll(window)

        def measure(name, canvas, toolbar, limits):
            _measure_pan(app, report, name, canvas, toolbar, limits, repeats, frames)

        wide = full[0], full[0] + (full[1] - full[0]) * 0.75
        _measure_time_scroll(
            app, report, "results_wide_scroll_6x30000", window, wide, repeats, frames
        )
        zoomed = full[0] + 0.5, full[0] + 0.5 + 900 / 86400
        _measure_time_scroll(
            app, report, "results_zoomed_scroll_6x30000", window, zoomed, repeats, frames
        )
        _measure_time_selection(app, report, window, full, repeats, frames)
        sensor = _synthetic_pan_sensors()
        window.loaded(("sensor.csv", sensor))
        deadline = time.monotonic() + 30
        while any(
            p.pending
            for p in (window._origin_preview, window._time_preview, window._sensor_preview)
        ):
            if time.monotonic() > deadline:
                raise RuntimeError("Inspection preview did not finish")
            QTest.qWait(5)
        channels = [c for c in sensor if c not in ("time", "time_dt")]
        window.navigate(0)
        window.data_tabs.setCurrentIndex(1)
        window.set_input_channels(channels)
        QTest.qWait(30)
        measure(
            "data_3_modalities",
            window.data_canvas,
            window.data_toolbar,
            window.data_figure.axes[0].get_xlim(),
        )
        window._result_state.provenance = {"settings": {"skip_preparation": True}}
        window.analyzed({"quantifications": {"tremor": output}})
        window.result_table.setCurrentIndex(window.result_table.model().index(30, 0))
        window.inspect_sensor_context()
        window.navigate(2)
        window.set_sensor_channels(channels)
        QTest.qWait(30)
        measure(
            "context_3_modalities",
            window.sensor_canvas,
            window.sensor_toolbar,
            window.sensor_figure.axes[0].get_xlim(),
        )
        window.close()
        app.processEvents()
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _measure_pan(app, report, name, canvas, toolbar, limits, repeats, frames):
    frame_times, release_times = [], []
    if not toolbar._actions["pan"].isChecked():
        toolbar.pan()
    for _ in range(repeats):
        axes = canvas.figure.axes[0]
        axes.set_xlim(*limits)
        canvas.draw()
        app.processEvents()
        x, y = axes.transAxes.transform((0.5, 0.5))
        toolbar.press_pan(MouseEvent("button_press_event", canvas, x, y, button=1))
        if toolbar._pan_info is None:
            raise RuntimeError("Pan drag did not start")
        for step in range(1, frames + 1):
            started = time.perf_counter()
            toolbar.drag_pan(
                MouseEvent("motion_notify_event", canvas, x + step * 3, y, buttons={1})
            )
            app.processEvents()
            frame_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        toolbar.release_pan(MouseEvent("button_release_event", canvas, x + frames * 3, y, button=1))
        app.processEvents()
        release_times.append(time.perf_counter() - started)
    _record_measurement(report, name, frame_times, release_times, len(canvas.figure.axes))


def _measure_time_scroll(app, report, name, window, limits, repeats, frames):
    canvas, bar = window.canvas, window.result_time_scroll
    frame_times, release_times = [], []
    for _ in range(repeats):
        canvas.figure.axes[0].set_xlim(*limits)
        canvas.draw()
        app.processEvents()
        bar.setSliderDown(True)
        start, step = bar.value(), max(1, bar.maximum() // (frames * 4))
        for index in range(1, frames + 1):
            started = time.perf_counter()
            bar.setValue(min(bar.maximum(), start + step * index))
            app.processEvents()
            frame_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        bar.setSliderDown(False)
        app.processEvents()
        release_times.append(time.perf_counter() - started)
    _record_measurement(report, name, frame_times, release_times, len(canvas.figure.axes))


def _record_measurement(report, name, frame_times, release_times, graphs):
    report["measurements"][name] = {
        "frame_seconds": frame_times,
        "median_frame_seconds": statistics.median(frame_times),
        "release_seconds": release_times,
        "median_release_seconds": statistics.median(release_times),
        "graphs": graphs,
    }
    print(f"{name}: {statistics.median(frame_times):.4f} s/frame", flush=True)


def _measure_time_selection(app, report, window, limits, repeats, frames):
    canvas, toolbar = window.canvas, window.plot_toolbar
    frame_times, release_times = [], []
    if not toolbar._actions["zoom"].isChecked():
        toolbar.zoom()
    for _ in range(repeats):
        axes = canvas.figure.axes[0]
        axes.set_xlim(*limits)
        canvas.draw()
        app.processEvents()
        start = axes.transAxes.transform((0.2, 0.5))
        toolbar.press_zoom(MouseEvent("button_press_event", canvas, *start, button=1))
        for fraction in np.linspace(0.3, 0.7, frames):
            end = axes.transAxes.transform((fraction, 0.5))
            started = time.perf_counter()
            toolbar.drag_zoom(MouseEvent("motion_notify_event", canvas, *end, buttons={1}))
            app.processEvents()
            frame_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        toolbar.release_zoom(MouseEvent("button_release_event", canvas, *end, button=1))
        app.processEvents()
        release_times.append(time.perf_counter() - started)
    _record_measurement(
        report,
        "results_interval_selection_6x30000",
        frame_times,
        release_times,
        len(canvas.figure.axes),
    )


def _prepare_result_scroll(window):
    window._result_state.provenance = {
        "display_clock": {
            "origin": "2026-10-10T00:00:00+02:00",
            "timezone": "Europe/Amsterdam",
        }
    }
    times = np.arange(30000) * 4.0
    output = pd.DataFrame(
        {
            "time": times,
            **{f"metric_{i}": (2 + np.sin(times / (i + 1) / 400)) * (i + 1) for i in range(6)},
        }
    )
    window.analyzed({"quantifications": {"tremor": output}})
    window.navigate(2)
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.plot()
    QTest.qWait(30)
    full = window.figure.axes[0].get_xlim()
    return output, full


def _synthetic_pan_sensors():
    times = np.arange(250000) / 100
    sensor = pd.DataFrame(
        {
            "time": times,
            "time_dt": pd.date_range("2026-10-10T00:00:00+02:00", periods=len(times), freq="10ms"),
            **{
                f"{kind}_{axis}": np.sin(times * (i + 1)) * scale
                for kind, scale in (("accelerometer", 1), ("gyroscope", 80))
                for i, axis in enumerate("xyz")
            },
            "green": 1000 + 20 * np.cos(times),
        }
    )
    return sensor


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    benchmark(args.report)
