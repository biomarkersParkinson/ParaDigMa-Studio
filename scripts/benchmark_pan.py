"""Measure Results time navigation and raw panning with queued Qt painting."""

import argparse
import hashlib
import json
import platform
import statistics
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from matplotlib.backend_bases import MouseEvent
from matplotlib.layout_engine import ConstrainedLayoutEngine
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paradigma_studio.app import MainWindow


def benchmark(
    report_path,
    *,
    frames=8,
    repeats=3,
    selection_only=False,
    rows=30000,
    graphs=6,
    pixel_ratio=1,
    with_controls=False,
    results_path=None,
):
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    report = {
        "platform": platform.platform(),
        "app_version": version("paradigma-studio"),
        "qt_platform": app.platformName(),
        "conditions": "Source app; Fusion, 1450x920; warm imports; queued Qt paints, without a profiler. Selection separates first creation from repeated toggles. Navigation release redraw is measured separately. See selection_conditions for input and display scale.",
        "frames_per_drag": frames,
        "repeats": repeats,
        "measurements": {},
    }
    with tempfile.TemporaryDirectory(prefix="paradigma-pan-review-") as directory:
        window = MainWindow(Path(directory) / "runs")
        window.resize(1450, 920)
        window.show()
        output, full = _prepare_result_scroll(
            window,
            rows=rows,
            graphs=graphs,
            select_all=not selection_only,
            results_path=results_path,
        )
        window.canvas._set_device_pixel_ratio(pixel_ratio)
        window.time_axis._set_device_pixel_ratio(pixel_ratio)
        if with_controls:
            model = window.result_table.model()
            window.result_table.setCurrentIndex(model.index(model.rowCount() // 2, 0))
            window.plot_toolbar.settings_action.setChecked(True)
        report["selection_conditions"] = {
            "rows": rows,
            "graphs": graphs,
            "pixel_ratio": pixel_ratio,
            "limits_and_timepoint": with_controls,
            "input": str(results_path) if results_path else "synthetic",
        }
        if selection_only:
            _measure_result_selection(app, report, window, repeats)
            window.clear_results()
            window.close()
            _write_report(report_path, report)
            return

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
        _measure_result_selection(app, report, window, repeats)
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
    _write_report(report_path, report)


def _write_report(report_path, report):
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


def _measure_result_selection(app, report, window, repeats):
    """Always remove the actual shared owner, which changes between selections."""
    previous_mode = window.result_graph_view.currentIndex()
    original = _table_signatures(window)
    report["selection"] = {}
    for mode, name in enumerate(("detailed", "30-minute", "day", "profile")):
        last = list(window._result_state._series_items.values())[-1]
        window.result_series.blockSignals(True)
        for item in window._result_state._series_items.values():
            item.setCheckState(0, Qt.Unchecked if item is last else Qt.Checked)
        window.result_series.blockSignals(False)
        window.result_graph_view.setCurrentIndex(mode)
        window.plot()
        _drain_paints(app)
        first = _measure_series_click(app, window, last)
        if mode == 3 and window.plot_toolbar.settings_action.isChecked():
            axis = window.figure.axes[0]
            summary = axis._paradigma_epoch_data
            valid = summary.loc[np.isfinite(summary.value)]
            if len(valid):
                x = float((valid.start_s.iloc[0] + valid.end_s.iloc[0]) / 2)
                window._result_state._profile_selection = (
                    axis._paradigma_dataset,
                    axis._paradigma_metric,
                    x,
                )
                window.highlight_result_row()
                _drain_paints(app)
        removals, additions, retained, draws = [], [], [], []
        for _ in range(repeats):
            window.result_series.blockSignals(True)
            for item in window._result_state._series_items.values():
                item.setCheckState(0, Qt.Checked)
            window.result_series.blockSignals(False)
            window.plot()
            _drain_paints(app)
            previous = tuple(window.figure.axes)
            owner = window._graph_state._result_shared_axes
            item = window._result_state._series_items[
                owner._paradigma_dataset, owner._paradigma_metric
            ]
            removed = _measure_series_click(app, window, item)
            removals.append(removed["seconds"])
            retained.append(sum(ax in previous for ax in window.figure.axes))
            added = _measure_series_click(app, window, item)
            additions.append(added["seconds"])
            draws.append({"remove": removed, "add": added})
        report["selection"][name] = {
            "remove_owner_seconds": removals,
            "median_remove_owner_seconds": statistics.median(removals),
            "add_seconds": additions,
            "median_add_seconds": statistics.median(additions),
            "retained_axes": retained,
            "first_selection": first,
            "samples": draws,
            "p95_remove_seconds": float(np.percentile(removals, 95)),
            "p95_add_seconds": float(np.percentile(additions, 95)),
        }
        print(f"{name}: {statistics.median(removals):.4f} s/owner removal", flush=True)
    window.result_graph_view.setCurrentIndex(previous_mode)
    app.processEvents()
    if _table_signatures(window) != original:
        raise AssertionError("Series selection changed source result values")
    report["source_values_unchanged"] = True


def _table_signatures(window):
    return {
        name: (
            tuple(frame.columns),
            tuple(str(dtype) for dtype in frame.dtypes),
            hashlib.sha256(
                pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
            ).hexdigest(),
        )
        for name, frame in window._result_state.tables.items()
    }


def _drain_paints(app):
    for _ in range(3):
        app.processEvents()


def _measure_series_click(app, window, item):
    tree = window.result_series
    tree.scrollToItem(item)
    _drain_paints(app)
    rect = tree.visualItemRect(item)
    counts = {"main_draws": 0, "ruler_draws": 0, "full_layouts": 0}

    def count(name):
        counts[name] += 1

    main = window.canvas.mpl_connect("draw_event", lambda event: count("main_draws"))
    ruler = window.time_axis.mpl_connect("draw_event", lambda event: count("ruler_draws"))
    before = item.checkState(0)
    started = time.perf_counter()
    execute = ConstrainedLayoutEngine.execute

    def solve(engine, figure):
        if figure is window.figure:
            counts["full_layouts"] += 1
        return execute(engine, figure)

    try:
        with patch.object(ConstrainedLayoutEngine, "execute", solve):
            QTest.mouseClick(
                tree.viewport(), Qt.LeftButton, pos=QPoint(rect.left() + 55, rect.center().y())
            )
            _drain_paints(app)
        elapsed = time.perf_counter() - started
        if item.checkState(0) == before:
            raise RuntimeError("Plot-series label click did not change selection")
        cache = getattr(window._graph_state, "_result_plot_cache", None)
        return {
            "seconds": elapsed,
            **counts,
            "retained_geometry_bytes": getattr(cache, "memory_bytes", 0),
        }
    finally:
        window.canvas.mpl_disconnect(main)
        window.time_axis.mpl_disconnect(ruler)


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


def _prepare_result_scroll(window, *, rows=30000, graphs=6, select_all=True, results_path=None):
    window._result_state.provenance = {
        "display_clock": {
            "origin": "2026-10-10T00:00:00+02:00",
            "timezone": "Europe/Amsterdam",
        }
    }
    times = np.arange(rows) * 4.0
    output = pd.DataFrame(
        {
            "time": times,
            **{f"metric_{i}": (2 + np.sin(times / (i + 1) / 400)) * (i + 1) for i in range(graphs)},
        }
    )
    window.analyzed({"quantifications": {"tremor": output}})
    if results_path is not None:
        from paradigma_studio.history import load_result_export

        provenance, results = load_result_export(results_path)
        window._result_state.provenance = provenance
        window.analyzed(results)
        output = next(iter(window._result_state.tables.values()))
    window.navigate(2)
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    if select_all:
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
    parser.add_argument("--selection-only", action="store_true")
    parser.add_argument("--rows", type=int, default=30000)
    parser.add_argument("--graphs", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--pixel-ratio", type=int, choices=(1, 2), default=1)
    parser.add_argument("--with-controls", action="store_true")
    parser.add_argument(
        "--results", type=Path, help="Saved results JSON; requires --selection-only"
    )
    args = parser.parse_args()
    if args.results is not None and not args.selection_only:
        parser.error("--results requires --selection-only")
    if args.rows < 2 or args.graphs < 2 or args.repeats < 1:
        parser.error("Use at least two rows/graphs and one repeat")
    benchmark(
        args.report,
        selection_only=args.selection_only,
        rows=args.rows,
        graphs=args.graphs,
        repeats=args.repeats,
        pixel_ratio=args.pixel_ratio,
        with_controls=args.with_controls,
        results_path=args.results,
    )
