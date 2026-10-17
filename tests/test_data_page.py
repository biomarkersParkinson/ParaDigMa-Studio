"""Data page construction, actions and resizing without an application window."""

from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QSplitter

from paradigma_studio.ui.layout import WorkspaceCallbacks, WorkspaceLayout
from paradigma_studio.workspace_state import GraphState, ResultState, ShellState


@pytest.fixture
def data_workspace(tmp_path):
    application = QApplication.instance() or QApplication([])
    parent = QMainWindow()
    callbacks = WorkspaceCallbacks(**{field.name: Mock() for field in fields(WorkspaceCallbacks)})
    layout = WorkspaceLayout(
        parent,
        callbacks,
        GraphState(),
        ShellState(),
        ResultState(),
        tmp_path,
        ("Data", "Analyze", "Results", "Runs"),
        {"Gait": "gait", "Tremor": "tremor", "Pulse rate": "pulse_rate"},
    )
    yield SimpleNamespace(parent=parent, layout=layout, callbacks=callbacks)
    parent.close()
    parent.deleteLater()
    application.processEvents()


def test_data_page_keeps_tab_order_actions_and_deferred_graphs(data_workspace):
    workspace = data_workspace
    layout, callbacks = workspace.layout, workspace.callbacks
    assert [layout.data_tabs.tabText(i) for i in range(layout.data_tabs.count())] == [
        "Overview",
        "Graphs",
        "Tables",
    ]
    assert layout.file_label.text() == "No recording loaded"
    assert [value.text() for value in layout.data_values] == ["—", "—", "—"]
    assert not layout.continue_button.isEnabled()
    assert layout.status_layout.itemAt(0).widget() is layout.status
    assert layout.status_layout.itemAt(1).widget() is layout.continue_button
    assert workspace.parent.actions() == [layout.open_action]
    assert layout.open_action.shortcut().toString() == "Ctrl+O"
    assert layout.open_action.parent() is workspace.parent
    assert not layout._data_graph.initialized
    assert not layout._sensor_graph.initialized
    assert not layout.graph_view.initialized

    layout.open_button.click()
    layout.open_action.trigger()
    assert callbacks.open_file.call_count == 2
    layout.input_recording.addItems(["first", "second"])
    callbacks.inspect_input_recording.reset_mock()
    layout.input_recording.setCurrentIndex(1)
    callbacks.inspect_input_recording.assert_called_once_with(1)
    layout.continue_button.setEnabled(True)
    layout.continue_button.click()
    callbacks.navigate.assert_called_once_with(1)
    assert not layout._data_graph.initialized


def test_data_splitter_changes_only_when_crossing_the_layout_threshold(data_workspace, monkeypatch):
    layout = data_workspace.layout
    changes = []
    set_orientation, set_sizes = QSplitter.setOrientation, QSplitter.setSizes

    def orientation(splitter, value):
        assert splitter is layout.data_details
        changes.append(("orientation", value))
        set_orientation(splitter, value)

    def sizes(splitter, value):
        assert splitter is layout.data_details
        changes.append(("sizes", value))
        set_sizes(splitter, value)

    monkeypatch.setattr(QSplitter, "setOrientation", orientation)
    monkeypatch.setattr(QSplitter, "setSizes", sizes)
    for width in (1450, 1280, 1279, 960, 1450, 1280, 960):
        layout.resize_data(width)
    assert changes == [
        ("orientation", Qt.Vertical),
        ("sizes", [220, 300]),
        ("orientation", Qt.Horizontal),
        ("sizes", [660, 400]),
        ("orientation", Qt.Vertical),
        ("sizes", [220, 300]),
    ]
    assert not layout._data_graph.initialized
