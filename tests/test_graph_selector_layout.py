"""Two-level series navigation and a full-height selector beside the ruler."""
import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paradigma_desktop.app import MainWindow


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = MainWindow(tmp_path / "runs")
    widget.show()
    yield widget
    widget.close()
    app.processEvents()


def test_all_metrics_are_direct_module_children_with_distinguishable_output_context(window):
    frame = pd.DataFrame({"time": [0., 1.], "range_of_motion": [3., 5.]})
    window.analyzed({"classifications": {"tremor": pd.DataFrame({"time": [0., 1.], "metric": [1., 0.]})},
                     "quantifications": {"gait": {"unfiltered": frame, "filtered": frame.copy()},
                                          "tremor": pd.DataFrame({"time": [0., 1.], "metric": [2., 3.]})},
                     "metadata": {"desktop_availability": {"gait": {"df_1": {"intervals": [[0., 2.]]}}}}})
    tree = window.result_series
    assert {tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())} == {"Gait", "Tremor", "Data preparation"}
    leaves = []
    for i in range(tree.topLevelItemCount()):
        module = tree.topLevelItem(i)
        assert module.childCount()
        for j in range(module.childCount()):
            item = module.child(j)
            assert item.childCount() == 0
            assert item.flags() & Qt.ItemIsUserCheckable
            assert item.data(0, Qt.UserRole) in window._series_items
            leaves.append(item)
    assert len(leaves) == len(window._series_items)
    assert len({item.text(0) for item in leaves if item.parent().text(0) == "Gait"}) == 2
    assert len({item.text(0) for item in leaves if item.parent().text(0) == "Tremor"}) == 2


@pytest.mark.parametrize("dated", [False, True])
def test_selector_uses_full_height_and_time_axis_stays_close_aligned_and_readable(window, dated):
    window.provenance = {"display_clock": {"origin": "2026-10-07T12:00:00Z", "timezone": "UTC"}} if dated else {}
    window.analyzed({"quantifications": {"tremor": pd.DataFrame({"time": np.arange(6.), "power": np.arange(6.)})}})
    window.result_tabs.setCurrentIndex(1)
    for width in (960, 1200, 1450):
        window.resize(width, 800)
        QTest.qWait(30)
        window.canvas.draw()
        window.time_axis.draw()
        tree_bottom = window.result_series.mapTo(window, QPoint(0, window.result_series.height())).y()
        ruler_bottom = window.time_axis.mapTo(window, QPoint(0, window.time_axis.height())).y()
        assert abs(tree_bottom - ruler_bottom) <= 1
        page_bottom = window.graph_view.mapTo(window, QPoint(0, window.graph_view.height())).y()
        assert page_bottom - tree_bottom == 12
        plot_bottom = window.graph_scroll.mapTo(window, QPoint(0, window.graph_scroll.height())).y()
        ruler_top = window.time_axis.mapTo(window, QPoint(0, 0)).y()
        assert 0 <= ruler_top - plot_bottom <= 8
        axis_y = ruler_top + (1 - window.time_axis.axes.get_position().y0) * window.time_axis.height()
        assert axis_y - plot_bottom <= 24
        assert window.result_series.visibleRegion().contains(window.result_series.rect())
        for action in (window.plot_toolbar._actions["save_figure"], window.plot_toolbar.settings_action):
            control = window.plot_toolbar.widgetForAction(action)
            assert control.isVisible() and control.visibleRegion().contains(control.rect())
        renderer = window.time_axis.get_renderer()
        for artist in [*window.time_axis.axes.get_xticklabels(), window.time_axis.axes.xaxis.label]:
            if artist.get_visible() and artist.get_text():
                assert artist.get_window_extent(renderer).y0 >= 0
