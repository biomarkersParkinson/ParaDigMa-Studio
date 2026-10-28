"""Time scrolling keeps exact visible pixels, stable layouts and complete exports."""

from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
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


def start_scroll(window, *, hand=False):
    axes = window.figure.axes[0]
    low, high = axes.get_xlim()
    axes.set_xlim(low, low + (high - low) / 2)
    window.canvas.draw()
    if hand:
        window.plot_toolbar.pan()
        window.plot_toolbar.press_pan(
            MouseEvent(
                "button_press_event", window.canvas, *axes.transAxes.transform((0.5, 0.5)), button=1
            )
        )
    else:
        window.result_time_scroll.setSliderDown(True)
    assert window.plot_toolbar.scrolling_time and window.canvas.panning


@pytest.mark.parametrize("pixel_ratio", [1, 2])
@pytest.mark.parametrize("scroll", [0, 450])
@pytest.mark.parametrize("hand", [False, True], ids=["scrollbar", "hand"])
def test_time_drag_skips_layout_and_offscreen_axes_but_preserves_visible_pixels_and_values(
    multi_graph_window, monkeypatch, pixel_ratio, scroll, hand
):
    window = multi_graph_window
    figure, canvas = window.figure, window.canvas
    window.graph_scroll.verticalScrollBar().setValue(scroll)
    canvas._set_device_pixel_ratio(pixel_ratio)
    figure.axes[1].set_ylim(0.5, 4.0)
    automatic = [ax.get_autoscaley_on() for ax in figure.axes]
    start_scroll(window, hand=hand)
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
    if hand:
        x, y = figure.axes[0].transAxes.transform((0.3, 0.5))
        window.plot_toolbar.drag_pan(MouseEvent("motion_notify_event", canvas, x, y, buttons={1}))
    else:
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
    FigureCanvasQTAgg.draw(canvas)
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
    if hand:
        window.plot_toolbar.release_pan(None)
    else:
        window.result_time_scroll.setSliderDown(False)
    QApplication.instance().processEvents()
    assert not canvas.panning and figure in executions
    assert 0 < len(set(drawn)) < len(figure.axes)
    # Release retains normal layout and the same display-resolution density. It no longer
    # rasterizes offscreen axes; compare every visible pixel to a full render.
    released = np.asarray(canvas.buffer_rgba()).copy()
    figure.set_layout_engine("none")
    FigureCanvasQTAgg.draw(canvas)
    figure.set_layout_engine(engine)
    np.testing.assert_array_equal(
        released[top:bottom, left:right], np.asarray(canvas.buffer_rgba())[top:bottom, left:right]
    )
    assert [ax.get_autoscaley_on() for ax in figure.axes] == automatic
    assert figure.axes[1].get_ylim() == (0.5, 4.0)
    np.testing.assert_allclose(window.time_axis.axes.get_xlim(), figure.axes[0].get_xlim())


