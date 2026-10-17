"""Two-level series navigation and a full-height selector beside the ruler."""

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paradigma_studio.app import MainWindow


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = MainWindow(tmp_path / "runs")
    widget.show()
    yield widget
    widget.close()
    app.processEvents()


def test_all_metrics_are_direct_module_children_with_distinguishable_output_context(window):
    frame = pd.DataFrame(
        {"time": [0.0, 1.0], "range_of_motion": [3.0, 5.0], "peak_velocity": [15.0, 25.0]}
    )
    window.analyzed(
        {
            "classifications": {
                "tremor": pd.DataFrame({"time": [0.0, 1.0], "metric": [1.0, 0.0]}),
                "gait": {
                    "detection": pd.DataFrame({"time": [0.0, 1.0], "pred_gait_proba": [0.1, 0.9]}),
                    "arm_activity": pd.DataFrame(
                        {"time": [0.0, 1.0], "pred_no_other_arm_activity_proba": [0.2, 0.8]}
                    ),
                },
            },
            "quantifications": {
                "gait": {"unfiltered": frame, "filtered": frame.copy()},
                "tremor": pd.DataFrame({"time": [0.0, 1.0], "metric": [2.0, 3.0]}),
            },
            "metadata": {"desktop_availability": {"gait": {"df_1": {"intervals": [[0.0, 2.0]]}}}},
        }
    )
    tree = window.result_series
    assert {tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())} == {
        "Gait",
        "Tremor",
        "Data coverage",
    }
    assert window._series_items["preparation/gait", "available"].text(0) == "Gait"
    leaves = []
    for i in range(tree.topLevelItemCount()):
        module = tree.topLevelItem(i)
        assert module.childCount()
        assert not module.flags() & Qt.ItemIsUserCheckable
        assert module.data(0, Qt.CheckStateRole) is None
        for j in range(module.childCount()):
            item = module.child(j)
            assert item.childCount() == 0
            assert item.flags() & Qt.ItemIsUserCheckable
            assert item.data(0, Qt.UserRole) in window._series_items
            leaves.append(item)
    assert len(leaves) == len(window._series_items)
    assert {item.text(0) for item in leaves if item.parent().text(0) == "Gait"} == {
        "Gait presence (probability)",
        "Gait presence (prediction)",
        "Filtered gait presence (probability)",
        "Filtered gait presence (prediction)",
        "Range of motion (filtered gait)",
        "Range of motion (unfiltered gait)",
        "Peak velocity (filtered gait)",
        "Peak velocity (unfiltered gait)",
    }
    for item in leaves:
        if item.parent().text(0) == "Gait" and item.text(0).endswith("(prediction)"):
            assert "bundled model threshold" in item.toolTip(0)
            assert item.text(0) not in item.toolTip(0)
        elif item.parent().text(0) == "Data coverage":
            assert "prepared samples" in item.toolTip(0)
        else:
            assert not item.toolTip(0)
    assert len({item.text(0) for item in leaves if item.parent().text(0) == "Tremor"}) == 2


