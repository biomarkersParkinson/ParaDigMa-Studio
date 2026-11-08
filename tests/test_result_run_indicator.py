"""Results identify their installed run independently of input/history selection."""

from datetime import datetime

import pandas as pd
import pytest
from conftest import wait_for_job, wait_for_previews
from gui_helpers import dispose_widget
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtTest import QTest
from run_fixtures import make_run

from paradigma_studio.provenance import run_provenance
from paradigma_studio.theme import STYLESHEET
from paradigma_studio.ui.run_indicator import RunIndicator


def install_run(window, results, *, batch=0):
    record = make_run("/recordings/sensor.csv", {"skip_preparation": True})
    record["started"] = "2026-11-08T13:32:00+00:00"
    if batch:
        record["sources"] = {
            f"recording_{index:03d}": f"/recordings/{index:03d}.csv"
            for index in range(1, batch + 1)
        }
    window._run_state.runs.insert(0, record)
    window._run_state.active_run = window._run_state.current_run = record
    window._result_state.provenance = run_provenance(record)
    window._result_state.result_source_frame = window._input_state.frame
    window.analyzed(results)
    return record


def plain_text(indicator):
    document = QTextDocument()
    document.setHtml(indicator.text())
    return document.toPlainText()


@pytest.mark.parametrize("batch", [0, 2, 24])
def test_reference_opens_its_exact_run_after_another_history_row_is_selected(
    window, tremor_outputs, batch
):
    owner = install_run(window, tremor_outputs, batch=batch)
    other = make_run("/recordings/sensor.csv")
    other["started"] = "2026-11-08T14:32:00+00:00"
    window._run_state.runs.insert(0, other)
    window.refresh_runs()
    window.run_table.selectRow(0)
    assert window._run_state.selected_run is other
    window.navigate(2)
    indicator = window.results_source
    started = datetime.fromisoformat(owner["started"]).astimezone().strftime("%d %b %Y, %H:%M")
    summary = f"{batch} recordings" if batch else "sensor.csv"
    assert indicator.accessibleName() == f"Run · {started} · {summary}"
    assert owner["id"] in indicator.toolTip()
    paths = list(owner.get("sources", {}).values()) or [owner["source"]]
    for source in paths[:5]:
        assert source in indicator.toolTip()
    if batch > 5:
        assert paths[-1] not in indicator.toolTip() and "full list in Runs" in indicator.toolTip()
    detail_tab = window._layout.run_detail_tabs.currentIndex()
    QTest.mouseClick(indicator, Qt.MouseButton.LeftButton, pos=QPoint(5, indicator.height() // 2))
    assert window.pages.currentIndex() == 3
    assert window._run_state.selected_run is owner
    assert window.selected_run_records() == [owner]
    assert window._layout.run_detail_tabs.currentIndex() == detail_tab
    assert paths[-1] in window._layout.run_recordings.toPlainText()
    assert window._result_state.results is tremor_outputs


def test_failed_open_and_loading_new_recordings_preserve_the_displayed_reference(
    window, tremor_outputs, tmp_path
):
    owner = install_run(window, tremor_outputs)
    indicator = window.results_source
    text, tooltip = indicator.accessibleName(), indicator.toolTip()
    invalid = make_run("unavailable.csv")
    invalid.update(
        status="Completed",
        _results=tremor_outputs,
        _provenance={"settings": {"plot_time_origin": {"mode": "custom", "clock": {}}}},
    )
    window._run_state.runs.insert(0, invalid)
    window.refresh_runs()
    window.run_table.selectRow(0)
    window.open_run()
    wait_for_job(window)
    assert window._run_state.current_run is owner
    assert window._result_state.results is tremor_outputs
    assert (indicator.accessibleName(), indicator.toolTip()) == (text, tooltip)

    path = tmp_path / "new.csv"
    pd.DataFrame({"time": [0.0, 1.0, 2.0], "gyroscope_x": [1.0, 2.0, 3.0]}).to_csv(
        path, index=False
    )
    window._data_controller._open_paths([path])
    wait_for_job(window)
    wait_for_previews(window)
    assert window._input_state.source == str(path)
    assert window._run_state.selected_run is not owner
    assert (indicator.accessibleName(), indicator.toolTip()) == (text, tooltip)
    assert window._result_state.results is tremor_outputs


def test_successful_reopen_replaces_the_reference(window, tremor_outputs):
    first = install_run(window, tremor_outputs)
    second = make_run("/recordings/second.csv")
    second.update(status="Completed", started="2026-11-09T14:45:00+00:00", _results=tremor_outputs)
    window._run_state.runs.insert(0, second)
    window.refresh_runs()
    window.run_table.selectRow(0)
    assert first["id"] in window.results_source.toolTip()
    window.open_run()
    wait_for_job(window)
    assert window._run_state.current_run is second
    assert second["id"] in window.results_source.toolTip()
    assert first["id"] not in window.results_source.toolTip()
    assert window.results_source.accessibleName().endswith(" · second.csv")


def test_reference_is_shared_by_every_result_view_and_cleared_with_results(window):
    frame = pd.DataFrame({"time": [0.0, 1.0, 2.0], "gyroscope_x": [1.0, 2.0, 3.0]})
    window.loaded(("sensor.csv", frame))
    wait_for_previews(window)
    results = {"quantifications": {"tremor": pd.DataFrame({"time": [0.0], "tremor_power": [1.0]})}}
    owner = install_run(window, results)
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    window.inspect_sensor_context()
    assert window.result_tabs.isTabVisible(window.sensor_tab_index)
    indicator = window.results_source
    for index in (0, 1, 2, window.sensor_tab_index):
        window.result_tabs.setCurrentIndex(index)
        window.resize(960, 650)
        window.repaint()
        assert indicator.isVisible()
        assert owner["id"] in indicator.toolTip()
        assert indicator.parentWidget().layout().indexOf(indicator) == 0
    window.clear_results()
    window.resize(1100, 750)
    assert indicator.isHidden() and indicator.text() == ""
    assert indicator.accessibleName() == "" and indicator.toolTip() == ""


@pytest.mark.parametrize("style,font_size", [("Fusion", 13), ("Windows", 18)])
def test_compact_reference_is_safe_elided_and_keyboard_accessible(qt_app, style, font_size):
    original_style = qt_app.style().objectName()
    qt_app.setStyle(style)
    indicator = RunIndicator()
    try:
        indicator.setStyleSheet(STYLESHEET + f"\nQWidget {{ font-size: {font_size}px; }}")
        source = "long recording name " * 20 + '<private & "special">.csv'
        text = "Run · 08 Nov 2026, 14:32 · " + source
        activated = []
        indicator.linkActivated.connect(activated.append)
        indicator.resize(330, 40)
        indicator.set_reference(text, source, "a" * 32)
        qt_app.processEvents()
        assert plain_text(indicator).startswith("Run · 08 Nov 2026")
        assert plain_text(indicator).endswith("…")
        assert not indicator.wordWrap() and indicator.accessibleName() == text
        assert "&lt;private &amp;" in indicator.toolTip()
        indicator.resize(12000, 40)
        qt_app.processEvents()
        assert plain_text(indicator) == text
        assert indicator.text().count('<a href="') == 1
        indicator.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(indicator, Qt.Key.Key_Return)
        QTest.keyClick(indicator, Qt.Key.Key_Space)
        assert activated == ["a" * 32] * 2
        indicator.clear()
        indicator.resize(500, 40)
        qt_app.processEvents()
        assert indicator.isHidden() and indicator.text() == ""
    finally:
        dispose_widget(indicator)
        qt_app.setStyle(original_style)
