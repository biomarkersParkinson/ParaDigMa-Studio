"""Prepared coverage, truthful bars, date labels and selective exports."""
from copy import deepcopy
import json
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel

from paradigma_desktop.app import MainWindow
from paradigma_desktop.availability import availability_views, prepared_availability
from paradigma_desktop.exports import ExportDialog, export_selection
from paradigma_desktop.history import load_result_export
from paradigma_desktop.overview import recording_summary
from paradigma_desktop.plotting import plot_bars
from paradigma_desktop.time_axis import RecordingTimeFormatter
from conftest import bar_values, bar_starts, bar_centers


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = MainWindow(history_dir=tmp_path / "runs")
    widget.show()
    yield widget
    widget.close()
    app.processEvents()


def outputs():
    return {"classifications": {"tremor": pd.DataFrame({"time": [0., 4., 8.], "pred_tremor_checked": [1, 0, 1]})},
            "quantifications": {"tremor": pd.DataFrame({"time": [0., 4., 8.], "tremor_power": [2., np.nan, 5.]})},
            "aggregations": {"tremor": {"perc_windows_tremor": 2 / 3 * 100, "count": 2**60 + 1}},
            "metadata": {"tremor": {"windows": 3}}, "errors": []}


def test_continuous_bars_show_exact_values_leave_missing_gaps_and_retain_zero(window):
    result = outputs()
    original = deepcopy(result)
    window.analyzed(result)
    axis = window.figure.axes[0]
    assert not axis.lines
    np.testing.assert_array_equal(bar_values(axis), [2., 5.])
    np.testing.assert_allclose(bar_starts(axis), [0., 8.], atol=1e-12)
    assert not any(path.contains_point((6., 1.)) for path in axis.collections[0].get_paths())
    axis.set_xlim(8.5, 9.5)
    window.canvas.draw()
    assert axis.collections[0].get_paths()[1].contains_point((9., 1.))
    pd.testing.assert_frame_equal(result["quantifications"]["tremor"], original["quantifications"]["tremor"])
    figure = Figure()
    axes = figure.add_subplot()
    plot_bars(axes, [0., 1., 2.], [1., 2., 3.], [-2., 0., np.nan], "#477DA3")
    np.testing.assert_array_equal(bar_values(axes), [-2., 0.])
    assert len(axes.collections[1].get_segments()) == 1  # Actual zero stays distinguishable from missing.


def test_prepared_coverage_retains_real_gaps_sections_offsets_and_distinct_pipeline_inputs(window):
    inputs = {"recording_001": pd.DataFrame({"time": [0., .01, .02, 1., 1.01]}),
              "recording_002": pd.DataFrame({"time": [0., .01]})}
    coverage = prepared_availability(inputs, ["gait", "tremor"])
    np.testing.assert_allclose(coverage["gait"]["recording_001"]["intervals"], [[0., .03], [1., 1.02]])
    coverage.update(prepared_availability({"recording_001": pd.DataFrame({"time": [0., .01]})}, ["pulse_rate"]))
    result = outputs()
    result["metadata"]["desktop_availability"] = coverage
    offsets = {"gait": {"recording_001": 2., "recording_002": 10.}, "tremor": {"recording_001": 2., "recording_002": 10.}, "pulse_rate": 0.}
    views, labels = availability_views(result, offsets)
    assert set(views) == {"preparation/gait_tremor", "preparation/pulse_rate"}
    np.testing.assert_allclose(views["preparation/gait_tremor"].time, [2., 3., 10.])
    assert "Gait, Tremor" in labels[("preparation/gait_tremor", "available")]
    window.provenance = {"display_offsets": offsets}
    window.analyzed(result)
    names = [name for name, metric in window.selected_result_series() if name.startswith("preparation/")]
    assert len(names) == 2
    assert not any(name.startswith("preparation/") for name in window.tables)
    axis = next(ax for ax in window.figure.axes if ax._paradigma_dataset == "preparation/gait_tremor")
    assert axis._paradigma_binary
    assert len(axis.collections[0].get_paths()) == 3


