"""Time scrolling keeps exact visible pixels, stable layouts and complete exports."""

from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.layout_engine import ConstrainedLayoutEngine
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from paradigma_studio.app import MainWindow
from paradigma_studio.plotting import ViewportPolyCollection
from paradigma_studio.time_axis import RecordingDateLocator


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.resize(1200, 750)
    window.show()
    window._result_state.provenance = {
        "display_clock": {"origin": "2026-10-10T00:00:00+02:00", "timezone": "Europe/Amsterdam"}
    }
    yield window
    window.close()
    app.processEvents()


@pytest.fixture
def multi_graph_window(window):
    times = np.arange(2000) * 4.0
    frame = pd.DataFrame(
        {"time": times, **{f"metric_{i}": 2 + np.sin(times / (50 + i)) for i in range(8)}}
    )
    window.analyzed({"quantifications": {"tremor": frame}})
    window.navigate(2)
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.plot()
    QApplication.instance().processEvents()
    if window.figure.stale:
        window.canvas.draw()
    return window


def start_scroll(window):
    axes = window.figure.axes[0]
    low, high = axes.get_xlim()
    axes.set_xlim(low, low + (high - low) / 2)
    window.canvas.draw()
    window.result_time_scroll.setSliderDown(True)
    assert window.plot_toolbar.scrolling_time and window.canvas.panning


