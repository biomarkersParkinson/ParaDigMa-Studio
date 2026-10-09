"""Measure UI workflows using synthetic data, temporary history and exports."""
import argparse
import json
import platform
import statistics
import tempfile
import time
from pathlib import Path
from importlib.metadata import version
from types import SimpleNamespace

import numpy as np
import pandas as pd
from matplotlib import dates
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
# Keep one-time scientific imports outside the interaction measurements.
from paradigma.config import TremorConfig  # noqa: F401

from paradigma_desktop.app import MainWindow
from paradigma_desktop.exports import export_selection
from paradigma_desktop.history import new_run
from paradigma_desktop.inspection import inspect_recording


def benchmark(report_path):
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    measurements = {}
    export_bytes = {}
    with tempfile.TemporaryDirectory(prefix='paradigma-ui-review-') as directory:
        window = MainWindow(Path(directory) / 'runs')
        window.resize(1450, 920)
        window.show()
        app.processEvents()

        def measure(name, operation, prepare=lambda: None):
            samples = []
            for _ in range(3):
                prepare()
                app.processEvents()
                start = time.perf_counter()
                operation()
                app.processEvents()
                samples.append(time.perf_counter() - start)
            measurements[name] = {'seconds': samples, 'median_seconds': statistics.median(samples)}
            print(f'{name}: {statistics.median(samples):.4f} s', flush=True)

        sensor_rows, output_rows = 250000, 30000
        frame = pd.DataFrame({'time': np.arange(sensor_rows) / 100.,
                              'time_dt': pd.date_range('2026-10-07T00:00:00+02:00', periods=sensor_rows, freq='10ms'),
                              **{f'{kind}_{axis}': np.ones(sensor_rows)
                                 for kind in ('accelerometer', 'gyroscope') for axis in 'xyz'}})
        description = inspect_recording(frame, 'relative_s')
        measure('LOAD UI', lambda: window.loaded(('sensor.csv', frame, description)))
        deadline = time.monotonic() + 30
        while any(preview.pending for preview in (window._origin_preview, window._time_preview, window._sensor_preview)):
            if time.monotonic() > deadline:
                raise RuntimeError('Inspection preview did not finish.')
            app.processEvents()
            time.sleep(.005)
        window.navigate(1)
        app.processEvents()

        def options():
            for _ in range(10):
                window.gaps.setChecked(not window.gaps.isChecked())
                window.acc.setCurrentIndex((window.acc.currentIndex() + 1) % window.acc.count())
                app.processEvents()
        measure('ANALYZE OPTIONS 10', options)
        measure('NAVIGATE 12', lambda: [(window.navigate(index % 4), app.processEvents()) for index in range(12)])
        sources = {f'recording_{index + 1:03d}': f'sensor-{index + 1}.csv' for index in range(3)}
        recordings = {key: frame.assign(time_dt=frame.time_dt + pd.Timedelta(hours=index))
                      for index, key in enumerate(sources)}
        descriptions = {key: inspect_recording(value, 'relative_s') for key, value in recordings.items()}
        window.loaded_recordings((sources, recordings, descriptions))
        window.navigate(0)
        app.processEvents()
        measure('RECORDING SWITCH 12', lambda: [(window.input_recording.setCurrentIndex(index % 3), app.processEvents())
                                               for index in range(12)])
        window.data_tabs.setCurrentIndex(1)
        app.processEvents()
        measure('DATA CHANNELS 4', lambda: [(window.set_input_channels(['gyroscope_x'] if index % 2 else
                                                  ['accelerometer_x', 'gyroscope_x']), app.processEvents())
                                          for index in range(4)])
        window.loaded(('sensor.csv', frame, description))
        output = pd.DataFrame({'time': np.arange(output_rows) * 4., 'file_key': ['df_1'] * output_rows,
                               'tremor_power': np.arange(output_rows) % 15 / 10,
                               'pred_tremor_checked': np.arange(output_rows) % 2,
                               'pred_arm_at_rest': np.ones(output_rows)})
        results = {'quantifications': {'tremor': output}, 'classifications': {'tremor': output},
                   'aggregations': {'tremor': {'perc_windows_tremor': 50.}}, 'metadata': {}}
        window.provenance = {'source': 'sensor.csv', 'settings': {'pipelines': ['tremor'], 'skip_preparation': True}}
        window.result_source_frame = frame
        measure('RESULTS LOAD', lambda: window.analyzed(results))
        measure('GRAPHS SHOW', lambda: window.result_tabs.setCurrentIndex(1),
                lambda: window.result_tabs.setCurrentIndex(0))

        def series(checked):
            for item in list(window._series_items.values())[:3]:
                item.setCheckState(0, checked)
                app.processEvents()
        measure('SELECT SERIES 3', lambda: series(Qt.Checked), lambda: series(Qt.Unchecked))
        window.result_graph_view.setCurrentIndex(1)
        app.processEvents()
        measure('SELECT EPOCH SERIES 3', lambda: series(Qt.Checked), lambda: series(Qt.Unchecked))
        window.result_graph_view.setCurrentIndex(0)
        app.processEvents()
        measure('SELECT ROWS 10', lambda: [(window.result_table.setCurrentIndex(window.result_table.model().index(index * 10, 0)),
                                           app.processEvents()) for index in range(10)])
        origin = dates.date2num(pd.Timestamp(window.display_clock['origin']))
        measure('GRAPH CLICKS 10', lambda: [(window.graph_clicked(SimpleNamespace(inaxes=window.figure.axes[0],
                                                        xdata=origin + (index * 8 + 1) / 86400)), app.processEvents())
                                            for index in range(10)])
        measure('TABLE TIMING 4', lambda: [(window.timing_toggle.setChecked(not window.timing_toggle.isChecked()),
                                          app.processEvents()) for _ in range(4)])
        measure('TABLE SWITCH 10', lambda: [(window.dataset.setCurrentText('classifications/tremor' if index % 2 else 'quantifications/tremor'),
                                           app.processEvents()) for index in range(10)])
        selected = ['quantifications/tremor', 'classifications/tremor']
        for format_name, extension in (('JSON', 'json'), ('CSV ZIP', 'zip')):
            measure(f'EXPORT {format_name}', lambda ext=extension: export_selection(
                str(Path(directory) / f'output.{ext}'), results, window.provenance, selected,
                'JSON' if ext == 'json' else 'CSV'))
            export_bytes[format_name] = (Path(directory) / f'output.{extension}').stat().st_size
        window.runs = [new_run('sensor.csv', {'pipelines': ['tremor']}) for _ in range(200)]
        window.navigate(3)
        window.refresh_runs()
        app.processEvents()
        for record in window.runs:
            window.history.save(record)
        measure('HISTORY LOAD 200', window.history.load)
        measure('RUNS REFRESH', window.refresh_runs)
        measure('RUNS SELECT 10', lambda: [(window.run_table.setCurrentIndex(window.run_table.model().index(index, 0)),
                                          app.processEvents()) for index in range(10)])
        window.close()
        app.processEvents()
    report = {'platform': platform.platform(), 'python': platform.python_version(),
              'qt_platform': app.platformName(),
              'versions': {name: version(name) for name in ('paradigma', 'PySide6', 'matplotlib', 'pandas', 'numpy')}, 'conditions': 'Source app; Qt Fusion, 1450x920, warm scientific imports and OS caches. Three repeats per workflow, including queued Qt painting; synthetic inputs and temporary history/exports only.',
              'sensor_rows': sensor_rows, 'output_rows_per_table': output_rows,
              'history_records': 200, 'export_bytes': export_bytes, 'workflows': measurements}
    Path(report_path).write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    benchmark(parser.parse_args().report)
