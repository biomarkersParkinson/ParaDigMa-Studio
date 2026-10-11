"""Native multi-selection and confirmed deletion without losing other data."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
import pytest

from paradigma_studio.app import MainWindow
from paradigma_studio.history import new_run


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = MainWindow(tmp_path / "runs")
    source = tmp_path / "sensor.csv"
    source.write_text("original sensor data")
    widget.runs = [new_run(str(source), {}) for _ in range(5)]
    for record in widget.runs:
        record["status"] = "Completed"
        widget.history.save(record)
    widget.refresh_runs()
    widget.navigate(3)
    widget.show()
    QTest.qWait(30)
    yield widget
    widget.close()
    app.processEvents()


def click_row(window, row, modifier=Qt.NoModifier):
    index = window.run_table.model().index(row, 0)
    QTest.mouseClick(
        window.run_table.viewport(),
        Qt.LeftButton,
        modifier,
        window.run_table.visualRect(index).center(),
    )
    QApplication.processEvents()


def test_ctrl_shift_selection_survives_refresh_and_single_run_actions_follow_selection(window):
    click_row(window, 0)
    click_row(window, 2, Qt.ControlModifier)
    assert window.selected_run_records() == [window.runs[0], window.runs[2]]
    assert window.delete_run_button.text() == "Delete 2 Runs…"
    assert not window.use_parameters_button.isEnabled()
    window.refresh_runs()
    assert window.selected_run_records() == [window.runs[0], window.runs[2]]
    assert window.selected_run is window.runs[2]
    click_row(window, 1)
    click_row(window, 3, Qt.ShiftModifier)
    assert window.selected_run_records() == window.runs[1:4]
    click_row(window, 0)
    click_row(window, 2, Qt.ControlModifier)
    click_row(window, 2, Qt.ControlModifier)  # Current row deselected; row 0 remains.
    assert window.selected_run_records() == [window.runs[0]]
    assert window.selected_run is window.runs[0]
    assert window.use_parameters_button.isEnabled()


@pytest.mark.parametrize("confirm", [False, True])
def test_bulk_delete_key_confirms_once_and_respects_shared_exports(
    window, tmp_path, monkeypatch, confirm
):
    selected_shared, retained_shared = tmp_path / "selected.json", tmp_path / "retained.json"
    selected_shared.write_text("shared only by runs being deleted")
    retained_shared.write_text("also used by a run being kept")
    original_runs = list(window.runs)
    for record in original_runs[:2]:
        record["outputs"] = [
            {"kind": "JSON", "path": str(path)} for path in (selected_shared, retained_shared)
        ]
        record["outputs"].append({"kind": "CSV", "path": record["source"]})
        window.history.save(record)
    original_runs[2]["outputs"] = [{"kind": "JSON", "path": str(retained_shared)}]
    window.history.save(original_runs[2])
    window.refresh_runs()
    click_row(window, 0)
    click_row(window, 1, Qt.ControlModifier)
    prompts = []

    def answer(dialog):
        prompts.append(dialog)
        assert dialog.defaultButton().text() == "Cancel"
        assert "2 runs" in dialog.text()
        assert "1 export file(s)" in dialog.informativeText()
        assert str(selected_shared) in dialog.detailedText()
        assert str(retained_shared) not in dialog.detailedText()
        assert "color: #22324a" in dialog.styleSheet()
        return QMessageBox.Yes if confirm else QMessageBox.Cancel

    monkeypatch.setattr(QMessageBox, "exec", answer)
    window.run_table.setFocus()
    QTest.keyClick(window.run_table, Qt.Key_Delete)
    QApplication.processEvents()
    assert len(prompts) == 1
    assert len(window.runs) == (3 if confirm else 5)
    assert selected_shared.exists() != confirm
    assert retained_shared.exists()
    assert (tmp_path / "sensor.csv").read_text() == "original sensor data"
    for record in original_runs:
        assert (window.history.directory / (record["id"] + ".json")).exists() == (
            not confirm or record in original_runs[2:]
        )


@pytest.mark.parametrize("confirm", [False, True])
def test_clear_all_deletes_every_run_after_one_readable_confirmation(
    window, tmp_path, monkeypatch, confirm
):
    output = tmp_path / "shared.json"
    output.write_text("export")
    for record in window.runs:
        record["outputs"] = [{"kind": "JSON", "path": str(output)}]
        window.history.save(record)
    window.current_run = window.runs[0]
    window.results = {}
    prompts = []

    def answer(dialog):
        prompts.append(dialog)
        assert "all runs" in dialog.text()
        assert "5 history entry/entries" in dialog.informativeText()
        assert "1 export file(s)" in dialog.informativeText()
        assert "Original sensor files" in dialog.informativeText()
        assert dialog.defaultButton().text() == "Cancel"
        return QMessageBox.Yes if confirm else QMessageBox.Cancel

    monkeypatch.setattr(QMessageBox, "exec", answer)
    window.clear_runs_button.click()
    assert len(prompts) == 1
    assert len(window.runs) == (0 if confirm else 5)
    assert output.exists() != confirm
    assert (tmp_path / "sensor.csv").exists()
    assert len(list(window.history.directory.glob("*.json"))) == (0 if confirm else 5)
    if confirm:
        assert window.current_run is None and window.results is None
        assert not window.clear_runs_button.isEnabled() and not window.delete_run_button.isEnabled()


def test_partial_deletion_error_keeps_ui_in_sync_and_reports_error(window, monkeypatch):
    original_runs = list(window.runs)
    remove = window.history.remove

    def fail_second(record, *args, **kwargs):
        if record is original_runs[1]:
            raise OSError("export is locked")
        return remove(record, *args, **kwargs)

    monkeypatch.setattr(window.history, "remove", fail_second)
    monkeypatch.setattr(QMessageBox, "exec", lambda _: QMessageBox.Yes)
    window.clear_runs_button.click()
    assert window.runs == original_runs[1:]
    assert len(list(window.history.directory.glob("*.json"))) == 4
    assert "1 deleted" in window.notice.text() and "export is locked" in window.notice.text()


def test_clear_and_selected_delete_are_disabled_during_background_work(window):
    window.worker = object()
    window.update_run_actions()
    assert not window.clear_runs_button.isEnabled() and not window.delete_run_button.isEnabled()
    window.clear_runs()
    assert len(window.runs) == 5
    window.worker = None