@pytest.mark.parametrize("pixel_ratio", [1, 2])
@pytest.mark.parametrize("scroll", [0, 450])
def test_scroll_skips_layout_and_offscreen_axes_but_preserves_visible_pixels_and_values(
    multi_graph_window, monkeypatch, pixel_ratio, scroll
):
    window = multi_graph_window
    figure, canvas = window.figure, window.canvas
    window.graph_scroll.verticalScrollBar().setValue(scroll)
    canvas._set_device_pixel_ratio(pixel_ratio)
    figure.axes[1].set_ylim(0.5, 4.0)
    automatic = [ax.get_autoscaley_on() for ax in figure.axes]
    start_scroll(window)
    engine = figure.get_layout_engine()
    paths = [[p.vertices.copy() for p in ax.collections[0].get_paths()] for ax in figure.axes]
    positions = [ax.get_position().bounds for ax in figure.axes]
    executions, drawn = [], []
    execute = ConstrainedLayoutEngine.execute
    monkeypatch.setattr(
        ConstrainedLayoutEngine,
        "execute",
        lambda self, fig: (executions.append(fig), execute(self, fig))[1],
    )
    for ax in figure.axes:
        original = ax.draw
        monkeypatch.setattr(
            ax,
            "draw",
            lambda renderer, original=original, ax=ax: (
                drawn.append(ax) if ax.get_visible() else None,
                original(renderer),
            )[1],
        )
    window.result_time_scroll.setValue(window.result_time_scroll.maximum() // 5)
    QApplication.instance().processEvents()
    assert figure not in executions
    assert 0 < len(set(drawn)) < len(figure.axes)
    assert figure.get_layout_engine() is engine and all(ax.get_visible() for ax in figure.axes)
    assert [ax.get_position().bounds for ax in figure.axes] == positions
    shifted = figure.axes[0].get_xlim()
    assert all(ax.get_xlim() == shifted for ax in figure.axes)
    actual = np.asarray(canvas.buffer_rgba()).copy()
    # The full reference uses the same settled layout and exactly the same limits.
    canvas.panning = False
    figure.set_layout_engine("none")
    canvas.draw()
    reference = np.asarray(canvas.buffer_rgba()).copy()
    figure.set_layout_engine(engine)
    canvas.panning = True
    region = canvas.visibleRegion().boundingRect()
    ratio = canvas.device_pixel_ratio
    left, right = round(region.left() * ratio), round((region.x() + region.width()) * ratio)
    top, bottom = round(region.top() * ratio), round((region.y() + region.height()) * ratio)
    np.testing.assert_array_equal(actual[top:bottom, left:right], reference[top:bottom, left:right])
    for ax, expected in zip(figure.axes, paths, strict=False):
        for path, values in zip(ax.collections[0].get_paths(), expected, strict=False):
            np.testing.assert_array_equal(path.vertices, values)
    drawn.clear()
    window.result_time_scroll.setSliderDown(False)
    QApplication.instance().processEvents()
    assert not canvas.panning and figure in executions
    assert set(drawn) == set(figure.axes)
    assert [ax.get_autoscaley_on() for ax in figure.axes] == automatic
    assert figure.axes[1].get_ylim() == (0.5, 4.0)
    np.testing.assert_allclose(window.time_axis.axes.get_xlim(), figure.axes[0].get_xlim())


def test_export_during_scroll_includes_every_axes_and_render_errors_restore_state(
    multi_graph_window, monkeypatch
):
    window = multi_graph_window
    canvas, figure = window.canvas, window.figure
    start_scroll(window)
    engine = figure.get_layout_engine()
    drawn = []
    for ax in figure.axes:
        original = ax.draw
        monkeypatch.setattr(
            ax,
            "draw",
            lambda renderer, original=original, ax=ax: (drawn.append(ax), original(renderer))[1],
        )
    image = BytesIO()
    figure.savefig(image, format="png")
    assert image.getvalue().startswith(b"\x89PNG")
    assert set(drawn) == set(figure.axes)
    assert canvas.panning and figure.get_layout_engine() is engine
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

    with monkeypatch.context() as patch:

        def fail(self):
            raise RuntimeError("renderer failure")

        patch.setattr(FigureCanvasQTAgg, "draw", fail)
        with pytest.raises(RuntimeError, match="renderer failure"):
            canvas.draw()
    assert figure.get_layout_engine() is engine and all(ax.get_visible() for ax in figure.axes)
    canvas.draw()
    window.result_time_scroll.setSliderDown(False)


@pytest.mark.parametrize("end", ["release", "refresh", "clear_results", "hide"])
def test_scroll_ends_cleanly_when_released_or_graphs_change(multi_graph_window, end):
    window = multi_graph_window
    start_scroll(window)
    if end == "release":
        window.result_time_scroll.setSliderDown(False)
    elif end == "refresh":
        window.plot_toolbar.refresh()
    elif end == "clear_results":
        window.clear_results()
    else:
        window.result_tabs.setCurrentIndex(0)
    QApplication.instance().processEvents()
    assert not window.plot_toolbar.scrolling_time and not window.canvas.panning
    if end in ("release", "clear_results", "hide"):
        assert not window.result_time_scroll.isSliderDown()


@pytest.mark.parametrize("pixel_ratio", [1, 2])
@pytest.mark.parametrize("scroll", [0, 450])
def test_interval_drag_never_redraws_graphs_even_without_an_overlay_background(
    multi_graph_window, monkeypatch, pixel_ratio, scroll
):
    window = multi_graph_window
    canvas, toolbar, figure = window.canvas, window.plot_toolbar, window.figure
    canvas.setFixedHeight(3200)
    canvas._set_device_pixel_ratio(pixel_ratio)
    window.graph_scroll.verticalScrollBar().setValue(scroll)
    QApplication.instance().processEvents()
    if figure.stale:
        canvas.draw()
    QApplication.instance().processEvents()
    if pixel_ratio == 2:
        assert figure.bbox.width * figure.bbox.height * 4 > 32 * 1024**2
        assert window.result_overlay.background is None
    limits = [(ax.get_xlim(), ax.get_ylim()) for ax in figure.axes]
    positions = [ax.bbox.bounds for ax in figure.axes]
    draws = []
    original_draw = canvas.draw

    def draw():
        draws.append(True)
        return original_draw()

    monkeypatch.setattr(canvas, "draw", draw)
    toolbar.zoom()
    start = figure.axes[0].transAxes.transform((0.2, 0.5))
    toolbar.press_zoom(MouseEvent("button_press_event", canvas, *start, button=1))
    for fraction in (0.3, 0.6, 0.4):
        end = figure.axes[0].transAxes.transform((fraction, 0.5))
        toolbar.drag_zoom(MouseEvent("motion_notify_event", canvas, *end, buttons={1}))
        QApplication.instance().processEvents()
        assert canvas.zoom_rectangle is not None and canvas.zoom_rectangle.width() > 0
        assert not draws, "Selecting time must repaint the cached image without graph redraws"
    assert [(ax.get_xlim(), ax.get_ylim()) for ax in figure.axes] == limits
    assert [ax.bbox.bounds for ax in figure.axes] == positions
    toolbar.stop_navigation()
    assert canvas.zoom_rectangle is None


@pytest.mark.parametrize("control", ["scrollbar", "trackpad"])
def test_dense_horizontal_navigation_bounds_render_work_and_restores_full_bars(
    window, monkeypatch, control
):
    from matplotlib.collections import PolyCollection

    times = np.arange(20000) * 4.0
    frame = pd.DataFrame({"time": times, "pulse_rate": 65 + 20 * np.sin(times / 100)})
    original = frame.copy(deep=True)
    window.analyzed({"quantifications": {"pulse_rate": frame}})
    window.result_tabs.setCurrentIndex(1)
    toolbar, canvas, bar = window.plot_toolbar, window.canvas, window.result_time_scroll
    toolbar._actions["zoom_in"].trigger()
    QApplication.instance().processEvents()
    if window.figure.stale:
        canvas.draw()
    axes = window.figure.axes[0]
    collection = next(item for item in axes.collections if isinstance(item, ViewportPolyCollection))
    counts = []
    native_draw = PolyCollection.draw

    def record(self, renderer):
        if self is collection:
            counts.append(len(self.get_paths()))
        return native_draw(self, renderer)

    monkeypatch.setattr(PolyCollection, "draw", record)
    if control == "scrollbar":
        bar.setSliderDown(True)
        bar.setValue(bar.maximum() // 3)
    else:
        event = QWheelEvent(
            QPointF(30, 30),
            QPointF(30, 30),
            QPoint(-120, 0),
            QPoint(),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(canvas, event)
        assert event.isAccepted()
    QApplication.instance().processEvents()
    assert canvas.time_scrolling and counts and max(counts) <= np.ceil(axes.bbox.width)
    assert len(collection.get_paths()) == len(frame)
    counts.clear()
    bar.finish_gesture()
    QApplication.instance().processEvents()
    assert not canvas.time_scrolling and counts and max(counts) > axes.bbox.width * 2
    assert not canvas._scroll_y_ticks
    pd.testing.assert_frame_equal(
        window._result_state.tables["quantifications/pulse_rate"], original
    )


@pytest.mark.parametrize("timezone", ["UTC", "Europe/Amsterdam"])
def test_cached_calendar_ticks_match_official_locator_across_zoom_and_dst(timezone, monkeypatch):
    figure = Figure()
    FigureCanvasAgg(figure)
    ax = figure.add_subplot()
    locator = RecordingDateLocator(tz=timezone)
    reference = dates.AutoDateLocator(tz=timezone)
    ax.xaxis.set_major_locator(locator)
    reference.set_axis(ax.xaxis)
    calls = []
    original = dates.AutoDateLocator.__call__
    monkeypatch.setattr(
        dates.AutoDateLocator, "__call__", lambda self: (calls.append(self), original(self))[1]
    )
    for start, end in (
        ("2026-10-24", "2026-10-27"),
        ("2026-10-25T00:00:00Z", "2026-10-25T03:00:00Z"),
        ("2026-10-25T01:01:01Z", "2026-10-25T01:01:02Z"),
        ("2026-01-01", "2027-01-01"),
    ):
        ax.set_xlim(dates.datestr2num(start), dates.datestr2num(end))
        expected = reference()
        for _ in range(5):
            np.testing.assert_array_equal(locator(), expected)
    assert calls.count(locator) == 4
