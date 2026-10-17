"""Measure UI workflows using synthetic data, temporary history and exports."""

import argparse
import json
import platform
import statistics
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from matplotlib import dates

# Importing ParaDigMa warms the scientific stack before interaction timing;
# the class itself is intentionally unused in this workflow benchmark.
from paradigma.config import TremorConfig  # noqa: F401
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_studio.app import MainWindow
from paradigma_studio.exports import export_selection
from paradigma_studio.history import new_run
from paradigma_studio.inspection import inspect_recording


def benchmark(report_path):
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    measurements = {}
    export_bytes = {}
    with tempfile.TemporaryDirectory(prefix="paradigma-ui-review-") as directory:
        window = MainWindow(Path(directory) / "runs")
        window.resize(1450, 920)
        window.show()
        app.processEvents()

        def measure(name, operation, prepare=lambda: None):
            _measure_workflow(app, measurements, name, operation, prepare)

        frame, sensor_rows = _benchmark_input_workflows(window, app, measure)
        output_rows = 30000
        results = _benchmark_result_workflows(window, app, measure, frame, output_rows)
        _benchmark_result_interactions(window, app, measure)
        _benchmark_exports(window, directory, results, measure, export_bytes)
        _benchmark_run_history(window, app, measure)
        window.close()
        app.processEvents()
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "qt_platform": app.platformName(),
        "versions": {
            name: version(name)
            for name in ("paradigma", "PySide6", "matplotlib", "pandas", "numpy")
        },
        "conditions": "Source app; Qt Fusion, 1450x920, warm scientific imports and OS caches. Three repeats per workflow, including queued Qt painting; series selection in all four graph views and table switching through visible module/output controls. Synthetic inputs and temporary history/exports only.",
        "sensor_rows": sensor_rows,
        "output_rows_per_table": output_rows,
        "history_records": 200,
        "export_bytes": export_bytes,
        "workflows": measurements,
    }
    Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")


def _measure_workflow(app, measurements, name, operation, prepare):
    samples = []
    for _ in range(3):
        prepare()
        app.processEvents()
        start = time.perf_counter()
        operation()
        app.processEvents()
        samples.append(time.perf_counter() - start)
    measurements[name] = {"seconds": samples, "median_seconds": statistics.median(samples)}
    print(f"{name}: {statistics.median(samples):.4f} s", flush=True)


def _benchmark_input_workflows(window, app, measure):
    sensor_rows = 250000
    frame = pd.DataFrame(
        {
            "time": np.arange(sensor_rows) / 100.0,
            "time_dt": pd.date_range("2026-10-07T00:00:00+02:00", periods=sensor_rows, freq="10ms"),
            **{
                f"{kind}_{axis}": np.ones(sensor_rows)
                for kind in ("accelerometer", "gyroscope")
                for axis in "xyz"
            },
        }
    )
    description = inspect_recording(frame, "relative_s")
    measure("LOAD UI", lambda: window.loaded(("sensor.csv", frame, description)))
    deadline = time.monotonic() + 30
    while any(
        preview.pending
        for preview in (window._origin_preview, window._time_preview, window._sensor_preview)
    ):
        if time.monotonic() > deadline:
            raise RuntimeError("Inspection preview did not finish.")
        app.processEvents()
        time.sleep(0.005)
    window.navigate(1)
    app.processEvents()

    def options():
        for _ in range(10):
            window.gaps.setChecked(not window.gaps.isChecked())
            window.acc.setCurrentIndex((window.acc.currentIndex() + 1) % window.acc.count())
            app.processEvents()

    measure("ANALYZE OPTIONS 10", options)
    measure(
        "NAVIGATE 12",
        lambda: [(window.navigate(index % 4), app.processEvents()) for index in range(12)],
    )
    sources = {f"recording_{index + 1:03d}": f"sensor-{index + 1}.csv" for index in range(3)}
    recordings = {
        key: frame.assign(time_dt=frame.time_dt + pd.Timedelta(hours=index))
        for index, key in enumerate(sources)
    }
    descriptions = {
        key: inspect_recording(value, "relative_s") for key, value in recordings.items()
    }
    window.loaded_recordings((sources, recordings, descriptions))
    window.navigate(0)
    app.processEvents()
    measure(
        "RECORDING SWITCH 12",
        lambda: [
            (window.input_recording.setCurrentIndex(index % 3), app.processEvents())
            for index in range(12)
        ],
    )
    window.data_tabs.setCurrentIndex(1)
    app.processEvents()
    measure(
        "DATA CHANNELS 4",
        lambda: [
            (
                window.set_input_channels(
                    ["gyroscope_x"] if index % 2 else ["accelerometer_x", "gyroscope_x"]
                ),
                app.processEvents(),
            )
            for index in range(4)
        ],
    )
    window.loaded(("sensor.csv", frame, description))
    return frame, sensor_rows