def test_module_title_and_arrow_toggle_once_while_leaf_clicks_only_change_selection(window):
    window.analyzed(
        {
            "classifications": {
                "tremor": pd.DataFrame(
                    {
                        "time": [0.0, 1.0],
                        "pred_tremor_checked": [0, 1],
                        "pred_arm_at_rest": [1, 1],
                        "pred_tremor_proba": [0.2, 0.8],
                        "pred_tremor_logreg": [0, 1],
                    }
                )
            },
            "quantifications": {
                "tremor": pd.DataFrame({"time": [0.0, 1.0], "tremor_power": [1.0, 3.0]})
            },
        }
    )
    window.result_tabs.setCurrentIndex(1)
    QTest.qWait(30)
    tree = window.result_series
    root = tree.topLevelItem(0)
    assert tree.indentation() == 6
    assert {root.child(i).text(0) for i in range(root.childCount())} == {
        "Tremor presence (prediction)",
        "Arm at rest (prediction)",
        "Tremor power",
    }
    assert "pred_tremor_proba" in window._result_state.tables["classifications/tremor"]
    assert "pred_tremor_logreg" in window._result_state.tables["classifications/tremor"]
    for expanded in (False, True, False):
        root.setExpanded(expanded)
        rect = tree.visualItemRect(root)
        QTest.mouseClick(
            tree.viewport(), Qt.LeftButton, pos=QPoint(rect.left() + 30, rect.center().y())
        )
        assert root.isExpanded() != expanded
        QTest.mouseClick(
            tree.viewport(),
            Qt.LeftButton,
            pos=QPoint(rect.left() - tree.indentation() // 2, rect.center().y()),
        )
        assert root.isExpanded() == expanded
        assert root.data(0, Qt.CheckStateRole) is None
    root.setExpanded(True)
    leaf = root.child(0)
    before = leaf.checkState(0)
    rect = tree.visualItemRect(leaf)
    QTest.mouseClick(
        tree.viewport(), Qt.LeftButton, pos=QPoint(rect.left() + 10, rect.center().y())
    )
    assert leaf.checkState(0) != before
    assert root.isExpanded()
    before = leaf.checkState(0)
    QTest.mouseClick(
        tree.viewport(), Qt.LeftButton, pos=QPoint(rect.left() + 55, rect.center().y())
    )
    assert leaf.checkState(0) != before
    assert root.isExpanded()
    for ax in window.figure.axes:
        assert ax.get_title(loc="left") == window._series_items[
            ax._paradigma_dataset, ax._paradigma_metric
        ].text(0)


@pytest.mark.parametrize("view", [0, 1, 2, 3], ids=["detailed", "30-minute", "day", "profile"])
def test_selected_graphs_follow_module_groups_in_all_views_and_long_labels_wrap(window, view):
    frame = pd.DataFrame(
        {"time": [0.0, 1.0], "range_of_motion": [10.0, 20.0], "peak_velocity": [30.0, 40.0]}
    )
    window.analyzed(
        {
            "classifications": {
                "tremor": pd.DataFrame({"time": [0.0, 1.0], "pred_tremor_checked": [0, 1]}),
                "gait": {
                    "detection": pd.DataFrame({"time": [0.0, 1.0], "pred_gait_proba": [0.1, 0.99]}),
                    "arm_activity": pd.DataFrame(
                        {"time": [0.0, 0.75], "pred_no_other_arm_activity_proba": [0.2, 0.99]}
                    ),
                },
            },
            "quantifications": {
                "gait": {"unfiltered": frame},
                "tremor": pd.DataFrame({"time": [0.0, 1.0], "tremor_power": [1.0, 2.0]}),
                "pulse_rate": pd.DataFrame({"time": [0.0, 1.0], "pulse_rate": [60.0, 70.0]}),
            },
        }
    )
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    for width in (960, 1200):
        window.resize(width, 800)
        QTest.qWait(30)
        for metric, suffix in [
            ("pred_no_other_arm_activity_proba", "probability"),
            ("pred_no_other_arm_activity_window", "prediction"),
        ]:
            item = window._series_items["classifications/gait/arm_activity", metric]
            assert item.text(0) == f"Filtered gait presence ({suffix})"
            assert (
                window.result_series.visualItemRect(item).height()
                >= window.result_series.fontMetrics().height() + 10
            )
        window.result_graph_view.setCurrentIndex(view)
        window.plot()
        modules = [ax._paradigma_module for ax in window.figure.axes]
        assert modules == sorted(modules, key=["gait", "tremor", "pulse_rate"].index)
        assert [
            (ax._paradigma_dataset, ax._paradigma_metric) for ax in window.figure.axes
        ] == window.selected_result_series()
        assert window.recording_time_label.text() == window.figure.axes[0].get_xlabel()


@pytest.mark.parametrize("dated", [False, True])
def test_selector_uses_full_height_and_time_axis_stays_close_aligned_and_readable(window, dated):
    window.provenance = (
        {"display_clock": {"origin": "2026-10-07T12:00:00Z", "timezone": "UTC"}} if dated else {}
    )
    window.analyzed(
        {
            "quantifications": {
                "tremor": pd.DataFrame({"time": np.arange(6.0), "power": np.arange(6.0)})
            }
        }
    )
    window.result_tabs.setCurrentIndex(1)
    for width in (960, 1200, 1450):
        window.resize(width, 800)
        QTest.qWait(30)
        window.canvas.draw()
        window.result_table.setCurrentIndex(window.result_table.model().index(1, 0))
        window.time_axis.draw()
        selected_bounds = window.time_axis.selection_label.get_window_extent(
            window.time_axis.get_renderer()
        )
        assert selected_bounds.y0 > window.time_axis.axes.bbox.y0
        assert selected_bounds.y1 <= window.time_axis.figure.bbox.y1
        tree_bottom = window.result_series.mapTo(
            window, QPoint(0, window.result_series.height())
        ).y()
        ruler_bottom = window.time_axis.mapTo(window, QPoint(0, window.time_axis.height())).y()
        footer_bottom = window.graph_footer.mapTo(
            window, QPoint(0, window.graph_footer.height())
        ).y()
        assert abs(tree_bottom - footer_bottom) <= 1
        footer_top = window.graph_footer.mapTo(window, QPoint(0, 0)).y()
        scroll_top = window.result_time_scroll.mapTo(window, QPoint(0, 0)).y()
        scroll_bottom = window.result_time_scroll.mapTo(
            window, QPoint(0, window.result_time_scroll.height())
        ).y()
        if window.result_time_scroll.isVisible():
            assert scroll_top == ruler_bottom and scroll_bottom == footer_top
            assert window.result_time_scroll.visibleRegion().contains(
                window.result_time_scroll.rect()
            )
        else:
            assert footer_top == ruler_bottom
        page_bottom = window.graph_view.mapTo(window, QPoint(0, window.graph_view.height())).y()
        controls_bottom = window.context_controls.mapTo(
            window, QPoint(0, window.context_controls.height())
        ).y()
        assert page_bottom - controls_bottom == 12
        assert page_bottom - tree_bottom == 12
        label_center = window.recording_time_label.mapTo(
            window, window.recording_time_label.rect().center()
        ).y()
        controls_center = window.context_controls.mapTo(
            window, window.context_controls.rect().center()
        ).y()
        assert abs(label_center - controls_center) <= 1
        assert window.recording_time_label.text() == window.time_axis.axes.get_xlabel()
        assert window.recording_time_label.visibleRegion().contains(
            window.recording_time_label.rect()
        )
        plot_bottom = window.graph_scroll.mapTo(window, QPoint(0, window.graph_scroll.height())).y()
        ruler_top = window.time_axis.mapTo(window, QPoint(0, 0)).y()
        assert 0 <= ruler_top - plot_bottom <= 8
        axis_y = (
            ruler_top + (1 - window.time_axis.axes.get_position().y0) * window.time_axis.height()
        )
        assert axis_y - plot_bottom <= 24
        assert window.result_series.visibleRegion().contains(window.result_series.rect())
        for action in (
            window.plot_toolbar._actions["save_figure"],
            window.plot_toolbar.settings_action,
        ):
            control = window.plot_toolbar.widgetForAction(action)
            assert control.isVisible() and control.visibleRegion().contains(control.rect())
        renderer = window.time_axis.get_renderer()
        for artist in [*window.time_axis.axes.get_xticklabels(), window.time_axis.axes.xaxis.label]:
            if artist.get_visible() and artist.get_text():
                assert artist.get_window_extent(renderer).y0 >= 0


def test_large_native_toolbar_wraps_context_without_hiding_actions_or_expanding_window(window):
    window.analyzed(
        {"quantifications": {"tremor": pd.DataFrame({"time": [0.0, 1.0], "power": [1.0, 2.0]})}}
    )
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
        assert window.graph_view_controls.visibleRegion().contains(
            window.graph_view_controls.rect()
        )
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


@pytest.mark.parametrize("empty_filtered", [False, True])
def test_requested_defaults_select_predictions_and_filtered_rom_without_extra_metrics(
    window, empty_filtered
):
    gait = pd.DataFrame(
        {"time": [0.0, 1.0], "range_of_motion": [10.0, 20.0], "peak_velocity": [30.0, 40.0]}
    )
    filtered = gait.iloc[:0].copy() if empty_filtered else gait.copy()
    outputs = {
        "classifications": {
            "gait": {
                "detection": pd.DataFrame({"time": [0.0, 1.0], "pred_gait_proba": [0.1, 0.9]})
            },
            "tremor": pd.DataFrame(
                {"time": [0.0, 1.0], "pred_tremor_checked": [0, 1], "pred_arm_at_rest": [1, 1]}
            ),
        },
        "quantifications": {
            "gait": {"filtered": filtered, "unfiltered": gait},
            "tremor": pd.DataFrame({"time": [0.0, 1.0], "tremor_power": [2.0, 3.0]}),
            "pulse_rate": pd.DataFrame({"time": [0.0, 1.0], "pulse_rate": [60.0, 70.0]}),
        },
        "metadata": {"desktop_availability": {"gait": {"df_1": {"intervals": [[0.0, 2.0]]}}}},
    }
    window.analyzed(outputs)
    wanted = {
        ("classifications/gait/detection", "pred_gait_window"),
        ("quantifications/gait/filtered", "range_of_motion"),
        ("classifications/tremor", "pred_tremor_checked"),
        ("quantifications/pulse_rate", "pulse_rate"),
        ("preparation/gait", "available"),
    }
    assert set(window.selected_result_series()) == wanted
    assert {(ax._paradigma_dataset, ax._paradigma_metric) for ax in window.figure.axes} == wanted
    pd.testing.assert_frame_equal(
        window._result_state.tables["quantifications/gait/filtered"], filtered
    )
    pd.testing.assert_frame_equal(
        window._result_state.tables["quantifications/gait/unfiltered"], gait
    )
    window.result_tabs.setCurrentIndex(1)
    QApplication.instance().processEvents()
    for item in window._series_items.values():
        assert window.result_series.visualItemRect(item).left() <= 12
