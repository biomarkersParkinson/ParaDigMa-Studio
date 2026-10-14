"""Day presentation respects calendars, label space and unchanged graph data."""

from copy import deepcopy
from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from conftest import select_plot_metric
from matplotlib import dates
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_studio.day_axis import RecordingDayFormatter, RecordingDayLocator
from paradigma_studio.time_axis import RecordingTimeFormatter


def calendar_axis(days=7, width=1000, start="2026-10-14", timezone="Europe/Amsterdam"):
    figure = Figure(figsize=(width / 100, 2), dpi=100)
    FigureCanvasAgg(figure)
    axis = figure.add_subplot()
    stamps = pd.date_range(start, periods=days + 1, freq="D", tz=timezone)
    axis.set_xlim(dates.date2num(stamps[[0, -1]]))
    axis.xaxis.set_major_locator(RecordingDayLocator(timezone))
    axis.xaxis.set_major_formatter(RecordingDayFormatter(timezone))
    axis.tick_params(labelsize=9)
    return figure, axis, stamps


@pytest.mark.parametrize("timezone", ["UTC", "Europe/Amsterdam", "Asia/Kathmandu"])
def test_every_day_gets_a_centered_date_when_labels_fit(timezone):
    figure, axis, stamps = calendar_axis(timezone=timezone)
    figure.canvas.draw()
    positions = axis.get_xticks()
    np.testing.assert_allclose(
        positions, np.mean([dates.date2num(stamps[:-1]), dates.date2num(stamps[1:])], axis=0)
    )
    assert [label.get_text() for label in axis.get_xticklabels()] == stamps[:-1].strftime(
        "%d %b\n%Y"
    ).tolist()


@pytest.mark.parametrize("days,width", [(40, 600), (365, 600), (7, 300)])
def test_labels_thin_without_overlap_and_return_on_zoom(days, width):
    figure, axis, stamps = calendar_axis(days, width)
    figure.canvas.draw()
    assert 0 < len(axis.get_xticks()) < days
    boxes = [
        label.get_window_extent(figure.canvas.get_renderer()) for label in axis.get_xticklabels()
    ]
    assert all(left.x1 < right.x0 for left, right in zip(boxes, boxes[1:], strict=False))
    assert boxes[0].x0 >= axis.bbox.x0 and boxes[-1].x1 <= axis.bbox.x1
    axis.set_xlim(dates.date2num(stamps[[0, 2]]))
    figure.canvas.draw()
    assert [label.get_text() for label in axis.get_xticklabels()] == stamps[:2].strftime(
        "%d %b\n%Y"
    ).tolist()


@pytest.mark.parametrize("start,hours", [("2026-03-28", 23), ("2026-10-24", 25)])
def test_dates_follow_local_midnight_and_dst_without_altering_data_bounds(start, hours):
    figure, axis, stamps = calendar_axis(3, start=start)
    axis.plot(dates.date2num(stamps[:-1]), [2, 5, 3])
    bounds, limits, vertical = axis.dataLim.bounds, axis.get_xlim(), axis.get_ylim()
    figure.canvas.draw()
    boundaries = dates.date2num(stamps)
    np.testing.assert_allclose(axis.get_xticks(), (boundaries[:-1] + boundaries[1:]) / 2)
    assert [label.get_text() for label in axis.get_xticklabels()] == stamps[:-1].strftime(
        "%d %b\n%Y"
    ).tolist()
    assert (boundaries[2] - boundaries[1]) * 24 == pytest.approx(hours)
    assert (
        axis.dataLim.bounds == bounds and axis.get_xlim() == limits and axis.get_ylim() == vertical
    )


def test_partial_day_zoom_keeps_the_date_and_elapsed_days_never_invent_dates():
    figure, axis, stamps = calendar_axis(2)
    axis.set_xlim(dates.date2num(stamps[0]) + 20 / 24, dates.date2num(stamps[0]) + 22 / 24)
    figure.canvas.draw()
    assert [label.get_text() for label in axis.get_xticklabels()] == ["14 Oct\n2026"]
    axis.xaxis.set_major_locator(RecordingDayLocator(calendar=False))
    axis.xaxis.set_major_formatter(RecordingDayFormatter(calendar=False))
    axis.set_xlim(0, 3 * 86400)
    figure.canvas.draw()
    assert [label.get_text() for label in axis.get_xticklabels()] == ["Day 1", "Day 2", "Day 3"]


