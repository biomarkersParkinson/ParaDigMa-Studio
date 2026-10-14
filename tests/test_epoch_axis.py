"""Grouped 30-minute dates/hours preserve data and use true midnight boundaries."""

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

from paradigma_studio.day_axis import RecordingDayFormatter
from paradigma_studio.epoch_axis import (
    EpochHourLocator,
    MidnightBridges,
    MidnightSeparators,
    style_epoch_axis,
)
from paradigma_studio.results_view import recording_clock
from paradigma_studio.time_axis import RecordingTimeFormatter


def epoch_axis(start="2026-10-14", days=3, timezone="Europe/Amsterdam", width=1000):
    figure = Figure(figsize=(width / 100, 2.5), dpi=100)
    FigureCanvasAgg(figure)
    axis = figure.add_subplot()
    stamps = pd.date_range(start, periods=days + 1, freq="D", tz=timezone)
    axis.set_xlim(dates.date2num(stamps[[0, -1]]))
    style_epoch_axis(
        axis,
        timezone,
        calendar=True,
        clock_formatter=RecordingTimeFormatter(timezone, show_date=False),
        labels=True,
    )
    return figure, axis, stamps


@pytest.mark.parametrize("timezone", ["UTC", "Europe/Amsterdam", "Asia/Kathmandu"])
def test_calendar_dates_and_clock_times_are_separate_and_centered(timezone):
    figure, axis, stamps = epoch_axis(timezone=timezone)
    figure.canvas.draw()
    assert [label.get_text() for label in axis.get_xticklabels()] == stamps[:-1].strftime(
        "%d %b %Y"
    ).tolist()
    boundaries = dates.date2num(stamps)
    np.testing.assert_allclose(axis.get_xticks(), (boundaries[:-1] + boundaries[1:]) / 2)
    clock = [label.get_text() for label in axis.get_xticklabels(minor=True)]
    assert clock and all("\n" not in label for label in clock)
    assert "00:00" in clock and any(label != "00:00" for label in clock)
    renderer = figure.canvas.get_renderer()
    dates_box = axis.get_xticklabels()[0].get_window_extent(renderer)
    clocks_box = axis.get_xticklabels(minor=True)[0].get_window_extent(renderer)
    assert clocks_box.y0 > dates_box.y1


def stacked_epoch_axes():
    figure, _, stamps = epoch_axis()
    figure.clear()
    figure.set_size_inches(10, 6)
    axes = figure.subplots(3, 1, sharex=True)
    for axis in axes:
        style_epoch_axis(
            axis,
            "Europe/Amsterdam",
            calendar=True,
            clock_formatter=RecordingTimeFormatter("Europe/Amsterdam", show_date=False),
        )
        axis._paradigma_day_groups = True
        MidnightSeparators(axis, "Europe/Amsterdam")
    axes[0].set_xlim(dates.date2num(stamps[[0, -1]]))
    return figure, axes, stamps, MidnightBridges(figure, "Europe/Amsterdam")


def test_midnight_lines_join_through_graph_gaps_and_follow_pan_and_resize():
    figure, axes, stamps, bridges = stacked_epoch_axes()
    midnight = dates.date2num(stamps[1])
    ranges = [stamps[[0, -1]], stamps[1] + pd.to_timedelta([-8, 8], unit="h")]
    for limits, width in zip(ranges, [10, 7], strict=True):
        axes[0].set_xlim(dates.date2num(limits))
        figure.set_size_inches(width, 6)
        figure.canvas.draw()
        x = axes[0].get_xaxis_transform().transform((midnight, 0))[0]
        segments = [
            figure.transFigure.transform(segment) for segment in bridges.lines.get_segments()
        ]
        image = np.asarray(figure.canvas.buffer_rgba())
        for upper, lower in zip(axes, axes[1:], strict=False):
            expected = [(x, lower.bbox.y1), (x, upper.bbox.y0)]
            assert any(np.allclose(segment, expected) for segment in segments)
            y = (lower.bbox.y1 + upper.bbox.y0) / 2
            row = round(image.shape[0] - y - 1)
            column = round(x)
            assert image[row, column - 1 : column + 2, :3].min() < 240
        assert bridges.get_zorder() < min(axis.get_zorder() for axis in axes)


