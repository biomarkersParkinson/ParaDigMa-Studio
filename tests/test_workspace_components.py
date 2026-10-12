"""Composed components work with their declared dependencies, without MainWindow."""

from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from paradigma_studio.history import RunHistory, new_run
from paradigma_studio.recordings import align_recordings
from paradigma_studio.result_controller import ResultCallbacks, ResultController, ResultView
from paradigma_studio.results_view import analysis_alignment
from paradigma_studio.run_controller import RunCallbacks, RunController, RunView
from paradigma_studio.ui.result_overview import ResultOverview
from paradigma_studio.ui.result_series import ResultSeries
from paradigma_studio.widgets import ReadableTable
from paradigma_studio.workspace_state import InputState, ResultState, RunState, SensorState


@pytest.fixture
def result_workspace():
    application = QApplication.instance() or QApplication([])
    parent = QWidget()
    tabs = QTabWidget(parent)
    tabs.addTab(QWidget(), "Overview")
    tabs.addTab(QWidget(), "Graphs")
    view = ResultView(
        QLabel(parent),
        QComboBox(parent),
        QPushButton(parent),
        QPushButton(parent),
        QLabel(parent),
        tabs,
    )
    state, inputs, runs, sensors = ResultState(), InputState(), RunState(), SensorState()
    overview = ResultOverview(QVBoxLayout(QWidget(parent)), QScrollArea(parent))
    tree = QTreeWidget(parent)
    series = ResultSeries(tree)
    rendered, items = {}, {}

    def render(prepared_views):
        rendered["values"], rendered["modules"], rendered["charts"] = overview.render(
            state.results, state.provenance, state.display_clock, prepared_views
        )

    def populate():
        items.clear()
        items.update(series.populate(state._plot_tables, state._plot_labels, state.tables))

    callbacks = ResultCallbacks(
        append_log=Mock(),
        build_result_overview=render,
        populate_result_series=populate,
        selected_result_series=lambda: [
            key for key, item in items.items() if item.checkState(0) == Qt.Checked
        ],
        select_dataset=Mock(),
        sync_table_outputs=Mock(),
        show_notice=Mock(),
        finish_run=Mock(),
        capture_warning=Mock(),
        navigate=Mock(),
        is_busy=lambda: False,
        align_recordings=align_recordings,
        analysis_alignment=analysis_alignment,
    )
    controller = ResultController(state, inputs, runs, sensors, view, callbacks)
    yield SimpleNamespace(
        controller=controller,
        state=state,
        inputs=inputs,
        runs=runs,
        view=view,
        callbacks=callbacks,
        rendered=rendered,
        items=items,
    )
    parent.deleteLater()
    application.processEvents()


@pytest.mark.parametrize("partial", [False, True])
def test_result_components_keep_scientific_frames_and_handle_partial_outputs(
    result_workspace, tremor_outputs, partial
):
    workspace = result_workspace
    workspace.inputs.frame = pd.DataFrame({"time": [0.0, 1.0, 2.0], "gyroscope_x": [1.0, 2.0, 3.0]})
    workspace.inputs.source = "sensor.csv"
    workspace.state.provenance = {"settings": {"skip_preparation": True}}
    record = new_run("sensor.csv", {})
    workspace.runs.active_run = record
    workspace.state._epoch_views["stale"] = object()
    workspace.state._table_views["stale"] = object()
    expected = tremor_outputs["quantifications"]["tremor"].copy(deep=True)
    if partial:
        tremor_outputs["errors"] = [{"pipeline": "gait", "error": "Missing sensor channel"}]

    workspace.controller.analyzed(tremor_outputs)

    assert workspace.state.results is tremor_outputs
    assert workspace.state.result_source_frame is workspace.inputs.frame
    pd.testing.assert_frame_equal(workspace.state.tables["quantifications/tremor"], expected)
    pd.testing.assert_frame_equal(tremor_outputs["quantifications"]["tremor"], expected)
    assert not workspace.state._epoch_views and not workspace.state._table_views
    assert record["_results"] is tremor_outputs and record["_unsaved_results"]
    assert record["_provenance"] == workspace.state.provenance
    assert set(workspace.rendered["modules"]) == {"tremor"}
    assert (
        workspace.items["classifications/tremor", "pred_tremor_checked"].checkState(0) == Qt.Checked
    )
    assert workspace.items["quantifications/tremor", "tremor_power"].checkState(0) == Qt.Unchecked
    assert workspace.view.dataset.currentText() == "classifications/tremor"
    workspace.callbacks.navigate.assert_called_once_with(2)
    if partial:
        workspace.callbacks.finish_run.assert_called_once_with("Partial", tremor_outputs["errors"])
        assert "1 processing error(s)" in workspace.view.status.text()
    else:
        workspace.callbacks.finish_run.assert_called_once_with("Completed")
        assert workspace.view.status.text() == "Analysis completed."