def test_day_ticks_reuse_the_same_view_and_follow_panning_and_resize(monkeypatch):
    figure, axis, stamps = calendar_axis(7)
    figure.canvas.draw()
    locator = axis.xaxis.get_major_locator()
    original = axis.get_xticks().copy()
    with monkeypatch.context() as patch:
        patch.setattr(
            locator, "_day_locations", lambda *_: pytest.fail("Unchanged view rebuilt day ticks")
        )
        figure.canvas.draw()
    axis.set_xlim(dates.date2num(stamps[[1, -2]]))
    figure.canvas.draw()
    np.testing.assert_allclose(axis.get_xticks(), original[1:-1])
    figure.set_size_inches(3, 2)
    figure.canvas.draw()
    assert len(axis.get_xticks()) < len(original) - 2


def daily_results():
    times = np.concatenate([np.arange(0, 1200, 4) + day * 86400 for day in range(7)])
    pulse_times = np.concatenate([np.arange(1200) + day * 86400 for day in range(7)])
    return {
        "classifications": {
            "tremor": pd.DataFrame(
                {"time": times, "pred_tremor_checked": (times % 86400 < 300).astype(int)}
            )
        },
        "quantifications": {
            "pulse_rate": pd.DataFrame(
                {"time": pulse_times, "pulse_rate": 60 + pulse_times // 86400}
            )
        },
        "metadata": {
            "desktop_availability": {
                "tremor": {
                    "df_1": {"intervals": [[day * 86400, day * 86400 + 1200] for day in range(7)]}
                }
            }
        },
    }


def test_live_day_axis_aligns_graphs_exports_dates_and_preserves_series(window):
    window.resize(1450, 920)
    output = daily_results()
    original = deepcopy(output)
    window.provenance = {
        "display_clock": {"origin": "2026-10-14T00:00:00+02:00", "timezone": "Europe/Amsterdam"}
    }
    window.analyzed(output)
    select_plot_metric(window, "classifications/tremor", "pred_tremor_checked")
    select_plot_metric(window, "quantifications/pulse_rate", "pulse_rate")
    coverage = next(
        item for key, item in window._series_items.items() if key[0].startswith("preparation/")
    )
    coverage.setCheckState(0, Qt.Unchecked)
    window.result_graph_view.setCurrentIndex(2)
    QApplication.instance().processEvents()
    window.canvas.draw()
    window.time_axis.draw()
    axes = window.figure.axes
    assert all(axis.get_facecolor() == (1, 1, 1, 1) for axis in axes)
    assert isinstance(window.time_axis.axes.xaxis.get_major_formatter(), RecordingDayFormatter)
    assert "Recording date" in window.time_axis.axes.get_xlabel()
    labels = [label.get_text() for label in window.time_axis.axes.get_xticklabels()]
    assert labels == pd.date_range("2026-10-14", periods=7).strftime("%d %b\n%Y").tolist()
    summaries = [axis._paradigma_epoch_data.copy(deep=True) for axis in axes]
    collections = [axis.collections[0].get_paths()[0].vertices.copy() for axis in axes]
    image = BytesIO()
    window.figure.savefig(image, format="png", dpi=150)
    assert image.getvalue().startswith(b"\x89PNG")
    assert not window.canvas.exporting_time_axis
    assert not any(label.get_visible() for label in axes[-1].get_xticklabels())
    for axis, summary, vertices in zip(axes, summaries, collections, strict=True):
        pd.testing.assert_frame_equal(axis._paradigma_epoch_data, summary, check_exact=True)
        np.testing.assert_array_equal(axis.collections[0].get_paths()[0].vertices, vertices)
    coverage.setCheckState(0, Qt.Checked)
    assert all(axis in window.figure.axes for axis in axes)
    window.result_graph_view.setCurrentIndex(1)
    assert isinstance(window.time_axis.axes.xaxis.get_major_formatter(), RecordingTimeFormatter)
    for stage in ("classifications", "quantifications"):
        for module in original[stage]:
            pd.testing.assert_frame_equal(
                output[stage][module], original[stage][module], check_exact=True
            )
