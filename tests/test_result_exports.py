"""Result export selection, formats and lossless serialization."""

import json
import math
import threading
import time
from contextlib import nullcontext
from decimal import Decimal
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from paradigma_studio import core, exports
from paradigma_studio.core import export_results
from paradigma_studio.exports import ExportDialog, export_selection
from paradigma_studio.history import load_result_export, new_run


def test_selective_json_csv_zip_preserve_native_outputs_precision_and_metadata(
    tmp_path, tremor_outputs
):
    result = tremor_outputs
    provenance = {"source": "sensor.csv", "settings": {"pipelines": ["tremor"]}}
    names = ["quantifications/tremor", "aggregations/tremor", "metadata/tremor"]
    path = tmp_path / "selection.json"
    export_selection(path, result, provenance, names, "JSON")
    saved_provenance, saved = load_result_export(path)
    assert saved_provenance == provenance
    assert not saved["classifications"]
    pd.testing.assert_frame_equal(
        saved["quantifications"]["tremor"], result["quantifications"]["tremor"]
    )
    assert saved["aggregations"]["tremor"]["count"] == 2**60 + 1
    export_selection(tmp_path / "selection.zip", result, provenance, names, "CSV")
    with ZipFile(tmp_path / "selection.zip") as archive:
        assert set(archive.namelist()) == {
            "001_quantifications_tremor.csv",
            "002_aggregations_tremor.csv",
            "metadata.json",
            "analysis.json",
        }
        pd.testing.assert_frame_equal(
            pd.read_csv(archive.open("001_quantifications_tremor.csv")),
            result["quantifications"]["tremor"],
        )
        assert json.loads(archive.read("metadata.json")) == {"metadata/tremor": {"windows": 3}}
    export_selection(tmp_path / "single.csv", result, provenance, [names[0]], "CSV")
    pd.testing.assert_frame_equal(
        pd.read_csv(tmp_path / "single.csv"), result["quantifications"]["tremor"]
    )


def test_export_dialog_and_single_button_are_consistent_across_tabs(window, tremor_outputs):
    result = tremor_outputs
    window.analyzed(result)
    for index in range(3):
        window.result_tabs.setCurrentIndex(index)
        assert window.export_button.isVisible() and window.export_button.text() == "Export…"
    dialog = ExportDialog(result, window)
    assert dialog.extension() == "json"
    dialog.format.setCurrentText("CSV")
    assert dialog.extension() == "zip"
    dialog.set_selection(Qt.Unchecked)
    assert not dialog.buttons.button(QDialogButtonBox.Save).isEnabled()
    dialog.leaves["quantifications/tremor"].setCheckState(0, Qt.Checked)
    assert dialog.extension() == "csv"
    dialog.leaves["metadata/tremor"].setCheckState(0, Qt.Checked)
    assert dialog.extension() == "zip"
    dialog.close()


def test_zip_export_protects_sources_and_neutralizes_formula_text(tmp_path):
    result = {
        "quantifications": {"tremor": pd.DataFrame({"time": [0.0], "=header": ["=cmd()"]})},
        "metadata": {"tremor": {}},
    }
    source = tmp_path / "source.csv"
    source.write_text("original")
    names = ["quantifications/tremor", "metadata/tremor"]
    with pytest.raises(ValueError, match="overwrite"):
        export_selection(source, result, {"source": str(source)}, names, "CSV")
    assert source.read_text() == "original"
    target = tmp_path / "safe.zip"
    export_selection(target, result, {}, names, "CSV")
    with ZipFile(target) as archive:
        text = archive.read("001_quantifications_tremor.csv").decode()
        assert "'=header" in text and "'=cmd()" in text


def test_json_export_preserves_float_precision_and_missing_values(tmp_path):
    path = tmp_path / "results.json"
    values = [np.nextafter(1.0, 2.0), 1e-20, np.nan]
    core.export_results(path, {"output": pd.DataFrame({"value": values}), "missing": pd.NA}, {})
    saved = json.loads(path.read_text())
    assert [row["value"] for row in saved["results"]["output"]["data"]] == [
        values[0],
        values[1],
        None,
    ]
    assert saved["results"]["missing"] is None


