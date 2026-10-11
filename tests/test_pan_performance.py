"""Pan frames keep exact visible data, stable layout and complete final exports."""

from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.layout_engine import ConstrainedLayoutEngine
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_studio.app import MainWindow
from paradigma_studio.time_axis import RecordingDateLocator


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.resize(1200, 750)
    window.show()
    times = np.arange(2000) * 4.0
    frame = pd.DataFrame(
        {"time": times, **{f"metric_{i}": 2 + np.sin(times / (50 + i)) for i in range(8)}}
    )
    window.provenance = {
        "display_clock": {"origin": "2026-10-10T00:00:00+02:00", "timezone": "Europe/Amsterdam"}
    }
    window.analyzed({"quantifications": {"tremor": frame}})
    window.navigate(2)
    window.result_tabs.setCurrentIndex(1)
    window.result_series.blockSignals(True)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.plot()
    app.processEvents()
    window.canvas.draw()
    yield window
    window.close()
    app.processEvents()


def start_pan(window):
    toolbar, canvas = window.plot_toolbar, window.canvas
    toolbar.pan()
    point = canvas.figure.axes[0].transAxes.transform((0.5, 0.5))
    toolbar.press_pan(MouseEvent("button_press_event", canvas, *point, button=1))
    assert toolbar._pan_info is not None and canvas.panning
    return point


@pytest.mark.parametrize("pixel_ratio", [1, 2])
@pytest.mark.parametrize("scroll", [0, 450])
def test_pan_skips_layout_and_offscreen_axes_but_preserves_visible_pixels_and_values(
    window, monkeypatch, pixel_ratio, scroll
):
    figure, canvas, toolbar = window.figure, window.canvas, window.plot_toolbar
    window.graph_scroll.verticalScrollBar().setValue(scroll)
    canvas._set_device_pixel_ratio(pixel_ratio)
    figure.axes[1].set_ylim(0.5, 4.0)
    canvas.draw()
    automatic = [ax.get_autoscaley_on() for ax in figure.axes]
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
    x, y = start_pan(window)
    toolbar.drag_pan(MouseEvent("motion_notify_event", canvas, x + 20, y, buttons={1}))
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
    toolbar.release_pan(MouseEvent("button_release_event", canvas, x + 20, y, button=1))
    QApplication.instance().processEvents()
    assert not canvas.panning and figure in executions
    assert set(drawn) == set(figure.axes)
    assert [ax.get_autoscaley_on() for ax in figure.axes] == automatic
    assert figure.axes[1].get_ylim() == (0.5, 4.0)
    np.testing.assert_allclose(window.time_axis.axes.get_xlim(), figure.axes[0].get_xlim())


def test_export_during_pan_includes_every_axes_and_render_errors_restore_state(window, monkeypatch):
    canvas, figure = window.canvas, window.figure
    start_pan(window)
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
    window.plot_toolbar.release_pan(None)


@pytest.mark.parametrize("end", ["lost_button", "refresh", "clear_results"])
def test_pan_ends_cleanly_when_button_is_lost_or_graphs_change(window, end):
    x, y = start_pan(window)
    if end == "lost_button":
        window.plot_toolbar.drag_pan(
            MouseEvent("motion_notify_event", window.canvas, x + 20, y, buttons=set())
        )
    elif end == "refresh":
        window.plot_toolbar.refresh()
    else:
        window.clear_results()
    QApplication.instance().processEvents()
    assert window.plot_toolbar._pan_info is None and not window.canvas.panning


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
