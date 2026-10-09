"""Readable source extent and elapsed coverage of actual prepared inputs."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication, QLabel

from paradigma_desktop.app import MainWindow
from paradigma_desktop.availability import prepared_availability
from paradigma_desktop.core import export_results
from paradigma_desktop.history import load_result_export
from paradigma_desktop.overview import recording_extent, recording_summary


def result(sections):
    return {"metadata": {"desktop_availability": sections}, "errors": []}


def section(intervals, samples=123):
    return {"df_1": {"samples": samples, "intervals": intervals}}


def provenance(start=0.0, end=7200.0, **extra):
    return {"recording_extent": {"start_s": start, "end_s": end}, **extra}


def test_prepared_hours_percentage_and_internal_gaps_replace_raw_preparation_counts():
    prepared = section([[60.0, 1860.0], [3660.0, 5460.0]])
    output = result({"gait": prepared, "tremor": deepcopy(prepared)})
    output["metadata"]["desktop_preparation"] = {
        "input_samples": 7200,
        "analyzed_samples": 3600,
        "continuous_sections": 2,
        "excluded_samples": 3600,
    }
    original = deepcopy(output)
    entries = dict(
        recording_summary(
            output,
            provenance(),
            {"origin": "2026-10-07T10:00:00+02:00", "timezone": "Europe/Amsterdam"},
        )
    )
    assert entries["Recording timespan"] == (
        "07 Oct 2026, 10:00:00 – 07 Oct 2026, 12:00:00 · Europe/Amsterdam"
    )
    assert entries["Gait, Tremor · Data coverage (prepared)"] == "1.00 h · 50.0% of timespan"
    assert entries["Gait, Tremor · Gaps"] == "1"
    assert "Input samples" not in entries
    assert not {"Prepared samples", "Prepared sections", "Time origin"}.intersection(entries)
    assert output == original


def test_removed_recording_boxes_stay_absent_for_current_and_legacy_metadata():
    output = {
        "metadata": {
            "desktop_recordings": {"recordings": ["first", "second"]},
            "recording": {"input_samples": 99, "n_samples": 99, "duration_s": 30},
            "desktop_preparation": {
                "input_samples": 99,
                "by_module": {"gait": {"input_samples": 99, "excluded_samples": 1}},
            },
        }
    }
    original = deepcopy(output)
    entries = dict(
        recording_summary(output, {"sources": {"first": "a.csv", "second": "b.csv"}}, None)
    )
    assert not any(
        name in ("Recordings", "Files") or name.endswith("Input samples") or name == "N samples"
        for name in entries
    )
    assert entries["Gait · Excluded missing samples"] == "1"
    assert output == original


@pytest.mark.parametrize("hz", [50, 100])
def test_coverage_uses_elapsed_prepared_intervals_at_different_sampling_rates(hz):
    frames = pd.DataFrame({"time": np.arange(3600 * hz) / hz})
    output = result(prepared_availability(frames, ["tremor"]))
    entries = dict(recording_summary(output, provenance(), None))
    assert entries["Tremor · Data coverage (prepared)"] == "1.00 h · 50.0% of timespan"
    assert entries["Tremor · Gaps"] == "0"


def test_overlapping_files_are_not_counted_twice_and_offsets_apply_to_each_module():
    sections = {"a": {"intervals": [[0.0, 3600.0]]}, "b": {"intervals": [[0.0, 3600.0]]}}
    output = result({"gait": sections, "pulse_rate": section([[0.0, 1800.0]])})
    saved = provenance(
        end=5400.0, display_offsets={"gait": {"a": 0.0, "b": 1800.0}, "pulse_rate": 3600.0}
    )
    entries = dict(recording_summary(output, saved, None))
    assert entries["Gait · Data coverage (prepared)"] == "1.50 h · 100.0% of timespan"
    assert entries["Gait · Gaps"] == "0"
    assert entries["Pulse rate · Data coverage (prepared)"] == "0.50 h · 33.3% of timespan"
    assert entries["Pulse rate · Gaps"] == "0"


def test_empty_preparation_has_zero_coverage_without_inventing_a_gap():
    entries = dict(recording_summary(result({"tremor": section([])}), provenance(), None))
    assert entries["Tremor · Data coverage (prepared)"] == "0 h · 0.0% of timespan"
    assert entries["Tremor · Gaps"] == "0"


def test_original_recording_extent_includes_excluded_edges_and_final_sample():
    assert recording_extent(np.array([-2.0, -1.0, 0.0, 1.0, 7.0, 8.0, np.nan])) == {
        "start_s": -2.0,
        "end_s": 9.0,
    }
    assert recording_extent(
        {"a": np.arange(3.0), "b": np.arange(3.0)}, {"a": 0.0, "b": 86400.0}
    ) == {"start_s": 0.0, "end_s": 86403.0}
    assert recording_extent(None) is None
    assert recording_extent(np.array([np.nan])) is None


def test_daylight_saving_uses_elapsed_hours_and_distinguishes_repeated_clock_times():
    entries = dict(
        recording_summary(
            result({"tremor": section([[0.0, 3600.0]])}),
            provenance(end=3600.0),
            {"origin": "2026-10-25T02:30:00+02:00", "timezone": "Europe/Amsterdam"},
        )
    )
    assert entries["Recording timespan"] == (
        "25 Oct 2026, 02:30:00 CEST – 25 Oct 2026, 02:30:00 CET · Europe/Amsterdam"
    )
    assert entries["Tremor · Data coverage (prepared)"] == "1.00 h · 100.0% of timespan"


def test_legacy_export_without_source_extent_does_not_invent_percentage_or_dates():
    entries = dict(
        recording_summary(result({"gait": section([[0.0, 3600.0], [7200.0, 10800.0]])}), {}, None)
    )
    assert entries["Gait · Data coverage (prepared)"] == "2.00 h · Timespan unavailable"
    assert entries["Gait · Gaps"] == "1"
    assert "Recording timespan" not in entries


def test_tiny_recording_shows_nonzero_hours_and_roundoff_does_not_create_a_gap():
    entries = dict(
        recording_summary(
            result({"gait": section([[0.0, 1.0], [1.0 + 1e-12, 2.0]])}), provenance(end=2.0), None
        )
    )
    assert entries["Gait · Data coverage (prepared)"] == "0.000556 h · 100.0% of timespan"
    assert entries["Gait · Gaps"] == "0"


def test_timespan_and_coverage_survive_reopening_without_sensor_files(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path / "runs")
    start = pd.Timestamp("2026-10-07T10:00:00Z")
    frame = pd.DataFrame(
        {
            "time": start.timestamp() + np.arange(10.0),
            **{f"gyroscope_{axis}": np.ones(10) for axis in "xyz"},
        }
    )
    frame.loc[[0, 1, 4, 9], "gyroscope_x"] = np.nan
    output = result({"tremor": section([[0.0, 2.0], [3.0, 7.0]])})
    window.frame = frame
    window.provenance = {
        "source": "missing.csv",
        "settings": {
            "pipelines": ["tremor"],
            "time_input_unit": "absolute_s",
            "drop_missing_samples": True,
        },
    }
    try:
        window.analyzed(output)
        entries = recording_summary(output, window.provenance, window.display_clock)
        assert window.provenance["recording_extent"] == {"start_s": -2.0, "end_s": 8.0}
        assert (
            dict(entries)["Recording timespan"]
            == "07 Oct 2026, 10:00:00 – 07 Oct 2026, 10:00:10 · UTC"
        )
        assert (
            dict(entries)["Tremor · Data coverage (prepared)"] == "0.001667 h · 60.0% of timespan"
        )
        assert dict(entries)["Tremor · Gaps"] == "1"
        path = tmp_path / "results.json"
        export_results(path, output, window.provenance)
        window.provenance, saved = load_result_export(path)
        window.frame = None
        window.analyzed(saved)
        assert recording_summary(saved, window.provenance, window.display_clock) == entries
        texts = [label.text() for label in window.overview_content.findChildren(QLabel)]
        assert dict(entries)["Recording timespan"] in texts
        assert dict(entries)["Tremor · Data coverage (prepared)"] in texts
    finally:
        window.close()
        app.processEvents()


def test_multiple_recording_clocks_include_between_file_gaps_in_the_timespan(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path / "runs")
    keys = ["first", "second"]
    start = pd.Timestamp("2026-10-07T10:00:00Z")
    frames = {
        key: pd.DataFrame(
            {
                "time": start.timestamp() + day * 86400 + np.arange(3600.0),
                **{f"gyroscope_{axis}": np.ones(3600) for axis in "xyz"},
            }
        )
        for day, key in enumerate(keys)
    }
    output = result(
        {"tremor": {key: {"samples": 3600, "intervals": [[0.0, 3600.0]]} for key in keys}}
    )
    output["metadata"]["desktop_recordings"] = {
        "recordings": keys,
        "sections": {key: key for key in keys},
    }
    window.recordings = frames
    window.provenance = {
        "sources": {key: key + ".csv" for key in keys},
        "settings": {"pipelines": ["tremor"], "time_input_unit": "absolute_s"},
    }
    try:
        window.analyzed(output)
        entries = dict(recording_summary(output, window.provenance, window.display_clock))
        assert (
            entries["Recording timespan"] == "07 Oct 2026, 10:00:00 – 08 Oct 2026, 11:00:00 · UTC"
        )
        assert entries["Tremor · Data coverage (prepared)"] == "2.00 h · 8.0% of timespan"
        assert entries["Tremor · Gaps"] == "1"
    finally:
        window.close()
        app.processEvents()
