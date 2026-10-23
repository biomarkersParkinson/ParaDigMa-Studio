"""Results page construction and deferred callbacks with only declared dependencies."""

from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from matplotlib.backend_bases import MouseEvent
from PySide6.QtWidgets import QApplication, QListWidget, QMainWindow, QVBoxLayout, QWidget

from paradigma_studio.ui.deferred import DeferredWidget
from paradigma_studio.ui.results_page import ResultsPage, ResultsPageHost
from paradigma_studio.ui.workspace_callbacks import WorkspaceCallbacks
from paradigma_studio.workspace_state import GraphState, ResultState


@pytest.fixture
def results_page():
    application = QApplication.instance() or QApplication([])
    parent = QMainWindow()
    container = QWidget()
    parent.setCentralWidget(container)
    callbacks = WorkspaceCallbacks(**{field.name: Mock() for field in fields(WorkspaceCallbacks)})
    callbacks.selected_result_series.return_value = []
    initialized = []

    def channel_graph(select_channels, accessible_name, prefix):
        graph = QWidget()
        graph_layout = QVBoxLayout(graph)
        channels = QListWidget()
        channels.setAccessibleName(accessible_name)
        deferred = DeferredWidget(lambda: initialized.append(prefix))
        graph_layout.addWidget(channels)
        graph_layout.addWidget(deferred)
        return graph, channels, deferred

    sensor_graphics = Mock(side_effect=AssertionError("Sensor canvas must stay deferred"))
    state = ResultState()
    page = ResultsPage(
        ResultsPageHost(parent, QVBoxLayout(container), channel_graph, sensor_graphics),
        callbacks,
        GraphState(),
        state,
    )
    yield SimpleNamespace(
        page=page,
        callbacks=callbacks,
        state=state,
        initialized=initialized,
        sensor_graphics=sensor_graphics,
    )
    parent.close()
    parent.deleteLater()
    application.processEvents()


def test_results_page_preserves_tabs_actions_and_unopened_canvases(results_page):
    page, callbacks = results_page.page, results_page.callbacks
    assert [page.result_tabs.tabText(i) for i in range(page.result_tabs.count())] == [
        "Overview",
        "Graphs",
        "Tables",
        "Sensor context",
    ]
    assert page.result_tabs.currentIndex() == 0
    assert not page.result_tabs.isTabVisible(page.sensor_tab_index)
    assert results_page.state.results_scroll is page._result_view_scrolls[0]
    assert not page.graph_view.initialized and not page._sensor_graph.initialized
    assert not results_page.initialized
    results_page.sensor_graphics.assert_not_called()
    assert not page.save_results_button.isEnabled() and not page.export_button.isEnabled()
    page.save_results_button.setEnabled(True)
    page.export_button.setEnabled(True)
    page.save_results_button.click()
    page.export_button.click()
    assert callbacks.save_results.call_count == callbacks.choose_export.call_count == 1
    page.result_tabs.setCurrentIndex(2)
    callbacks.results_tab_changed.assert_called_once_with(2)
    assert not page.graph_view.initialized and not page._sensor_graph.initialized


def test_results_page_initializes_graph_once_and_preserves_frozen_view_handles(results_page):
    page, callbacks = results_page.page, results_page.callbacks
    workspace, graph = page.workspace_view(), page.graph_view_model()
    assert not page.graph_view.initialized
    first = workspace.result_graphics()
    assert graph.result_graphics() is first
    assert page.result_graphics() is first
    assert first.figure is first.canvas.figure
    assert first.canvas.outer_scroll_area is page._result_view_scrolls[1]
    assert first.result_overlay.canvas is first.canvas
    assert page.graph_view.initialized and not page._sensor_graph.initialized
    assert not results_page.initialized
    results_page.sensor_graphics.assert_not_called()
    callbacks.selected_result_series.assert_called_once_with()
    callbacks.plot.assert_called_once_with()
    event = MouseEvent("button_press_event", first.canvas, 0, 0)
    first.canvas.callbacks.process("button_press_event", event)
    callbacks.graph_clicked.assert_called_once_with(event)