@pytest.mark.parametrize("pixel_ratio", [1, 2])
def test_settled_results_paint_only_visible_graphs_and_refresh_after_vertical_scroll(
    multi_graph_window, monkeypatch, pixel_ratio
):
    window = multi_graph_window
    canvas, figure = window.canvas, window.figure
    canvas._set_device_pixel_ratio(pixel_ratio)
    app = QApplication.instance()
    app.processEvents()
    drawn = []
    for ax in figure.axes:
        original = ax.draw
        monkeypatch.setattr(
            ax,
            "draw",
            lambda renderer, original=original, ax=ax: (drawn.append(ax), original(renderer))[1],
        )
    bar = window.graph_scroll.verticalScrollBar()
    for index, scroll in enumerate((0, 450, bar.maximum(), 0)):
        painted = canvas._painted_axes.copy()
        drawn.clear()
        window.result_table.setCurrentIndex(window.result_table.model().index((index + 1) * 100, 0))
        bar.setValue(scroll)
        app.processEvents()
        if index == 0:
            canvas.draw()
        else:
            assert not set(drawn).intersection(painted), "Unchanged rows retain their pixels"
        assert len(set(drawn)) < len(figure.axes)
        if index in (0, 1):
            assert drawn, "Newly exposed graphs must actually be rendered"
        actual = np.asarray(canvas.buffer_rgba()).copy()
        # Restore the partial image/cache after the reference, so a complete
        # reference render cannot hide a missing viewport refresh on the next scroll.
        partial_image = canvas.copy_from_bbox(figure.bbox)
        background = window.result_overlay.background
        engine = figure.get_layout_engine()
        figure.set_layout_engine("none")
        try:
            FigureCanvasQTAgg.draw(canvas)
            reference = np.asarray(canvas.buffer_rgba()).copy()
        finally:
            figure.set_layout_engine(engine)
            figure.stale = False
            canvas.restore_region(partial_image)
            window.result_overlay.background = background
        region = canvas.visibleRegion().boundingRect()
        ratio = canvas.device_pixel_ratio
        left, right = round(region.x() * ratio), round((region.x() + region.width()) * ratio)
        top, bottom = round(region.y() * ratio), round((region.y() + region.height()) * ratio)
        np.testing.assert_array_equal(
            actual[top:bottom, left:right], reference[top:bottom, left:right]
        )
    # A normal export after viewport drawing must include the hidden rows too.
    drawn.clear()
    image = BytesIO()
    figure.savefig(image, format="png")
    assert image.getvalue().startswith(b"\x89PNG")
    assert set(drawn) == set(figure.axes)


@pytest.mark.parametrize("scrolling", [False, True])
def test_export_includes_every_axes_and_render_errors_restore_state(
    multi_graph_window, monkeypatch, scrolling
):
    window = multi_graph_window
    canvas, figure = window.canvas, window.figure
    if scrolling:
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
    assert canvas.panning == scrolling and figure.get_layout_engine() is engine
    with monkeypatch.context() as patch:

        def fail(self):
            raise RuntimeError("renderer failure")

        patch.setattr(FigureCanvasQTAgg, "draw", fail)
        with pytest.raises(RuntimeError, match="renderer failure"):
            canvas.draw()
    assert figure.get_layout_engine() is engine and all(ax.get_visible() for ax in figure.axes)
    canvas.draw()
    window.result_time_scroll.setSliderDown(False)


def test_incremental_viewport_failure_invalidates_pixels_and_preserves_traceback(
    multi_graph_window, monkeypatch
):
    window = multi_graph_window
    canvas = window.canvas
    canvas.draw()
    missing = next(ax for ax in window.figure.axes if ax not in canvas._painted_axes)
    assert window.result_overlay.background is not None
    with monkeypatch.context() as patch:
        patch.setattr(canvas, "_viewport_bounds", lambda: (missing.bbox.y0, missing.bbox.y1))

        def fail(renderer):
            raise RuntimeError("newly exposed graph failed")

        patch.setattr(missing, "draw", fail)
        with pytest.raises(RuntimeError, match="newly exposed graph failed") as error:
            canvas._extend_viewport()
        assert error.traceback[-1].name == "fail"
    assert canvas._viewport_renderer is None and window.result_overlay.background is None
    canvas.draw()
    assert canvas._viewport_renderer is canvas.get_renderer()
    assert window.result_overlay.background is not None


