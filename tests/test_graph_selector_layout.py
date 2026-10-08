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


def test_module_title_and_arrow_toggle_once_while_leaf_clicks_only_change_selection(window):
    window.analyzed({'classifications': {'tremor': pd.DataFrame({'time': [0., 1.],
        'pred_tremor_checked': [0, 1], 'pred_arm_at_rest': [1, 1],
        'pred_tremor_proba': [.2, .8], 'pred_tremor_logreg': [0, 1]})},
        'quantifications': {'tremor': pd.DataFrame({'time': [0., 1.], 'tremor_power': [1., 3.]})}})
    window.result_tabs.setCurrentIndex(1)
    QTest.qWait(30)
    tree = window.result_series
    root = tree.topLevelItem(0)
    assert tree.indentation() == 12
    assert {root.child(i).text(0) for i in range(root.childCount())} == {
        'Tremor presence (prediction)', 'Arm at rest (prediction)', 'Tremor power'}
    assert 'pred_tremor_proba' in window.tables['classifications/tremor']
    assert 'pred_tremor_logreg' in window.tables['classifications/tremor']
    for expanded in (False, True, False):
        root.setExpanded(expanded)
        rect = tree.visualItemRect(root)
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=QPoint(rect.left() + 30, rect.center().y()))
        assert root.isExpanded() != expanded
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=QPoint(rect.left() - 6, rect.center().y()))
        assert root.isExpanded() == expanded
    root.setExpanded(True)
    leaf = root.child(0)
    before = leaf.checkState(0)
    rect = tree.visualItemRect(leaf)
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=QPoint(rect.left() + 10, rect.center().y()))
    assert leaf.checkState(0) != before
    assert root.isExpanded()
    for ax in window.figure.axes:
        assert ax.get_title(loc='left') == window._series_items[ax._paradigma_dataset, ax._paradigma_metric].text(0)


def test_selected_graphs_follow_module_groups_in_both_views_and_long_labels_wrap(window):
    frame = pd.DataFrame({'time': [0., 1.], 'range_of_motion': [10., 20.], 'peak_velocity': [30., 40.]})
    window.analyzed({'classifications': {
        'tremor': pd.DataFrame({'time': [0., 1.], 'pred_tremor_checked': [0, 1]}),
        'gait': {'detection': pd.DataFrame({'time': [0., 1.], 'pred_gait_proba': [.1, .99]}),
                 'arm_activity': pd.DataFrame({'time': [0., .75], 'pred_no_other_arm_activity_proba': [.2, .99]})}},
        'quantifications': {'gait': {'unfiltered': frame},
                            'tremor': pd.DataFrame({'time': [0., 1.], 'tremor_power': [1., 2.]}),
                            'pulse_rate': pd.DataFrame({'time': [0., 1.], 'pulse_rate': [60., 70.]})}})
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    for width in (960, 1200):
        window.resize(width, 800)
        QTest.qWait(30)
        for metric, suffix in [('pred_no_other_arm_activity_proba', 'probability'),
                               ('pred_no_other_arm_activity_window', 'prediction')]:
            item = window._series_items['classifications/gait/arm_activity', metric]
            assert item.text(0) == f'Filtered gait presence ({suffix})'
            assert window.result_series.visualItemRect(item).height() > window.result_series.fontMetrics().height() * 2
        for mode in (0, 1):
            window.result_graph_view.setCurrentIndex(mode)
            window.plot()
            modules = [ax._paradigma_module for ax in window.figure.axes]
            assert modules == sorted(modules, key=['gait', 'tremor', 'pulse_rate'].index)
            assert [(ax._paradigma_dataset, ax._paradigma_metric) for ax in window.figure.axes] == window.selected_result_series()
            assert window.recording_time_label.text() == window.figure.axes[0].get_xlabel()


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
        footer_bottom = window.graph_footer.mapTo(window, QPoint(0, window.graph_footer.height())).y()
        assert abs(tree_bottom - footer_bottom) <= 1
        footer_top = window.graph_footer.mapTo(window, QPoint(0, 0)).y()
        assert footer_top == ruler_bottom
        page_bottom = window.graph_view.mapTo(window, QPoint(0, window.graph_view.height())).y()
        controls_bottom = window.context_controls.mapTo(window, QPoint(0, window.context_controls.height())).y()
        assert page_bottom - controls_bottom == 12
        assert page_bottom - tree_bottom == 12
        label_center = window.recording_time_label.mapTo(window, window.recording_time_label.rect().center()).y()
        controls_center = window.context_controls.mapTo(window, window.context_controls.rect().center()).y()
        assert abs(label_center - controls_center) <= 1
        assert window.recording_time_label.text() == window.time_axis.axes.get_xlabel()
        assert window.recording_time_label.visibleRegion().contains(window.recording_time_label.rect())
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
        assert window.graph_view_controls.visibleRegion().contains(window.graph_view_controls.rect())
        assert window.context_controls.visibleRegion().contains(window.context_controls.rect())
        assert window.time_axis.visibleRegion().contains(window.time_axis.rect())
    # Inspect controls move to Tables; the graph View selector stays in its toolbar.
    window.result_tabs.setCurrentIndex(2)
    QTest.qWait(30)
    assert window.detail_controls.isAncestorOf(window.context_controls)
    window.result_tabs.setCurrentIndex(1)
    QTest.qWait(30)
    assert window.figure_actions.secondary.isVisible()
    assert window.context_controls.isVisible()
    assert window.graph_footer.isAncestorOf(window.context_controls)
    assert window.figure_actions.isAncestorOf(window.graph_view_controls)