@pytest.mark.parametrize("start,hours", [("2026-03-28", 23), ("2026-10-24", 25)])
def test_midnight_lines_follow_dst_and_do_not_affect_bounds_or_bar_style(start, hours):
    figure, axis, stamps = epoch_axis(start=start)
    axis.plot(dates.date2num(stamps[:-1]), [2, 4, 3], color="#477DA3")
    bounds, limits, vertical = axis.dataLim.bounds, axis.get_xlim(), axis.get_ylim()
    separator = MidnightSeparators(axis, "Europe/Amsterdam")
    figure.canvas.draw()
    positions = np.array([segment[0, 0] for segment in separator.lines.get_segments()])
    np.testing.assert_allclose(positions, dates.date2num(stamps), rtol=0, atol=1e-10)
    assert (positions[2] - positions[1]) * 24 == pytest.approx(hours)
    assert (
        axis.dataLim.bounds == bounds and axis.get_xlim() == limits and axis.get_ylim() == vertical
    )
    assert axis.get_facecolor() == (1, 1, 1, 1)
    assert separator.get_zorder() < axis.lines[0].get_zorder()


def test_fallback_hour_disambiguation_is_retained_on_the_clock_row():
    figure, axis, _ = epoch_axis(start="2026-10-25")
    limits = dates.date2num(pd.to_datetime(["2026-10-25T00:00:00Z", "2026-10-25T02:30:00Z"]))
    axis.set_xlim(limits)
    locations = dates.date2num(pd.date_range("2026-10-25T00:00:00Z", periods=6, freq="30min"))
    formatter = axis.xaxis.get_minor_formatter()
    formatter.set_locs(locations)
    assert formatter(locations[0]) == "02:00 +0200"
    assert formatter(locations[2]) == "02:00 +0100"
    figure.canvas.draw()


def test_long_ranges_thin_dates_omit_redundant_hours_and_restore_hours_on_zoom():
    figure, axis, stamps = epoch_axis(days=60, width=600)
    figure.canvas.draw()
    assert 0 < len(axis.get_xticks()) < 60
    assert not len(axis.get_xticks(minor=True))
    boxes = [
        label.get_window_extent(figure.canvas.get_renderer()) for label in axis.get_xticklabels()
    ]
    assert all(left.x1 < right.x0 for left, right in zip(boxes, boxes[1:], strict=False))
    axis.set_xlim(dates.date2num(stamps[[0, 1]]))
    figure.canvas.draw()
    assert [label.get_text() for label in axis.get_xticklabels()] == ["14 Oct 2026"]
    assert len(axis.get_xticks(minor=True)) > 1


def test_elapsed_day_groups_do_not_invent_dates_or_change_the_numeric_timeline():
    figure, axis, _ = epoch_axis()
    axis.set_xlim(0, 2 * 86400)
    style_epoch_axis(axis, None, calendar=False, clock_formatter=None, labels=True)
    separator = MidnightSeparators(axis, calendar=False)
    figure.canvas.draw()
    assert [label.get_text() for label in axis.get_xticklabels()] == ["Day 1", "Day 2"]
    assert "12:00" in [label.get_text() for label in axis.get_xticklabels(minor=True)]
    np.testing.assert_array_equal(
        [segment[0, 0] for segment in separator.lines.get_segments()], [0, 86400, 172800]
    )
    assert axis.get_xlim() == (0, 172800)


