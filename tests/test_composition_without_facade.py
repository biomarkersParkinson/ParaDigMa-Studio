"""Exercise the production composition root without installing legacy window ports."""

import ast
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication

from paradigma_studio import app as desktop
from paradigma_studio.ui import compatibility


def test_recording_results_and_sensor_context_work_without_window_aliases(
    tmp_path, monkeypatch, tremor_outputs
):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(compatibility, "workspace_ports", lambda cls: cls)
    name = "paradigma_studio._facade_free_app"
    spec = importlib.util.spec_from_file_location(name, desktop.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    window = module.MainWindow(history_dir=tmp_path)
    times = np.arange(1200) / 100
    raw = pd.DataFrame({"time": times, "gyroscope_x": np.sin(times)})
    original = raw.copy(deep=True)
    try:
        assert "_sensor_controller" not in window.__dict__
        assert not any(
            graph.initialized
            for graph in (
                window._layout._data_graph,
                window._layout.graph_view,
                window._layout._sensor_graph,
            )
        )
        window._data_controller.loaded(("sensor.csv", raw))
        window._result_state.provenance = {
            "source": "sensor.csv",
            "settings": {"skip_preparation": True},
        }
        window._result_controller.analyzed(tremor_outputs)
        assert window._result_state.results is tremor_outputs
        pd.testing.assert_frame_equal(
            window._result_state.tables["quantifications/tremor"],
            tremor_outputs["quantifications"]["tremor"],
            check_exact=True,
        )
        window._layout.result_tabs.setCurrentIndex(1)
        application.processEvents()
        assert window._layout.graph_view.initialized
        assert window._workspace_controller.selected_result_series() == [
            ("classifications/tremor", "pred_tremor_checked")
        ]
        table = window._layout.result_table
        table.setCurrentIndex(table.model().index(1, 0))
        window._sensor_controller.inspect_sensor_context()
        assert window._layout.result_tabs.currentIndex() == window._layout.sensor_tab_index
        assert window._layout._sensor_graph.initialized
        pd.testing.assert_frame_equal(window._sensor_state.sensor_frame, original, check_exact=True)
        pd.testing.assert_frame_equal(window._input_state.frame, original, check_exact=True)
    finally:
        window.close()
        window.deleteLater()
        application.processEvents()


def test_main_window_composition_uses_explicit_owners():
    tree = ast.parse(Path(desktop.__file__).read_text(encoding="utf-8"))
    references = [
        f"{node.lineno}: self.{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr in compatibility._PORTS
    ]
    assert not references, "Composition uses legacy aliases:\n" + "\n".join(references)