def test_result_component_falls_back_from_invalid_stored_clock(result_workspace, tremor_outputs):
    workspace = result_workspace
    workspace.inputs.frame = pd.DataFrame(
        {
            "time": [0.0, 1.0, 2.0],
            "time_dt": pd.date_range("2026-10-11T12:00:00Z", periods=3, freq="s"),
            "gyroscope_x": [1.0, 2.0, 3.0],
        }
    )
    workspace.state.provenance = {
        "settings": {"skip_preparation": True},
        "display_clock": {"origin": "invalid"},
    }
    workspace.controller.analyzed(tremor_outputs)
    assert pd.Timestamp(workspace.state.display_clock["origin"]) == pd.Timestamp(
        "2026-10-11T12:00:00Z"
    )
    assert workspace.state.provenance["display_clock"] == workspace.state.display_clock
    workspace.callbacks.append_log.assert_called_once_with(
        "Stored recording clock is invalid; using available recording timing."
    )


def test_run_component_deletion_preserves_remaining_runs_after_partial_failure(
    tmp_path, monkeypatch
):
    application = QApplication.instance() or QApplication([])
    parent = QWidget()
    table = ReadableTable()
    table.setParent(parent)
    view = RunView(
        status=QLabel(parent),
        log=QPlainTextEdit(parent),
        run_table=table,
        run_heading=QLabel(parent),
        run_summary=QLabel(parent),
        run_details=QPlainTextEdit(parent),
        run_warnings=QPlainTextEdit(parent),
        run_errors=QPlainTextEdit(parent),
        run_saved=QPlainTextEdit(parent),
        run_outputs=QPlainTextEdit(parent),
        open_run_button=QPushButton(parent),
        use_parameters_button=QPushButton(parent),
        delete_run_button=QPushButton(parent),
        clear_runs_button=QPushButton(parent),
    )
    source = tmp_path / "sensor.csv"
    source.write_text("original sensor samples")
    records = [new_run(str(source), {}) for _ in range(3)]
    state = RunState(runs=records.copy(), current_run=records[0])
    results = ResultState(results={"metadata": {}}, provenance={"source": str(source)})
    history = RunHistory(tmp_path / "runs")
    for record in records:
        history.save(record)
    callbacks = RunCallbacks(
        show_notice=Mock(),
        clear_results=Mock(),
        start_job=Mock(),
        analyzed=Mock(),
        selected_export_table=Mock(),
        is_busy=lambda: False,
        select_run=lambda *args: controller.select_run(*args),
        update_run_actions=lambda *args: controller.update_run_actions(*args),
    )
    controller = RunController(
        state, results, InputState(source=str(source)), history, view, callbacks, parent=parent
    )
    remove = history.remove

    def fail_second(record, *args, **kwargs):
        if record is records[1]:
            raise OSError("Export is locked")
        return remove(record, *args, **kwargs)

    monkeypatch.setattr(history, "remove", fail_second)
    monkeypatch.setattr(QMessageBox, "exec", lambda dialog: QMessageBox.Yes)
    try:
        controller.refresh_runs()
        controller.delete_runs(records[:2])
        assert state.runs == records[1:]
        assert state.current_run is None and results.provenance == {}
        assert source.read_text() == "original sensor samples"
        assert not (history.directory / f"{records[0]['id']}.json").exists()
        assert (history.directory / f"{records[1]['id']}.json").is_file()
        assert view.run_table.model().rowCount() == 2
        callbacks.clear_results.assert_called_once()
        callbacks.show_notice.assert_called_once_with(
            "Could not finish deleting runs (1 deleted): Export is locked", "error"
        )
    finally:
        parent.deleteLater()
        application.processEvents()