def test_repeated_drawing_reuses_time_ticks_and_separator_geometry(monkeypatch):
    figure, axes, _, bridges = stacked_epoch_axes()
    axis = axes[0]
    separator = next(artist for artist in axis.artists if isinstance(artist, MidnightSeparators))
    figure.canvas.draw()
    locator = axis.xaxis.get_minor_locator()
    assert isinstance(locator, EpochHourLocator)
    with monkeypatch.context() as patch:
        patch.setattr(
            locator, "_hour_locations", lambda *_: pytest.fail("Recomputed identical hour ticks")
        )
        patch.setattr(
            separator.lines,
            "set_segments",
            lambda *_: pytest.fail("Recomputed identical midnight lines"),
        )
        patch.setattr(
            bridges.lines,
            "set_segments",
            lambda *_: pytest.fail("Recomputed identical graph bridges"),
        )
        figure.canvas.draw()


def epoch_results():
    times = np.arange(0, 3 * 86400, 4.0)
    return {
        "classifications": {
            "tremor": pd.DataFrame(
                {"time": times, "pred_tremor_checked": (times % 1800 < 300).astype(int)}
            )
        }
    }


@pytest.mark.parametrize("start", ["2026-10-14T00:00:00+05:45", "2026-10-14T00:00:00"])
def test_epoch_graphs_preserve_original_metadata_clock_without_assuming_a_timezone(window, start):
    source = pd.DataFrame({"time": [0.0, 1.0]})
    source.attrs["desktop_recording_start"] = start
    clock = recording_clock(source, {}, timeline=np.array([0.0, 1.0]))
    window.provenance = {"display_clock": clock}
    window.analyzed(epoch_results())
    select_plot_metric(window, "classifications/tremor", "pred_tremor_checked")
    window.result_graph_view.setCurrentIndex(1)
    window.canvas.draw()
    window.time_axis.draw()
    assert window.display_clock == clock
    assert [label.get_text() for label in window.time_axis.axes.get_xticklabels()] == [
        "14 Oct 2026",
        "15 Oct 2026",
        "16 Oct 2026",
    ]
    assert "00:00" in [
        label.get_text() for label in window.time_axis.axes.get_xticklabels(minor=True)
    ]
    assert (clock["timezone"] or "timezone unspecified") in window.figure.axes[0].get_xlabel()


def test_graph_changes_reuse_one_bridge_and_other_views_and_clear_remove_it(window):
    results = epoch_results()
    results["classifications"]["tremor"]["pred_arm_at_rest"] = 1
    window.analyzed(results)
    select_plot_metric(window, "classifications/tremor", "pred_tremor_checked")
    window.result_graph_view.setCurrentIndex(1)
    bridge = next(artist for artist in window.figure.artists if isinstance(artist, MidnightBridges))
    extra = window._series_items[("classifications/tremor", "pred_arm_at_rest")]
    for state in (Qt.Checked, Qt.Unchecked, Qt.Checked):
        extra.setCheckState(0, state)
        window.canvas.draw()
        assert [
            artist for artist in window.figure.artists if isinstance(artist, MidnightBridges)
        ] == [bridge]
        assert bool(bridge.lines.get_segments()) == (state == Qt.Checked)
    for mode in (2, 0, 1):
        window.result_graph_view.setCurrentIndex(mode)
        assert any(isinstance(artist, MidnightBridges) for artist in window.figure.artists) == (
            mode == 1
        )
    window.clear_results()
    assert not any(isinstance(artist, MidnightBridges) for artist in window.figure.artists)


