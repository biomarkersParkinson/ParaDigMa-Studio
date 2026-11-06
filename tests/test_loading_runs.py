"""Imports and analysis attempts own their diagnostics independently of selection."""

import logging
import time
from copy import deepcopy
from datetime import datetime, timedelta
from threading import Event

import pytest
from conftest import wait_for_previews
from gui_helpers import wait_until
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QMessageBox
from run_fixtures import make_run, saved_settings

from paradigma_studio import app as desktop, provenance, recordings
from paradigma_studio.history import RunHistory, load_result_export, now
from paradigma_studio.jobs import Worker
from paradigma_studio.provenance import run_provenance
from paradigma_studio.run_lifecycle import analysis_record, close_loading, new_loading_run


def wait_for_job(window):
    deadline = time.monotonic() + 30
    while window._job_state.worker is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        # Yield Python execution as well as Qt events during real import/spawn work.
        time.sleep(0.005)
    assert window._job_state.worker is None


@pytest.fixture
def paths(tmp_path, synthetic_imu):
    result = [tmp_path / "new.csv", tmp_path / "another.csv"]
    for path in result:
        synthetic_imu.iloc[:2000].to_csv(path, index=False)
    return result


@pytest.fixture
def previous(window, synthetic_imu, tremor_outputs):
    window.loaded(("previous.csv", synthetic_imu.iloc[:2000].copy()))
    wait_for_previews(window)
    record = make_run("previous.csv")
    record.update(status="Completed", finished=now(), log="Previous analysis log\n")
    record["_frame"] = window._input_state.frame
    record["_results"] = deepcopy(tremor_outputs)
    record["_provenance"] = run_provenance(record)
    state = window._run_state
    state.runs.append(record)
    state.current_run = state.selected_run = record
    window._result_state.provenance = dict(record["_provenance"])
    window.analyzed(record["_results"])
    window.refresh_runs()
    window._run_controller.persist_run(record)
    return record


def load(window, recording_picker, paths):
    window.navigate(0)
    recording_picker(paths)
    window.open_file()
    wait_for_job(window)
    wait_for_previews(window)
    return window._run_state.runs[0]


@pytest.mark.parametrize("count", [1, 2])
def test_loading_creates_pending_history_without_relabeling_previous_results(
    window, previous, paths, recording_picker, count
):
    previous_log = previous["log"]
    result = window._result_state.results
    record = load(window, recording_picker, paths[:count])
    assert record["status"] == "Loaded" and record["settings"] == {}
    assert record["id"] != previous["id"] and record["outputs"] == []
    assert "analysis_started" not in record and record["finished"] is None
    assert "Found" in record["log"] and "Loading recording_001" in record["log"]
    assert "Preparing initial statistics" in record["log"]
    assert record["loading"]["log"] == record["log"]
    assert record["loading"]["finished"]
    assert window._input_state.load_run_id == record["id"]
    assert window._run_state.current_run is previous
    assert window._result_state.results is result and previous["log"] == previous_log
    assert window._run_state.selected_run is record and window.pages.currentIndex() == 0
    assert not window.open_run_button.isEnabled() and not window.use_parameters_button.isEnabled()
    assert "Analysis has not started" in window._layout.run_details.toPlainText()
    restored, issues = window.history.load()
    assert (
        not issues
        and next(item for item in restored if item["id"] == record["id"])["status"] == "Loaded"
    )


def test_first_analysis_reuses_import_and_later_attempt_keeps_a_separate_snapshot(
    window, previous, paths, recording_picker
):
    first = load(window, recording_picker, paths[:1])
    prefix, original_id = first["log"], first["id"]
    window.set_modules(["tremor"])
    window.side.setCurrentText("left")
    window.run_analysis()
    wait_for_job(window)
    assert window._run_state.current_run is first and first["id"] == original_id
    assert len(window._run_state.runs) == 2 and first["status"] == "Completed"
    assert first["log"].startswith(prefix + "\nAnalysis\n")
    assert datetime.fromisoformat(first["analysis_started"]) >= datetime.fromisoformat(
        first["loading"]["finished"]
    )
    assert not first["_results"]["quantifications"]["tremor"].empty
    frozen = (first["log"], deepcopy(first["settings"]), first["_results"])
    window.side.setCurrentText("right")
    window.run_analysis()
    wait_for_job(window)
    second = window._run_state.current_run
    assert second is not first and second["id"] != original_id
    assert len(window._run_state.runs) == 3
    assert second["loading"]["id"] == original_id
    assert second["log"].startswith(prefix + "\nAnalysis\n")
    assert second["log"].count("\nAnalysis\n") == 1
    assert second["settings"]["watch_side"] == "right" and first["settings"]["watch_side"] == "left"
    assert first["log"] == frozen[0] and first["settings"] == frozen[1]
    assert first["_results"] is frozen[2]
    assert previous["log"] == "Previous analysis log\n"