def test_availability_matches_exact_prepared_inputs_and_excludes_discarded_sections(monkeypatch):
    from paradigma_desktop import core
    times = np.r_[np.arange(100) / 100, 5., 5.01]
    raw = pd.DataFrame({"time": times, **{f"gyroscope_{axis}": np.ones(len(times)) for axis in "xyz"}})
    raw.loc[50, "gyroscope_x"] = np.nan
    captured = []
    def orchestrator(**kwargs):
        captured.append(kwargs["dfs"])
        return {"metadata": {}, "quantifications": {}, "aggregations": {}, "errors": []}
    monkeypatch.setattr(core, "run_paradigma", orchestrator)
    result = core.analyze(raw, pipelines=["tremor"], drop_missing_samples=True, split_by_gaps=True,
                          max_gap_seconds=1.5, min_segment_seconds=.1)
    prepared = captured[0]
    assert isinstance(prepared, dict) and len(prepared) == 2  # Official missing-sample splitting.
    np.testing.assert_array_equal(pd.concat(prepared.values()).time, np.delete(times[:100], 50))
    coverage = result["metadata"]["desktop_availability"]["tremor"]
    assert sum(section["samples"] for section in coverage.values()) == 99
    np.testing.assert_allclose([interval for section in coverage.values() for interval in section["intervals"]],
                               [[0., .5], [.51, 1.]])
    assert raw.gyroscope_x.isna().sum() == 1


def test_module_help_keeps_all_module_buttons_stationary_and_spacing(window):
    window.navigate(1)
    window.resize(960, 650)
    QTest.qWait(30)
    positions = [button.mapTo(window, button.rect().topLeft()) for button in window.module_buttons.values()]
    sizes = [button.size() for button in window.module_buttons.values()]
    window.analysis_help["Analysis modules"][0].click()
    QTest.qWait(30)
    assert positions == [button.mapTo(window, button.rect().topLeft()) for button in window.module_buttons.values()]
    assert sizes == [button.size() for button in window.module_buttons.values()]
    assert window.analysis_controls.layout().spacing() == 16


def test_axis_and_mapping_fields_follow_their_columns_with_readable_official_guide(window):
    window.navigate(1)
    window.resize(1450, 920)
    QTest.qWait(30)
    fields = [window.side, window.acc, window.gyro, window.time, window.orientation]
    assert len({field.mapTo(window, field.rect().topLeft()).x() for field in fields}) == 1
    assert window.orientation.mapTo(window, window.orientation.rect().topLeft()).y() > window.time.mapTo(window, window.time.rect().bottomLeft()).y()
    assert window.mapping.mapTo(window, window.mapping.rect().topLeft()).y() > window.min_segment.mapTo(window, window.min_segment.rect().bottomLeft()).y()
    for info, description in window.analysis_help.values():
        assert "color: #1E609E" in description.text()
    info, description = window.analysis_help["Device axes"]
    info.click()
    assert '<img src="' in description.text() and "directions_axes.png" in description.text()
    assert "https://biomarkersparkinson.github.io/paradigma/guides/coordinate_system.html" in description.text()


def test_recording_overview_groups_desktop_metadata_and_deduplicates_preparation(window):
    result = outputs()
    preparation = {"input_samples": 100, "analyzed_samples": 90, "excluded_samples": 10, "continuous_sections": 2}
    result["metadata"].update(desktop_recordings={"recordings": ["a", "b"], "sections": {"a": "a"}},
                               desktop_preparation={"input_samples": 100, "analysis_groups": [["gait", "tremor"]],
                                                    "by_module": {"gait": preparation, "tremor": preparation}})
    provenance = {"sources": {"a": "/recordings/a.csv", "b": "/recordings/b.csv"}}
    entries = recording_summary(result, provenance, None)
    assert entries.count(("Input samples", "100")) == 1
    assert ("Gait, Tremor · Prepared samples", "90") in entries
    assert not any("section" in title.lower() and isinstance(value, dict) for title, value in entries)
    window.provenance = provenance
    window.analyzed(result)
    assert set(window.overview_module_cards) == {"tremor"}
    assert sum(label.text() == "Recording & preparation" for label in window.overview_content.findChildren(QLabel)) == 1


