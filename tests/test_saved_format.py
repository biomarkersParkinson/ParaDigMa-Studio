"""Current files round-trip; unsupported files never acquire inferred settings."""

import hashlib
import json
import logging

import pandas as pd
import pytest
from run_fixtures import export_receipt, make_run, saved_settings

from paradigma_studio.history import RunHistory, load_result_export, new_run
from paradigma_studio.result_reopening import load_saved_results
from paradigma_studio.run_controller import RunController
from paradigma_studio.saved_format import FORMAT_VERSION, RESULT_FORMAT, RUN_FORMAT
from paradigma_studio.serialization import export_results


def test_current_run_and_result_contracts_round_trip_without_rewriting_files(tmp_path):
    history = RunHistory(tmp_path)
    settings = saved_settings()
    record = new_run("sensor.csv", settings)
    record["status"] = "Completed"
    record["extension"] = {"label": "retained"}
    assert record["settings"] is settings
    results = {"quantifications": {"tremor": pd.DataFrame({"time": [0.0], "value": [2.0]})}}
    record["outputs"] = history.save_results(record, results, {"settings": settings})
    path = tmp_path / f"{record['id']}.json"
    before = path.read_bytes()
    records, issues = history.load()
    assert not issues and records == [record]
    assert path.read_bytes() == before
    assert json.loads(before)["format"] == RUN_FORMAT
    assert json.loads(before)["format_version"] == FORMAT_VERSION
    output = record["outputs"][0]
    provenance, restored = load_saved_results(
        output["path"], logging.getLogger(__name__), run_id=record["id"], checksum=output["sha256"]
    )
    assert provenance["run_id"] == record["id"]
    pd.testing.assert_frame_equal(
        restored["quantifications"]["tremor"], results["quantifications"]["tremor"]
    )


@pytest.mark.parametrize("version", [None, 0, 1, FORMAT_VERSION + 1, True, 2.0, "2"])
def test_unsupported_history_is_reported_without_hiding_current_runs_or_touching_files(
    tmp_path, version
):
    history = RunHistory(tmp_path)
    current, unsupported = make_run("current.csv"), make_run("earlier.csv")
    current["status"] = "Completed"
    history.save(current)
    if version is None:
        unsupported.pop("format_version")
    else:
        unsupported["format_version"] = version
    path = tmp_path / f"{unsupported['id']}.json"
    path.write_text(json.dumps(unsupported))
    before = path.read_bytes()
    records, issues = history.load()
    assert records == [current]
    assert len(issues) == 1 and "Unsupported run history format" in issues[0]
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="Unsupported run history format"):
        history.save(unsupported)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "field", ["finished", "studio_version", "paradigma_version", "errors", "log"]
)
def test_current_history_requires_fields_instead_of_filling_them_in(tmp_path, field):
    history = RunHistory(tmp_path)
    record = make_run()
    record.pop(field)
    history.save(record)
    assert not history.load()[0]
    assert len(history.load()[1]) == 1


@pytest.mark.parametrize(
    "field",
    [
        "pipelines",
        "watch_side",
        "accelerometer_units",
        "gyroscope_units",
        "time_input_unit",
        "signal_columns",
        "axis_inversions",
        "column_mapping",
        "split_by_gaps",
        "drop_missing_samples",
        "max_gap_seconds",
        "min_segment_seconds",
        "plot_time_origin",
    ],
)
def test_current_history_requires_explicit_analyze_settings(tmp_path, field):
    history = RunHistory(tmp_path)
    record = make_run()
    record["settings"].pop(field)
    history.save(record)
    records, issues = history.load()
    assert not records and len(issues) == 1


@pytest.mark.parametrize(
    "settings",
    [
        {"skip_preparation": False},
        {"device_orientation": ["-y", "x", "z"]},
        {"column_mapping": {"unused": "temperature"}},
        {"column_mapping": {"other_clock": "time"}},
        {"plot_time_origin": {"mode": "custom", "clock": {}}},
    ],
)
def test_retired_or_inconsistent_settings_are_not_interpreted(tmp_path, settings):
    history = RunHistory(tmp_path)
    history.save(make_run(settings=settings))
    records, issues = history.load()
    assert not records and len(issues) == 1


@pytest.mark.parametrize("isolate_bytes", [0, 10**9])
@pytest.mark.parametrize("version", [None, 1, FORMAT_VERSION + 1])
def test_unsupported_results_are_rejected_even_with_correct_owner_and_checksum(
    tmp_path, isolate_bytes, version
):
    path = tmp_path / "results.json"
    run_id = "1" * 32
    export_results(path, {"errors": []}, {"run_id": run_id})
    value = json.loads(path.read_text())
    assert value["format"] == RESULT_FORMAT
    if version is None:
        value.pop("format_version")
    else:
        value["format_version"] = version
    path.write_text(json.dumps(value))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Unsupported result export format"):
        load_result_export(path)
    with pytest.raises(ValueError, match="Unsupported result export format"):
        load_saved_results(
            path,
            logging.getLogger(__name__),
            run_id=run_id,
            checksum=hashlib.sha256(before).hexdigest(),
            isolate_bytes=isolate_bytes,
        )
    assert path.read_bytes() == before


def test_export_reopening_requires_explicit_completeness():
    record = make_run()
    output = {"kind": "JSON", "path": "results.json", "sha256": "0" * 64}
    record["outputs"] = [output]
    assert RunController.reopen_output(record) is None
    output["complete"] = False
    assert RunController.reopen_output(record) is None
    output["complete"] = True
    assert RunController.reopen_output(record) is output


@pytest.mark.parametrize("field", ["saved", "complete", "sha256"])
def test_current_history_requires_json_export_receipts(tmp_path, field):
    history = RunHistory(tmp_path / "runs")
    path = tmp_path / "results.json"
    export_results(path, {"errors": []}, {})
    record = make_run()
    receipt = export_receipt(path)
    receipt.pop(field)
    record["outputs"] = [receipt]
    history.save(record)
    records, issues = history.load()
    assert not records and len(issues) == 1


@pytest.mark.parametrize(
    "document",
    [
        None,
        [],
        {},
        {"format": RUN_FORMAT, "format_version": FORMAT_VERSION, "analysis": {}, "results": {}},
    ],
)
def test_result_decoder_requires_the_result_document_kind(tmp_path, document):
    path = tmp_path / "wrong-kind.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Unsupported result export format"):
        load_result_export(path)