@pytest.mark.parametrize("view", [0, 1, 2], ids=["detailed", "30-minute", "day"])
@pytest.mark.parametrize("calendar", [False, True], ids=["elapsed", "calendar"])
def test_axis_limits_keep_dates_or_seconds_for_all_views(window, view, calendar):
    window.provenance = (
        {"display_clock": {"origin": "2026-10-14T00:00:00+02:00", "timezone": "Europe/Amsterdam"}}
        if calendar
        else {}
    )
    output = epoch_results()
    window.analyzed(output)
    select_plot_metric(window, "classifications/tremor", "pred_tremor_checked")
    window.result_graph_view.setCurrentIndex(view)
    axis = window.figure.axes[0]
    initial = axis.get_xlim()
    toolbar = window.plot_toolbar
    toolbar.active_axes = axis
    toolbar.settings_action.setChecked(True)
    automatic, lower, upper = toolbar.settings.bounds["x"]
    assert ("ISO date/time" in lower.toolTip()) == calendar
    automatic.setChecked(False)
    if calendar:
        bounds = pd.to_datetime(["2026-10-14T06:00:00+02:00", "2026-10-15T18:00:00+02:00"])
        lower.setText(bounds[0].isoformat())
        upper.setText(bounds[1].isoformat())
        expected = dates.date2num(bounds)
    else:
        lower.setText("21600")
        upper.setText("151200")
        expected = (21600, 151200)
    upper.editingFinished.emit()
    assert toolbar.settings.error.isHidden()
    np.testing.assert_allclose(axis.get_xlim(), expected)
    toolbar.settings.reset_button.click()
    np.testing.assert_allclose(axis.get_xlim(), initial)
    pd.testing.assert_frame_equal(
        window.tables["classifications/tremor"],
        output["classifications"]["tremor"],
        check_exact=True,
    )


def test_live_epoch_axis_and_exports_keep_days_hours_selection_and_values(window):
    window.resize(1450, 920)
    window.provenance = {
        "display_clock": {"origin": "2026-10-14T00:00:00+02:00", "timezone": "Europe/Amsterdam"}
    }
    results = epoch_results()
    original = deepcopy(results)
    window.analyzed(results)
    select_plot_metric(window, "classifications/tremor", "pred_tremor_checked")
    window.result_graph_view.setCurrentIndex(1)
    QApplication.instance().processEvents()
    window.canvas.draw()
    window.time_axis.draw()
    axis = window.figure.axes[0]
    summary = axis._paradigma_epoch_data.copy(deep=True)
    values = [path.vertices.copy() for path in axis.collections[0].get_paths()]
    facecolors = axis.collections[0].get_facecolors().copy()
    assert any(isinstance(artist, MidnightSeparators) for artist in axis.artists)
    assert [label.get_text() for label in window.time_axis.axes.get_xticklabels()] == [
        "14 Oct 2026",
        "15 Oct 2026",
        "16 Oct 2026",
    ]
    assert any(label.get_visible() for label in window.time_axis.axes.get_xticklabels(minor=True))
    renderer = window.time_axis.get_renderer()
    for label in window.time_axis.axes.get_xticklabels() + window.time_axis.axes.get_xticklabels(
        minor=True
    ):
        box = label.get_window_extent(renderer)
        assert box.y0 >= 0 and box.y1 <= window.time_axis.figure.bbox.y1
    image = BytesIO()
    seen = []
    window.canvas.mpl_connect(
        "draw_event",
        lambda *_: seen.append(
            (
                window.canvas.exporting_time_axis,
                any(label.get_visible() for label in axis.get_xticklabels(minor=True)),
            )
        ),
    )
    window.figure.savefig(image, format="png", dpi=150)
    assert image.getvalue().startswith(b"\x89PNG") and (True, True) in seen
    assert not axis.get_xticklabels() and not axis.get_xticklabels(minor=True)
    pd.testing.assert_frame_equal(axis._paradigma_epoch_data, summary, check_exact=True)
    np.testing.assert_array_equal(axis.collections[0].get_facecolors(), facecolors)
    for path, before in zip(axis.collections[0].get_paths(), values, strict=True):
        np.testing.assert_array_equal(path.vertices, before)
    pd.testing.assert_frame_equal(
        results["classifications"]["tremor"],
        original["classifications"]["tremor"],
        check_exact=True,
    )
    window.result_graph_view.setCurrentIndex(2)
    assert isinstance(window.time_axis.axes.xaxis.get_major_formatter(), RecordingDayFormatter)
    assert not window.time_axis.axes.get_xticklabels(minor=True)
    window.result_graph_view.setCurrentIndex(0)
    assert isinstance(window.time_axis.axes.xaxis.get_major_formatter(), RecordingTimeFormatter)
    assert not window.time_axis.axes.get_xticklabels(minor=True)
