"""Compact module notices route to the displayed result's own run details."""

from copy import deepcopy

import pandas as pd
import pytest
from conftest import wait_for_job
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton
from run_fixtures import make_run

from paradigma_studio.history import merge_errors, now
from paradigma_studio.provenance import run_provenance


def results(count=50):
    return {
        "errors": [
            {
                "pipeline": "tremor",
                "stage": "pipeline_execution",
                "file": f"recording_{index // 2 + 1:03d}__segment_{index % 2 + 1}",
                "error": "Classification failed: Original detailed failure",
            }
            for index in range(count)
        ],
        "quantifications": {"tremor": pd.DataFrame({"time": [0.0], "tremor_power": [1.0]})},
    }


def install_owned(window, values):
    record = make_run(settings={"pipelines": ["tremor"]})
    record.update(
        sources={
            key: f"/recordings/{key}.csv"
            for key in sorted(
                {error["file"].split("__segment_", 1)[0] for error in values["errors"]}
            )
        },
        status="Partial",
        finished=now(),
        errors=merge_errors([], values["errors"]),
    )
    window._run_state.runs.insert(0, record)
    window._run_state.current_run = window._run_state.selected_run = record
    window._result_state.provenance = run_provenance(record)
    window.analyzed(values)
    record["_results"] = values
    record["_provenance"] = deepcopy(window._result_state.provenance)
    window.refresh_runs()
    return record


def summary(window, module="tremor"):
    card = window._result_state.overview_module_cards[module]
    notices = [item for item in card.findChildren(QLabel) if item.objectName() == "notice"]
    links = card.findChildren(QPushButton, "overviewRunErrors")
    return notices, links


@pytest.mark.parametrize("style", ["Fusion", "Windows"])
@pytest.mark.parametrize("font_size", [13, 18])
def test_large_batch_has_one_readable_summary_in_compact_and_wide_views(
    styled_window, style, font_size
):
    window = styled_window
    values = results(500)
    original = deepcopy(values)
    install_owned(window, values)
    for size in ((1450, 1000), (960, 650)):
        window.resize(*size)
        QTest.qWait(30)
        notices, links = summary(window)
        assert len(notices) == len(links) == 1
        assert (
            notices[0].text() == "Partial results\n500 processing errors affecting 250 recordings."
        )
        assert notices[0].property("severity") == "warning"
        assert notices[0].wordWrap() and notices[0].height() < 180
        assert "Original detailed failure" not in notices[0].text()
        window._layout._result_view_scrolls[0].ensureWidgetVisible(links[0])
        QTest.qWait(10)
        assert links[0].isVisible()
    assert values["errors"] == original["errors"]
    pd.testing.assert_frame_equal(
        values["quantifications"]["tremor"], original["quantifications"]["tremor"]
    )


@pytest.mark.parametrize("activation", ["mouse", "keyboard"])
def test_details_link_selects_its_original_run_after_another_batch_loads(window, activation):
    values = results(2)
    owner = install_owned(window, values)
    old_results = window._result_state.results
    _, links = summary(window)
    link = links[0]
    pending = window._run_controller.start_loading(["new.csv"])
    window.loaded(("new.csv", pd.DataFrame({"time": [0.0, 1.0]})))
    assert pending["status"] == "Loaded" and window._run_state.selected_run is pending
    window.navigate(2)
    if activation == "mouse":
        link.click()
    else:
        link.setFocus()
        QTest.keyClick(link, Qt.Key.Key_Space)
    assert window.pages.currentIndex() == 3
    assert window._run_state.selected_run is owner
    assert window._layout.run_detail_tabs.currentWidget() is window.run_errors
    assert window.run_errors.toPlainText() == "\n\n".join(owner["errors"])
    assert window._run_state.current_run is owner and window._result_state.results is old_results
    assert window._input_state.source == "new.csv" and pending["errors"] == []


def test_missing_outputs_still_show_failed_module_and_successful_cards_stay_clean(window):
    values = {"errors": [{"pipeline": "gait", "error": "Original gait failure"}]}
    window.analyzed(values)
    notices, links = summary(window, "gait")
    assert notices[0].text().startswith("No results available\n1 processing error.")
    assert notices[0].property("severity") == "error" and links == []
    window.analyzed({"aggregations": {"tremor": {"perc_windows_tremor": 0}}})
    assert summary(window) == ([], [])


def test_reopening_preserves_counts_and_owner_link_without_original_recordings(window_factory):
    with window_factory(show=False) as first:
        values = results(4)
        owner = install_owned(first, values)
        first._run_controller.save_run_results([owner])
        wait_for_job(first)
        directory = first.history.directory
        run_id = owner["id"]
    with window_factory(show=False) as restored:
        from paradigma_studio.history import RunHistory

        restored.history = RunHistory(directory)
        restored._run_controller.history = restored.history
        restored._run_state.runs, issues = restored.history.load()
        assert not issues
        restored.refresh_runs()
        restored.open_run()
        wait_for_job(restored)
        notices, links = summary(restored)
        assert "4 processing errors affecting 2 recordings" in notices[0].text()
        links[0].click()
        assert restored._run_state.selected_run["id"] == run_id
        assert restored._layout.run_detail_tabs.currentWidget() is restored.run_errors
        assert restored._input_state.frame is None