def _benchmark_result_workflows(window, app, measure, frame, output_rows):
    output = pd.DataFrame(
        {
            "time": np.arange(output_rows) * 4.0,
            "file_key": ["df_1"] * output_rows,
            "tremor_power": np.arange(output_rows) % 15 / 10,
            "pred_tremor_checked": np.arange(output_rows) % 2,
            "pred_arm_at_rest": np.ones(output_rows),
        }
    )
    results = {
        "quantifications": {"tremor": output},
        "classifications": {"tremor": output},
        "aggregations": {"tremor": {"perc_windows_tremor": 50.0}},
        "metadata": {},
    }
    window.provenance = {
        "source": "sensor.csv",
        "settings": {"pipelines": ["tremor"], "skip_preparation": True},
    }
    window._result_state.result_source_frame = frame
    measure("RESULTS LOAD", lambda: window.analyzed(results))
    measure(
        "GRAPHS SHOW",
        lambda: window.result_tabs.setCurrentIndex(1),
        lambda: window.result_tabs.setCurrentIndex(0),
    )

    _benchmark_graph_series(window, app, measure)
    return results


def _benchmark_graph_series(window, app, measure):
    def series(checked):
        for item in list(window._series_items.values())[:3]:
            item.setCheckState(0, checked)
            app.processEvents()

    views = (
        ("Detailed", "SELECT SERIES 3"),
        ("30-minute epochs", "SELECT EPOCH SERIES 3"),
        ("Day", "SELECT DAY SERIES 3"),
        ("24-hour profile", "SELECT PROFILE SERIES 3"),
    )
    for title, name in views:
        index = window.result_graph_view.findText(title)
        if index < 0:
            raise RuntimeError(f"Graph view is unavailable: {title}")
        window.result_graph_view.setCurrentIndex(index)
        app.processEvents()
        measure(name, lambda: series(Qt.Checked), lambda: series(Qt.Unchecked))
    window.result_graph_view.setCurrentText("Detailed")
    app.processEvents()


def _benchmark_result_interactions(window, app, measure):
    _benchmark_table_interactions(window, app, measure)
    window.result_tabs.setCurrentIndex(1)
    app.processEvents()
    origin = dates.date2num(pd.Timestamp(window._result_state.display_clock["origin"]))
    measure(
        "GRAPH CLICKS 10",
        lambda: [
            (
                window.graph_clicked(
                    SimpleNamespace(
                        inaxes=window.figure.axes[0], xdata=origin + (index * 8 + 1) / 86400
                    )
                ),
                app.processEvents(),
            )
            for index in range(10)
        ],
    )


def _select_result_table(window, name):
    """Use the same module tabs and output selector as an interactive user."""
    if not window.table_module_tabs.isVisible() or not window.table_dataset.isVisible():
        raise RuntimeError("Table controls must be visible during the workflow benchmark.")
    module = name.split("/")[1]
    modules = [
        window.table_module_tabs.tabData(index) for index in range(window.table_module_tabs.count())
    ]
    if module not in modules:
        raise RuntimeError(f"Table module is unavailable: {module}")
    window.table_module_tabs.setCurrentIndex(modules.index(module))
    index = window.table_dataset.findData(name)
    if index < 0:
        raise RuntimeError(f"Output table is unavailable: {name}")
    window.table_dataset.setCurrentIndex(index)


def _benchmark_table_interactions(window, app, measure):
    window.result_tabs.setCurrentIndex(2)
    app.processEvents()
    _select_result_table(window, "quantifications/tremor")
    app.processEvents()
    measure(
        "SELECT ROWS 10",
        lambda: [
            (
                window.result_table.setCurrentIndex(
                    window.result_table.model().index(index * 10, 0)
                ),
                app.processEvents(),
            )
            for index in range(10)
        ],
    )
    measure(
        "TABLE TIMING 4",
        lambda: [
            (
                window.timing_toggle.setChecked(not window.timing_toggle.isChecked()),
                app.processEvents(),
            )
            for _ in range(4)
        ],
    )
    measure(
        "TABLE SWITCH 10",
        lambda: [
            (
                _select_result_table(
                    window, "classifications/tremor" if index % 2 else "quantifications/tremor"
                ),
                app.processEvents(),
            )
            for index in range(10)
        ],
        lambda: _select_result_table(window, "classifications/tremor"),
    )


def _benchmark_exports(window, directory, results, measure, export_bytes):
    selected = ["quantifications/tremor", "classifications/tremor"]
    for format_name, extension in (("JSON", "json"), ("CSV ZIP", "zip")):
        measure(
            f"EXPORT {format_name}",
            lambda ext=extension: export_selection(
                str(Path(directory) / f"output.{ext}"),
                results,
                window.provenance,
                selected,
                "JSON" if ext == "json" else "CSV",
            ),
        )
        export_bytes[format_name] = (Path(directory) / f"output.{extension}").stat().st_size


def _benchmark_run_history(window, app, measure):
    window._run_state.runs = [new_run("sensor.csv", {"pipelines": ["tremor"]}) for _ in range(200)]
    window.navigate(3)
    window.refresh_runs()
    app.processEvents()
    for record in window._run_state.runs:
        window.history.save(record)
    measure("HISTORY LOAD 200", window.history.load)
    measure("RUNS REFRESH", window.refresh_runs)
    measure(
        "RUNS SELECT 10",
        lambda: [
            (
                window.run_table.setCurrentIndex(window.run_table.model().index(index, 0)),
                app.processEvents(),
            )
            for index in range(10)
        ],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    benchmark(parser.parse_args().report)