def test_switching_history_during_load_cannot_redirect_logs_or_warnings(
    window, previous, paths, recording_picker, monkeypatch
):
    entered, release = Event(), Event()
    reader = recordings.load_sensor_file

    def held(path, **kwargs):
        entered.set()
        assert release.wait(10)
        logging.getLogger("paradigma").warning("Warning from the new import")
        return reader(path, **kwargs)

    monkeypatch.setattr(recordings, "load_sensor_file", held)
    recording_picker(paths[:1])
    window.open_file()
    try:
        wait_until(entered.is_set, timeout=5000)
        record = window._run_state.active_run
        assert record["status"] == "Loading"
        row = next(i for i, item in enumerate(window._run_state.runs) if item is previous)
        window.run_table.selectionModel().setCurrentIndex(
            window.run_table.model().index(row, 0),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        assert window._run_state.selected_run is previous
    finally:
        release.set()
        wait_for_job(window)
    assert previous["log"] == "Previous analysis log\n" and previous["warnings"] == []
    assert window.log.toPlainText().rstrip("\n") == previous["log"].rstrip("\n")
    assert "Warning from the new import" in record["log"]
    assert "Warning from the new import" in record["warnings"]
    assert record["loading"]["warnings"] == record["warnings"] and record["status"] == "Loaded"


def test_failed_new_import_does_not_replace_the_pending_successful_batch(
    window, previous, paths, tmp_path, recording_picker
):
    ready = load(window, recording_picker, paths[:1])
    frame = window._input_state.frame
    settings = window._analysis_controller._analysis_settings(["tremor"])
    invalid = tmp_path / "invalid.csv"
    invalid.write_text("time,gyroscope_x\n")
    failed = load(window, recording_picker, [invalid])
    assert failed is not ready and failed["status"] == "Failed"
    assert failed["settings"] == {} and failed["errors"]
    assert failed["loading"]["errors"] == failed["errors"]
    assert window._input_state.frame is frame and window._input_state.load_run_id == ready["id"]
    assert window._analysis_controller._analysis_settings(["tremor"]) == settings
    assert window._run_state.current_run is previous
    window.set_modules(["tremor"])
    window.run_analysis()
    wait_for_job(window)
    assert window._run_state.current_run is ready and ready["status"] == "Completed"
    assert failed["status"] == "Failed"
    assert not window.history.load()[1]


@pytest.mark.parametrize("failure", [False, True])
def test_saving_or_exporting_previous_results_uses_their_owner_after_new_loading(
    window, previous, paths, recording_picker, monkeypatch, tmp_path, failure
):
    pending = load(window, recording_picker, paths[:1])
    prefix = pending["log"]
    if failure:

        def fail(*args, **kwargs):
            raise OSError("Old result export failed")

        monkeypatch.setattr(desktop, "export_results", fail)
        monkeypatch.setattr(
            desktop.QFileDialog,
            "getSaveFileName",
            lambda *args: (str(tmp_path / "output.json"), "JSON"),
        )
        window.export()
        assert "Old result export failed" in previous["log"]
        assert previous["status"] == "Completed"
    else:
        window.save_results()
        wait_for_job(window)
        output = next(item for item in previous["outputs"] if item.get("local"))
        origin, result = load_result_export(output["path"])
        assert origin["run_id"] == previous["id"]
        assert len(result["quantifications"]["tremor"]) == 3
    assert pending["log"] == prefix and pending["status"] == "Loaded" and pending["outputs"] == []
    assert window._run_state.current_run is previous


def test_unrelated_worker_messages_cannot_write_to_the_current_loading_record(window):
    owner = window._run_controller.start_loading(["new.csv"])
    entered, release = Event(), Event()

    def operation(logger):
        entered.set()
        assert release.wait(5)
        logger.info("Owned job message")

    window.start_job(operation, lambda _: None)
    foreign = Worker(lambda _: None)
    window._connect_worker(foreign, lambda _: None)
    try:
        wait_until(entered.is_set)
        foreign.message.emit("Foreign message")
        foreign.warning.emit("Foreign warning")
        assert "Foreign" not in owner["log"] and owner["warnings"] == []
    finally:
        release.set()
        wait_for_job(window)
        foreign.deleteLater()
    assert "Owned job message" in owner["log"]
    window.finish_run("Cancelled")


def test_import_log_messages_do_not_cause_per_message_history_writes(
    window, paths, recording_picker, monkeypatch
):
    saved, reader, save = [], recordings.load_sensor_file, window.history.save

    def observe(record):
        saved.append(record["id"])
        return save(record)

    def verbose(path, **kwargs):
        for index in range(200):
            logging.getLogger("paradigma").info("Import milestone %s", index)
        return reader(path, **kwargs)

    monkeypatch.setattr(window.history, "save", observe)
    monkeypatch.setattr(recordings, "load_sensor_file", verbose)
    record = load(window, recording_picker, paths[:1])
    assert record["log"].count("Import milestone") == 200
    assert len(saved) <= 5 and set(saved) == {record["id"]}


@pytest.mark.parametrize("choice", ["picker", "pickle", "empty-folder"])
def test_cancelled_picker_or_import_is_recorded_without_changing_old_inputs(
    window, previous, tmp_path, recording_picker, monkeypatch, choice
):
    frame = window._input_state.frame
    if choice == "picker":
        selection = []
    elif choice == "pickle":
        source = tmp_path / "trusted.pkl"
        frame.to_pickle(source)
        selection = [source]
        monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.No)
    else:
        source = tmp_path / "empty"
        source.mkdir()
        selection = [source]
    recording_picker(selection, folders=choice == "empty-folder")
    if choice == "empty-folder":
        window._layout.open_folder_action.trigger()
    else:
        window.open_file()
    wait_for_job(window)
    assert window._input_state.frame is frame and window._run_state.current_run is previous
    assert previous["log"] == "Previous analysis log\n"
    if choice == "picker":
        assert window._run_state.runs == [previous]
    else:
        record = window._run_state.runs[0]
        assert record["status"] == ("Cancelled" if choice == "pickle" else "Failed")
        assert record["loading"]["finished"] and record["settings"] == {}
        assert not window.history.load()[1]


