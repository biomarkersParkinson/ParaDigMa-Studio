"""Table models and cached presentation views retain current native values."""

import pandas as pd
from PySide6.QtCore import Qt

from paradigma_studio.widgets import FrameModel, RecordModel


def test_table_tooltips_only_expose_precision_hidden_by_rounding():
    frame = pd.DataFrame({"value": [1.234567, 2.0, None]})
    original = frame.copy(deep=True)
    raw, compact = FrameModel(frame), FrameModel(frame, compact=True)
    for model in (raw, compact):
        assert model.headerData(0, Qt.Horizontal, Qt.ToolTipRole) is None
    assert all(raw.data(raw.index(row, 0), Qt.ToolTipRole) is None for row in range(3))
    assert compact.data(compact.index(0, 0), Qt.DisplayRole) == "1.2346"
    assert compact.data(compact.index(0, 0), Qt.ToolTipRole) == "1.234567"
    assert compact.data(compact.index(1, 0), Qt.ToolTipRole) is None
    assert compact.data(compact.index(2, 0), Qt.ToolTipRole) is None
    records = RecordModel([{"name": "Saved run"}], ["name"])
    assert records.data(records.index(0, 0), Qt.ToolTipRole) is None
    assert records.headerData(0, Qt.Horizontal, Qt.ToolTipRole) is None
    pd.testing.assert_frame_equal(frame, original)


def test_cached_column_values_invalidate_after_model_update():
    frame = pd.DataFrame({"value": pd.Series([pd.NA, 3], dtype="Int64"), "name": ["a", "b"]})
    model = FrameModel(frame)
    before = model.data(model.index(1, 0), Qt.DisplayRole)
    frame["value"] = [1.5, 2.5]
    model.dataChanged.emit(model.index(0, 0), model.index(1, 0))
    assert model.data(model.index(1, 0), Qt.DisplayRole) != before
    assert model.data(model.index(1, 0), Qt.DisplayRole) == "2.5"


def test_timing_table_cache_reuses_views_without_modifying_native_outputs(window):
    frame = pd.DataFrame({"time": [0.0, 1.0], "metric": [2.0, 3.0]})
    original = frame.copy()
    window.analyzed({"quantifications": {"tremor": frame}})
    views = {}
    for enabled in (False, True, False, True):
        window.timing_toggle.setChecked(enabled)
        window.refresh_detail_table()
        if enabled in views:
            assert window.display_frame is views[enabled]
        views[enabled] = window.display_frame
    assert set(window._result_state._table_views) == {
        ("quantifications/tremor", False),
        ("quantifications/tremor", True),
    }
    pd.testing.assert_frame_equal(frame, original)
