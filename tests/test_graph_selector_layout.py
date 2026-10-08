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
    frame = pd.DataFrame({"time": [0., 1.], "range_of_motion": [3., 5.], "peak_velocity": [15., 25.]})
    window.analyzed({"classifications": {"tremor": pd.DataFrame({"time": [0., 1.], "metric": [1., 0.]}),
                                          "gait": {"detection": pd.DataFrame({"time": [0., 1.], "pred_gait_proba": [.1, .9]}),
                                                   "arm_activity": pd.DataFrame({"time": [0., 1.], "pred_no_other_arm_activity_proba": [.2, .8]})}},
                     "quantifications": {"gait": {"unfiltered": frame, "filtered": frame.copy()},
                                          "tremor": pd.DataFrame({"time": [0., 1.], "metric": [2., 3.]})},
                     "metadata": {"desktop_availability": {"gait": {"df_1": {"intervals": [[0., 2.]]}}}}})
    tree = window.result_series
    assert {tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())} == {"Gait", "Tremor", "Data coverage"}
    assert window._series_items["preparation/gait", "available"].text(0) == "Gait"
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
    assert {item.text(0) for item in leaves if item.parent().text(0) == "Gait"} == {
        "Gait presence (probability)", "Gait presence (prediction)",
        "Filtered gait presence (probability)", "Filtered gait presence (prediction)",
        "Range of motion (filtered gait)", "Range of motion (unfiltered gait)",
        "Peak velocity (filtered gait)", "Peak velocity (unfiltered gait)"}
    for item in leaves:
        if item.parent().text(0) == "Gait" and item.text(0).endswith("(prediction)"):
            assert "bundled model threshold" in item.toolTip(0)
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


def test_large_native_toolbar_wraps_context_without_hiding_actions_or_expanding_window(window):
    window.analyzed({"quantifications": {"tremor": pd.DataFrame({"time": [0., 1.], "power": [1., 2.]})}})
    window.result_tabs.setCurrentIndex(1)
    toolbar = window.plot_toolbar
    # Reproduce native Windows hints exceeding the width left beside context.
    toolbar.widgetForAction(toolbar.settings_action).setMinimumWidth(260)
    toolbar.widgetForAction(toolbar._actions["save_figure"]).setMinimumWidth(100)
    for width in (960, 1450, 960):
        window.resize(width, 800)
        QTest.qWait(40)
        assert window.width() == width
        wrapped = width == 960
        for action in (toolbar._actions["save_figure"], toolbar.settings_action):
            control = toolbar.widgetForAction(action)
            assert control.isVisible() and control.visibleRegion().contains(control.rect())
        assert window.figure_actions.secondary.isVisible() == wrapped
        assert window.context_controls.visibleRegion().contains(window.context_controls.rect())
        assert window.time_axis.visibleRegion().contains(window.time_axis.rect())
    # Moving the shared controls to Tables must not leave an empty toolbar row.
    window.result_tabs.setCurrentIndex(2)
    QTest.qWait(30)
    assert window.detail_controls.isAncestorOf(window.context_controls)
    window.result_tabs.setCurrentIndex(1)
    QTest.qWait(30)
    assert window.figure_actions.secondary.isVisible()
    assert window.context_controls.isVisible()