def test_analysis_captures_its_software_identity_while_retaining_loader_identity(monkeypatch):
    versions = {"paradigma-studio": "1.0", "paradigma": "1.1.2"}
    monkeypatch.setattr(provenance, "version", versions.__getitem__)
    record = new_loading_run(["sensor.csv"])
    close_loading(record, now())
    record["status"] = "Loaded"
    versions.update({"paradigma-studio": "2.0", "paradigma": "1.2"})
    actual = analysis_record(record, "sensor.csv", saved_settings(), record["loading"])
    assert actual is record and actual["studio_version"] == "2.0"
    assert actual["loading"]["software"]["studio_version"] == "1.0"
    origin = run_provenance(actual)
    assert origin["analysis_started"] == actual["analysis_started"]
    assert origin["loading"]["software"]["paradigma_version"] == "1.1.2"


@pytest.mark.parametrize("status", ["Loading", "Loaded", "Failed", "Cancelled"])
def test_import_history_survives_restart_without_claiming_analysis_results(tmp_path, status):
    history = RunHistory(tmp_path / "runs")
    record = new_loading_run(["folder", "another-folder"])
    record["status"] = status
    if status != "Loading":
        close_loading(record, now())
    if status in ("Failed", "Cancelled"):
        record["finished"] = record["loading"]["finished"]
    history.save(record)
    restored, issues = history.load()
    assert not issues and len(restored) == 1
    assert restored[0]["status"] == ("Unfinished" if status == "Loading" else status)
    assert restored[0]["settings"] == {} and restored[0]["outputs"] == []
    assert restored[0]["loading"] == record["loading"]
    with pytest.raises(ValueError, match="no analysis results"):
        history.save_results(record, {}, {})


@pytest.mark.parametrize(
    "fault",
    [
        "completed",
        "settings",
        "outputs",
        "missing-time",
        "bad-selection",
        "bad-software",
        "bad-build",
        "analysis-before-load",
        "null-loading",
        "null-analysis",
    ],
)
def test_loading_history_validation_does_not_admit_fake_analysis_outcomes(tmp_path, fault):
    history = RunHistory(tmp_path / "runs")
    record = new_loading_run(["sensor.csv"])
    close_loading(record, now())
    record["status"] = "Loaded"
    if fault == "completed":
        record["status"] = "Completed"
    elif fault == "settings":
        record["settings"] = saved_settings()
    elif fault == "outputs":
        record["outputs"] = [{"kind": "CSV", "path": "fake.csv", "saved": now(), "complete": False}]
    elif fault == "missing-time":
        record["loading"].pop("finished")
    elif fault == "bad-selection":
        record["loading"]["selections"] = []
    elif fault == "bad-software":
        record["loading"]["software"]["studio_version"] = 10
    elif fault == "bad-build":
        record["loading"]["software"]["studio_build_commit"] = "bad"
    elif fault == "null-loading":
        record["loading"] = None
    elif fault == "null-analysis":
        record["analysis_started"] = None
    else:
        record = analysis_record(record, record["source"], saved_settings(), record["loading"])
        record["analysis_started"] = (
            datetime.fromisoformat(record["loading"]["finished"]) - timedelta(seconds=1)
        ).isoformat()
    history.save(record)
    restored, issues = history.load()
    assert restored == [] and len(issues) == 1