def test_time_formatter_separates_time_date_at_midnight_and_keeps_date_when_zoomed():
    figure = Figure()
    axis = figure.add_subplot()
    values = dates.date2num(pd.to_datetime(["2026-10-07T23:59:55Z", "2026-10-08T00:00:00Z", "2026-10-08T00:00:05Z"]))
    axis.set_xlim(values[0], values[-1])
    formatter = RecordingTimeFormatter("UTC")
    axis.xaxis.set_major_formatter(formatter)
    formatter.set_locs(values)
    assert formatter(values[0]) == "23:59:55\n07 Oct 2026"
    assert formatter(values[1]) == "00:00:00\n08 Oct 2026"
    assert formatter(values[2]) == "00:00:05\n"
    axis.set_xlim(values[1], values[2])
    formatter.set_locs(values)
    assert formatter(values[1]).endswith("08 Oct 2026")
    fine = dates.date2num(pd.date_range("2026-10-07T12:00:00Z", periods=7, freq="500ms"))
    axis.set_xlim(fine[0], fine[-1])
    formatter.set_locs(fine)
    assert formatter(fine[0]).startswith("12:00:00.000")
    assert formatter(fine[1]).startswith("12:00:00.500")


def test_selective_json_csv_zip_preserve_native_outputs_precision_and_metadata(tmp_path):
    result = outputs()
    provenance = {"source": "sensor.csv", "settings": {"pipelines": ["tremor"]}}
    names = ["quantifications/tremor", "aggregations/tremor", "metadata/tremor"]
    path = tmp_path / "selection.json"
    export_selection(path, result, provenance, names, "JSON")
    saved_provenance, saved = load_result_export(path)
    assert saved_provenance == provenance
    assert not saved["classifications"]
    pd.testing.assert_frame_equal(saved["quantifications"]["tremor"], result["quantifications"]["tremor"])
    assert saved["aggregations"]["tremor"]["count"] == 2**60 + 1
    export_selection(tmp_path / "selection.zip", result, provenance, names, "CSV")
    with ZipFile(tmp_path / "selection.zip") as archive:
        assert set(archive.namelist()) == {"001_quantifications_tremor.csv", "002_aggregations_tremor.csv", "metadata.json", "analysis.json"}
        pd.testing.assert_frame_equal(pd.read_csv(archive.open("001_quantifications_tremor.csv")), result["quantifications"]["tremor"])
        assert json.loads(archive.read("metadata.json")) == {"metadata/tremor": {"windows": 3}}
    export_selection(tmp_path / "single.csv", result, provenance, [names[0]], "CSV")
    pd.testing.assert_frame_equal(pd.read_csv(tmp_path / "single.csv"), result["quantifications"]["tremor"])


def test_export_dialog_and_single_button_are_consistent_across_tabs(window):
    result = outputs()
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


def test_analyze_time_origin_defaults_reset_and_never_changes_pipeline_arguments(window, monkeypatch):
    from paradigma_desktop import app as desktop
    original = pd.DataFrame({"time": [0., .01, .02], "time_dt": pd.date_range(
        "2026-10-07T12:00:00.123456789Z", periods=3, freq="10ms"),
        **{f"gyroscope_{axis}": [1., 2., 3.] for axis in "xyz"}})
    window.set_modules(["tremor"])
    window.loaded(("sensor.csv", original))
    derived_origin = window.clock_input.text()
    assert pd.Timestamp(derived_origin) == original.time_dt.iloc[0]
    window.clock_input.setText("2020-01-01T08:00:00+02:00")
    window.origin_edited()
    captured = []
    monkeypatch.setattr(desktop, "run_isolated_analysis", lambda frame, settings, logger, cancel: captured.append((frame, settings)))
    monkeypatch.setattr(window, "start_job", lambda function, callback: function(None))
    window.run_analysis()
    assert len(captured) == 1 and "plot_time_origin" not in captured[0][1]
    pd.testing.assert_frame_equal(captured[0][0], original)
    clock = window.current_run["settings"]["plot_time_origin"]["clock"]
    assert pd.Timestamp(clock["origin"]) == pd.Timestamp("2020-01-01T08:00:00+02:00")
    assert clock["timezone"] == "UTC"  # Preserve the recording zone while accepting an explicit offset.
    window.reset_origin()
    assert window.clock_input.text() == derived_origin
    assert window.origin_setting() == {"mode": "automatic"}


def test_zip_export_protects_sources_and_neutralizes_formula_text(tmp_path):
    result = {"quantifications": {"tremor": pd.DataFrame({"time": [0.], "=header": ["=cmd()"]})}, "metadata": {"tremor": {}}}
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
