"""A single Results plot scrollbar keeps the ruler, toolbar and selector fixed."""

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QScrollBar


def select_graphs(window):
    window._result_state.provenance = {
        "display_clock": {"origin": "2020-11-01T00:00:00Z", "timezone": None}
    }
    times = np.arange(0, 6 * 86400, 60.0)
    frame = pd.DataFrame(
        {"time": times, **{f"metric_{i}": 2 + i + np.sin(times / 10000) for i in range(18)}}
    )
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_series.blockSignals(True)
    for i, item in enumerate(window._result_state._series_items.values()):
        item.setCheckState(0, Qt.Checked if i < 8 else Qt.Unchecked)
    window.result_series.blockSignals(False)
    window.plot()
    window.navigate(2)
    window.result_tabs.setCurrentIndex(1)


@pytest.mark.parametrize("view", [0, 1, 2, 3], ids=["detailed", "30-minute", "day", "profile"])
@pytest.mark.parametrize("style,font_size", [("Fusion", 13), ("Windows", 18)])
def test_results_have_one_plot_scrollbar_at_compact_sizes_with_pinned_controls(
    window, view, style, font_size
):
    app = QApplication.instance()
    original_style = app.style().objectName()
    app.setStyle(style)
    window.setStyleSheet(window.styleSheet() + f"\nQWidget {{ font-size: {font_size}px; }}")
    try:
        select_graphs(window)
        window.result_graph_view.setCurrentIndex(view)
        for size in ((1450, 1050), (960, 650)):
            window.resize(*size)
            for settings in (False, True):
                window.plot_toolbar.settings_action.setChecked(settings)
                # Native footer hints can finish updating with the deferred
                # source paint. Complete that paint and its layout delivery
                # before recording geometry that scrolling must preserve.
                app.processEvents()
                window.canvas.draw()
                app.processEvents()
                assert window.recording_time_label.text() == window.figure.axes[0].get_xlabel()
                assert window.size().toTuple() == size
                assert window.graph_view.findChildren(QScrollArea) == [window.graph_scroll]
                assert window._result_state.results_scroll is window.graph_scroll
                assert window.graph_scroll.widget() is window.canvas
                bars = [
                    bar
                    for bar in window.graph_view.findChildren(QScrollBar)
                    if bar.orientation() == Qt.Vertical
                    and bar.isVisible()
                    and bar.mapTo(window, QPoint()).x() > window.width() / 2
                ]
                assert bars == [window.graph_scroll.verticalScrollBar()]
                controls = (
                    window.figure_actions,
                    window.result_series,
                    window.time_axis,
                    window.graph_footer,
                )
                baseline = [
                    (control.mapTo(window, QPoint()), control.size()) for control in controls
                ]
                bounds = [axis.get_xlim() for axis in window.figure.axes]
                for position in (bars[0].maximum(), 0):
                    bars[0].setValue(position)
                    app.processEvents()
                    assert [
                        (control.mapTo(window, QPoint()), control.size()) for control in controls
                    ] == baseline
                    assert [axis.get_xlim() for axis in window.figure.axes] == bounds
                for control in controls:
                    assert control.visibleRegion().boundingRect().contains(control.rect())
                bottom = window.graph_scroll.mapTo(
                    window, QPoint(0, window.graph_scroll.height())
                ).y()
                assert bottom <= window.time_axis.mapTo(window, QPoint()).y()
    finally:
        app.setStyle(original_style)


@pytest.mark.parametrize("trackpad", [False, True])
def test_graph_wheel_scrolls_the_only_plot_viewport_and_series_list_stays_independent(
    window, trackpad
):
    select_graphs(window)
    window.resize(960, 650)
    QTest.qWait(30)
    bar = window.graph_scroll.verticalScrollBar()
    tree = window.result_series.verticalScrollBar()
    assert tree.maximum() > 0
    tree.setValue(tree.maximum())
    assert bar.value() == 0
    event = QWheelEvent(
        QPointF(30, 30),
        QPointF(window.canvas.mapToGlobal(QPoint(30, 30))),
        QPoint(0, -37 if trackpad else 0),
        QPoint(0, 0 if trackpad else -120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(window.canvas, event)
    assert event.isAccepted() and bar.value() > 0
    assert tree.value() == tree.maximum()
    assert window.graph_view.findChildren(QScrollArea) == [window.graph_scroll]
