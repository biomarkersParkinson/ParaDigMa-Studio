"""Result export selection, formats and lossless serialization."""

import json
import threading
import time
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from paradigma_studio import core, exports
from paradigma_studio.core import export_results
from paradigma_studio.exports import ExportDialog, export_selection
from paradigma_studio.history import load_result_export


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
    assert batch_sizes == [5000, 5000, 3]


def test_export_worker_leaves_ui_responsive_until_atomic_completion(window, tmp_path, monkeypatch):
    frame = pd.DataFrame({"time": [0.0, 1.0], "metric": [2.0, 3.0]})
    window.analyzed({"quantifications": {"tremor": frame}})
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
        assert window.worker is not None and not path.exists()
        window.navigate(0)
        QApplication.instance().processEvents()
        assert window.pages.currentIndex() == 0
    finally:
        release.set()
        deadline = time.monotonic() + 5
        while window.worker is not None and time.monotonic() < deadline:
            QApplication.instance().processEvents()
            time.sleep(0.01)
    assert window.worker is None
    assert (
        json.loads(path.read_text())["results"]["quantifications"]["tremor"]["data"][1]["metric"]
        == 3.0
    )