@pytest.mark.parametrize("change", ["limits", "style", "budget"])
def test_viewport_reuse_falls_back_after_changes_or_without_a_static_image(
    multi_graph_window, monkeypatch, change
):
    window = multi_graph_window
    canvas = window.canvas
    canvas.draw()
    if change == "limits":
        window.figure.axes[0].set_xlim(*window.figure.axes[0].get_xlim()[::-1])
    elif change == "style":
        window.figure.axes[0].set_ylabel("Changed label")
    else:
        window.result_overlay.invalidate()
    draws = []
    original = FigureCanvasQTAgg.draw
    monkeypatch.setattr(
        FigureCanvasQTAgg, "draw", lambda self: (draws.append(self), original(self))[1]
    )
    canvas.redraw_viewport()
    QApplication.instance().processEvents()
    assert canvas in draws
    assert window.figure.axes[0] in canvas._painted_axes
    assert canvas._viewport_renderer is canvas.get_renderer()
    assert window.result_overlay.background is not None


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
def test_dense_horizontal_navigation_keeps_display_density_and_exports_original_bars(
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
        # Keep this manually ended gesture active while rendering its images.
        bar._wheel_timer.stop()
    QApplication.instance().processEvents()
    assert canvas.time_scrolling and counts and max(counts) <= np.ceil(axes.bbox.width)
    assert len(collection.get_paths()) == len(frame)
    counts.clear()
    bar.finish_gesture()
    QApplication.instance().processEvents()
    assert not canvas.time_scrolling and counts and max(counts) <= np.ceil(axes.bbox.width)
    assert not canvas._scroll_y_ticks
    assert len(collection.get_paths()) == len(frame)
    counts.clear()
    destination = BytesIO()
    window.figure.savefig(destination, format="png")
    assert destination.getvalue().startswith(b"\x89PNG")
    low, high = sorted(axes.get_xlim())
    visible = sum(
        path.vertices[:, 0].max() >= low and path.vertices[:, 0].min() <= high
        for path in collection.get_paths()
    )
    assert counts and max(counts) == visible > axes.bbox.width * 2
    pd.testing.assert_frame_equal(
        window._result_state.tables["quantifications/pulse_rate"], original
    )


def dense_gait_plot(window, metric, pixel_ratio):
    samples = np.arange(20000.0)
    values = 30 + 15 * np.sin(samples / 30)
    values[2000:3000] = np.nan
    frame = pd.DataFrame({"gait_segment_nr": np.repeat([1, 2], 10000), metric: values})
    metadata = {
        1: {"start_s": 0.0, "end_s": 36000.0, "duration_s": 36000.0},
        2: {"start_s": 48000.0, "end_s": 120000.0, "duration_s": 72000.0},
    }
    window.analyzed(
        {
            "quantifications": {"gait": {"unfiltered": frame}},
            "metadata": {"gait": {"unfiltered": {"per_segment": metadata}}},
        }
    )
    window.result_tabs.setCurrentIndex(1)
    window.canvas._set_device_pixel_ratio(pixel_ratio)
    window.plot_toolbar._actions["zoom_in"].trigger()
    QApplication.instance().processEvents()
    axes = window.figure.axes[0]
    axes.set_ylim(0, 50)
    window.canvas.draw()
    return frame, axes


@pytest.mark.parametrize("metric", ["range_of_motion", "peak_velocity"])
@pytest.mark.parametrize("pixel_ratio", [1, 2])
@pytest.mark.parametrize("control", ["scrollbar", "trackpad"])
def test_detailed_gait_density_is_identical_during_and_after_horizontal_scrolling(
    window, metric, pixel_ratio, control
):
    frame, axes = dense_gait_plot(window, metric, pixel_ratio)
    original = frame.copy(deep=True)
    collection = next(item for item in axes.collections if isinstance(item, ViewportPolyCollection))
    paths = collection.get_paths()
    vertices = np.array([path.vertices.copy() for path in paths])
    canvas, bar = window.canvas, window.result_time_scroll
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
        # This pixel comparison ends the gesture explicitly below. Prevent
        # the inactivity timer racing its captures on instrumented runners.
        bar._wheel_timer.stop()
    QApplication.instance().processEvents()
    assert canvas.time_scrolling
    limits = axes.get_xlim()
    moving = np.asarray(canvas.buffer_rgba()).copy()
    bar.finish_gesture()
    QApplication.instance().processEvents()
    assert not canvas.time_scrolling and axes.get_xlim() == limits
    stopped = np.asarray(canvas.buffer_rgba()).copy()
    height = moving.shape[0]
    left, right = int(np.ceil(axes.bbox.x0)) + 1, int(np.floor(axes.bbox.x1)) - 1
    top, bottom = height - int(np.floor(axes.bbox.y1)) + 1, height - int(np.ceil(axes.bbox.y0)) - 1
    np.testing.assert_array_equal(moving[top:bottom, left:right], stopped[top:bottom, left:right])
    assert collection.get_paths() is paths
    np.testing.assert_array_equal([path.vertices for path in paths], vertices)
    pd.testing.assert_frame_equal(
        window._result_state.tables["quantifications/gait/unfiltered"], original
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
