"""Performance regressions: reuse presentation work without losing values."""
import json
import threading
import time
from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from matplotlib.collections import PolyCollection
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_desktop import core, exports
from paradigma_desktop.app import MainWindow
from paradigma_desktop.plotting import time_coordinates
from paradigma_desktop.widgets import FrameModel


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = MainWindow(history_dir=tmp_path / 'runs')
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    app.processEvents()


def test_row_markers_reuse_pixels_but_changed_limits_redraw(window, monkeypatch):
    frame = pd.DataFrame({'time': np.arange(1000.), 'metric': np.arange(1000.) / 10})
    window.analyzed({'quantifications': {'tremor': frame}})
    window.result_tabs.setCurrentIndex(1)
    app = QApplication.instance()
    app.processEvents()
    window.canvas.draw()
    draws = []
    original = PolyCollection.draw
    def record(collection, renderer):
        draws.append(collection)
        return original(collection, renderer)
    monkeypatch.setattr(PolyCollection, 'draw', record)
    for row in (10, 30, 50):
        window.result_table.setCurrentIndex(window.result_table.model().index(row, 0))
        app.processEvents()
    assert not draws
    assert window._result_selection_artists
    optimized = np.asarray(window.canvas.buffer_rgba()).copy()
    window.canvas.draw()
    np.testing.assert_array_equal(np.asarray(window.canvas.buffer_rgba()), optimized)
    draws.clear()
    window.figure.axes[0].set_xlim(5, 20)
    window.highlight_result_row()
    app.processEvents()
    assert draws
    stream = BytesIO()
    window.figure.savefig(stream, format='png')
    assert stream.getvalue().startswith(b'\x89PNG')
    assert window._result_selection_artists  # Export does not discard selection.


def test_batched_json_preserves_schema_values_and_limits_temporary_rows(tmp_path, monkeypatch):
    count = 10003
    frame = pd.DataFrame({'time': np.arange(count), 'metric': np.resize([np.nan, np.inf, 1.25], count),
                          'large': [2**60 + 1] * count,
                          'stamp': pd.date_range('2026-10-25', periods=count, freq='s', tz='Europe/Amsterdam')})
    expected = core.json_value({'quantifications': {'tremor': frame}})
    batch_sizes = []
    original = pd.DataFrame.to_dict
    def observe(self, *args, **kwargs):
        batch_sizes.append(len(self))
        return original(self, *args, **kwargs)
    monkeypatch.setattr(pd.DataFrame, 'to_dict', observe)
    destination = tmp_path / 'results.json'
    core.export_results(destination, {'quantifications': {'tremor': frame}}, {'source': 'sensor.csv'})
    value = json.loads(destination.read_text())
    assert value['results'] == expected
    assert value['analysis'] == {'source': 'sensor.csv'}
    assert batch_sizes == [5000, 5000, 3]


def test_cached_column_values_invalidate_after_model_update():
    frame = pd.DataFrame({'value': pd.Series([pd.NA, 3], dtype='Int64'), 'name': ['a', 'b']})
    model = FrameModel(frame)
    before = model.data(model.index(1, 0), Qt.DisplayRole)
    frame['value'] = [1.5, 2.5]
    model.dataChanged.emit(model.index(0, 0), model.index(1, 0))
    assert model.data(model.index(1, 0), Qt.DisplayRole) != before
    assert model.data(model.index(1, 0), Qt.DisplayRole) == '2.5'


def test_vectorized_plot_dates_preserve_absolute_time_across_dst():
    timestamps = pd.date_range('2026-10-25T00:30:00Z', periods=5, freq='30min').tz_convert('Europe/Amsterdam')
    np.testing.assert_allclose(time_coordinates(timestamps), dates.date2num(timestamps.to_pydatetime()), atol=1e-12, rtol=0)


def test_export_worker_leaves_ui_responsive_until_atomic_completion(window, tmp_path, monkeypatch):
    frame = pd.DataFrame({'time': [0., 1.], 'metric': [2., 3.]})
    window.analyzed({'quantifications': {'tremor': frame}})
    path = tmp_path / 'chosen.json'
    started, release = threading.Event(), threading.Event()
    original = exports.export_selection
    def slow_export(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(exports, 'export_selection', slow_export)
    monkeypatch.setattr(exports.ExportDialog, 'exec', lambda self: True)
    monkeypatch.setattr(exports.ExportDialog, 'selected', lambda self: ['quantifications/tremor'])
    monkeypatch.setattr('paradigma_desktop.app.QFileDialog.getSaveFileName', lambda *args: (str(path), 'JSON'))
    window.choose_export()
    try:
        assert started.wait(2)
        assert window.worker is not None and not path.exists()
        window.navigate(0)
        QApplication.instance().processEvents()
        assert window.pages.currentIndex() == 0
    finally:
        release.set()
        deadline = time.monotonic() + 5
        while window.worker is not None and time.monotonic() < deadline:
            QApplication.instance().processEvents()
            time.sleep(.01)
    assert window.worker is None
    assert json.loads(path.read_text())['results']['quantifications']['tremor']['data'][1]['metric'] == 3.


def test_timing_table_cache_reuses_views_without_modifying_native_outputs(window):
    frame = pd.DataFrame({'time': [0., 1.], 'metric': [2., 3.]})
    original = frame.copy()
    window.analyzed({'quantifications': {'tremor': frame}})
    views = {}
    for enabled in (False, True, False, True):
        window.timing_toggle.setChecked(enabled)
        window.refresh_detail_table()
        if enabled in views:
            assert window.display_frame is views[enabled]
        views[enabled] = window.display_frame
    assert set(window._table_views) == {('quantifications/tremor', False), ('quantifications/tremor', True)}
    pd.testing.assert_frame_equal(frame, original)