def test_export_round_trip_preserves_numeric_columns_and_float_values(tmp_path):
    path = tmp_path / "results.json"
    frame = pd.DataFrame({0: [np.nextafter(1.0, 2.0), None], "power": [2.0, 3.0]})
    export_results(
        path, {"quantifications": {"test": frame}, "errors": []}, {"source": "input.csv"}
    )
    provenance, results = load_result_export(path)
    assert provenance["source"] == "input.csv"
    pd.testing.assert_frame_equal(results["quantifications"]["test"], frame)


def test_batched_json_preserves_schema_values_and_limits_temporary_rows(tmp_path, monkeypatch):
    count = 10003
    frame = pd.DataFrame(
        {
            "time": np.arange(count),
            "metric": np.resize([np.nan, np.inf, 1.25], count),
            "large": [2**60 + 1] * count,
            "stamp": pd.date_range("2026-10-25", periods=count, freq="s", tz="Europe/Amsterdam"),
        }
    )
    expected = core.json_value({"quantifications": {"tremor": frame}})
    batch_sizes = []
    original = pd.DataFrame.to_dict

    def observe(self, *args, **kwargs):
        batch_sizes.append(len(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_dict", observe)
    destination = tmp_path / "results.json"
    core.export_results(
        destination, {"quantifications": {"tremor": frame}}, {"source": "sensor.csv"}
    )
    value = json.loads(destination.read_text())
    assert value["results"] == expected
    assert value["analysis"] == {"source": "sensor.csv"}
    assert sum(batch_sizes) == count and max(batch_sizes) <= 1000


def test_json_save_matches_existing_bytes_and_keeps_nested_source_values(tmp_path):
    count = 2003
    values = [-0.0, np.nextafter(0.0, 1.0), np.nextafter(1.0, 2.0), np.finfo(float).max]
    nested = {1: 'µ\n"', "values": (np.int64(2**60 + 1), pd.NA, np.inf)}
    scalars = [Decimal("1.234567890123456789"), np.datetime64("2026-10-25"), pd.NaT]
    frame = pd.DataFrame(
        {
            "time": np.arange(count) / 100,
            "metric": np.resize([*values, np.nan, np.inf, -np.inf], count),
            "large": np.full(count, np.iinfo(np.uint64).max, dtype=np.uint64),
            "nullable": pd.array(
                [[2**60 + 1, None, -(2**60 + 1)][i % 3] for i in range(count)], dtype="Int64"
            ),
            "flag": pd.array([[True, None, False][i % 3] for i in range(count)], dtype="boolean"),
            "float32": np.resize(np.array([0.1, np.nan, np.inf], dtype=np.float32), count),
            "when": pd.date_range("2026-10-25T00:45Z", periods=count, freq="s").tz_convert(
                "Europe/Amsterdam"
            ),
            "nested": [nested] * count,
            "scalar": pd.Series([scalars[i % 3] for i in range(count)], dtype=object),
        }
    )
    original = frame.copy(deep=True)
    provenance = {"settings": {"threshold": np.float32(0.1), "pair": ("a", pd.NA)}}
    results = {"quantifications": {"tremor": frame}, "errors": []}
    expected = json.dumps(
        core.json_value({"analysis": provenance, "results": results}),
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    destination = tmp_path / "results.json"
    export_results(destination, results, provenance)
    assert destination.read_bytes() == expected
    rows = json.loads(expected)["results"]["quantifications"]["tremor"]["data"]
    np.testing.assert_array_equal(
        np.array([row["metric"] for row in rows[:4]]).view(np.uint64),
        np.array(values).view(np.uint64),
    )
    assert math.copysign(1, rows[0]["metric"]) == -1
    assert [row["metric"] for row in rows[4:7]] == [None, None, None]
    assert rows[0]["large"] == 2**64 - 1 and rows[0]["nullable"] == 2**60 + 1
    assert rows[0]["when"].endswith("+02:00") and rows[-1]["when"].endswith("+01:00")
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert 1 in nested and "1" not in nested and isinstance(nested["values"], tuple)
    assert type(nested["values"][0]) is np.int64 and nested["values"][1] is pd.NA
    assert np.isposinf(nested["values"][2])
    assert type(provenance["settings"]["threshold"]) is np.float32
    assert isinstance(provenance["settings"]["pair"], tuple)
    assert provenance["settings"]["pair"][1] is pd.NA


@pytest.mark.parametrize(
    "columns",
    [
        ["time", "metric"],
        [0, "0", 0],
        ["metric", "time", "metric"],
        [("metric", 1), ("metric", 2)],
        [None, "None"],
        [],
    ],
)
def test_json_save_preserves_column_key_order_collisions_and_empty_tables(tmp_path, columns):
    frame = pd.DataFrame(np.arange(3 * len(columns)).reshape(3, len(columns)), columns=columns)
    destination = tmp_path / "columns.json"
    result = {"table": frame, "empty": frame.iloc[:0]}
    with (
        pytest.warns(UserWarning, match="columns are not unique")
        if frame.columns.has_duplicates
        else nullcontext()
    ):
        expected = json.dumps(
            core.json_value({"analysis": {}, "results": result}),
            allow_nan=False,
            separators=(",", ":"),
        )
        export_results(destination, result, {})
    assert destination.read_text(encoding="utf-8") == expected


@pytest.mark.parametrize("existing", [False, True])
def test_later_batch_encoding_failure_keeps_destination_and_cleans_temporary_files(
    tmp_path, existing
):
    class BrokenValue:
        def __str__(self):
            raise ValueError("failed encoding value")

    destination = tmp_path / "results.json"
    previous = b'{"previous":true}'
    if existing:
        destination.write_bytes(previous)
    broken = BrokenValue()
    frame = pd.DataFrame({"value": [*range(2002), broken]})
    with pytest.raises(ValueError, match="failed encoding value"):
        export_results(destination, {"table": frame}, {})
    if existing:
        assert destination.read_bytes() == previous
    else:
        assert not destination.exists()
    assert sorted(tmp_path.iterdir()) == ([destination] if existing else [])
    assert frame.iloc[-1, 0] is broken


def test_export_worker_leaves_ui_responsive_until_atomic_completion(window, tmp_path, monkeypatch):
    frame = pd.DataFrame({"time": [0.0, 1.0], "metric": [2.0, 3.0]})
    window.analyzed({"quantifications": {"tremor": frame}})
    window._run_state.current_run = new_run("sensor.csv", {"pipelines": ["tremor"]})
    path = tmp_path / "chosen.json"
    started, release = threading.Event(), threading.Event()
    original = exports.export_selection

    def slow_export(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(exports, "export_selection", slow_export)
    monkeypatch.setattr(exports.ExportDialog, "exec", lambda self: True)
    monkeypatch.setattr(exports.ExportDialog, "selected", lambda self: ["quantifications/tremor"])
    monkeypatch.setattr(
        "paradigma_studio.app.QFileDialog.getSaveFileName", lambda *args: (str(path), "JSON")
    )
    window.choose_export()
    try:
        assert started.wait(2)
        assert window._job_state.worker is not None and not path.exists()
        window.navigate(0)
        QApplication.instance().processEvents()
        assert window.pages.currentIndex() == 0
    finally:
        release.set()
        deadline = time.monotonic() + 5
        while window._job_state.worker is not None and time.monotonic() < deadline:
            QApplication.instance().processEvents()
            time.sleep(0.01)
    assert window._job_state.worker is None
    assert (
        json.loads(path.read_text())["results"]["quantifications"]["tremor"]["data"][1]["metric"]
        == 3.0
    )
