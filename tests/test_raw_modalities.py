"""Raw plots separate physical modalities while retaining original values and timing."""

import warnings

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_previews
from matplotlib import dates
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paradigma_studio.app import MainWindow


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = MainWindow(tmp_path / "runs")
    widget.show()
    yield widget
    wait_for_previews(widget)
    widget.close()
    app.processEvents()


def signals(axes):
    return [line for line in axes.lines if line.get_gid() is None]


@pytest.mark.parametrize("context", [False, True], ids=["data", "sensor-context"])
@pytest.mark.parametrize("dated", [False, True], ids=["elapsed", "calendar"])
def test_modalities_share_time_and_have_independent_ranges_colors_and_original_values(
    window, context, dated
):
    times = np.arange(1001) / 100
    source = pd.DataFrame(
        {
            "time": times,
            "accelerometer_x": np.sin(times),
            "gyroscope_x": 100 * np.cos(times),
            "accelerometer_y": 0.5 * np.cos(times),
            "gyroscope_z": 200 * np.sin(times),
            "green": 2000 + 30 * np.sin(times),
            "red": 3000 + 20 * np.cos(times),
        }
    )
    if dated:
        source["time_dt" if context else "time"] = pd.Timestamp(
            "2026-10-10T14:00:00+02:00"
        ) + pd.to_timedelta(times, unit="s")
    original = source.copy(deep=True)
    window.loaded(("recording.csv", source))
    if context:
        window._result_state.provenance = {
            "source": "recording.csv",
            "settings": {"skip_preparation": True},
        }
        window.analyzed(
            {"quantifications": {"tremor": pd.DataFrame({"time": [5.0], "tremor_power": [2.0]})}}
        )
        window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
        window.inspect_sensor_context()
        choose, figure, toolbar = (
            window.set_sensor_channels,
            window.sensor_figure,
            window.sensor_toolbar,
        )
        frame = window._sensor_state.sensor_frame
    else:
        window.navigate(0)
        window.data_tabs.setCurrentIndex(1)
        choose, figure, toolbar = window.set_input_channels, window.data_figure, window.data_toolbar
        frame = source
    choose([column for column in source if column != "time"])
    groups = [
        ["accelerometer_x", "accelerometer_y"],
        ["gyroscope_x", "gyroscope_z"],
        ["green", "red"],
    ]
    assert [[line.get_label() for line in signals(ax)] for ax in figure.axes] == groups
    colors = {line.get_label(): line.get_color() for ax in figure.axes for line in signals(ax)}
    assert len(set(colors.values())) == 6
    for ax, group in zip(figure.axes, groups, strict=False):
        assert [text.get_text() for text in ax.get_legend().get_texts()] == group
        assert ax.get_shared_x_axes().joined(figure.axes[0], ax)
        for line in signals(ax):
            np.testing.assert_array_equal(line.get_ydata(), frame[line.get_label()])
            actual_x = dates.date2num(line.get_xdata()) if dated else line.get_xdata()
            expected_x = (
                dates.date2num(frame["time_dt" if context else "time"]) if dated else frame.time
            )
            np.testing.assert_allclose(actual_x, expected_x)
    assert figure.axes[0].get_ylim()[1] < 2
    assert figure.axes[1].get_ylim()[1] > 100
    assert figure.axes[2].get_ylim()[0] > figure.axes[1].get_ylim()[1]
    assert [ax.xaxis.label.get_visible() for ax in figure.axes] == [False, False, True]
    # A clicked modality owns Y limits; X limits remain linked across modalities.
    toolbar.active_axes = figure.axes[1]
    toolbar.settings_action.setChecked(True)
    for axis, limits in (
        (
            "x",
            (
                signals(figure.axes[0])[0].get_xdata()[200],
                signals(figure.axes[0])[0].get_xdata()[600],
            ),
        ),
        ("y", (-500.0, 500.0)),
    ):
        automatic, lower, upper = toolbar.settings.bounds[axis]
        automatic.setChecked(False)
        if dated and axis == "x":
            lower.setText(pd.Timestamp(limits[0]).isoformat())
            upper.setText(pd.Timestamp(limits[1]).isoformat())
        else:
            lower.setText(str(limits[0]))
            upper.setText(str(limits[1]))
    untouched_y = [figure.axes[i].get_ylim() for i in (0, 2)]
    toolbar.settings.apply()
    assert toolbar.settings.error.isHidden()
    assert figure.axes[1].get_ylim() == (-500.0, 500.0)
    assert [figure.axes[i].get_ylim() for i in (0, 2)] == untouched_y
    assert all(ax.get_xlim() == figure.axes[0].get_xlim() for ax in figure.axes)
    choose(["gyroscope_z", "accelerometer_y"])
    assert len(figure.axes) == 2
    for ax in figure.axes:
        line = signals(ax)[0]
        assert line.get_color() == colors[line.get_label()]
    pd.testing.assert_frame_equal(source, original)
    pd.testing.assert_frame_equal(window.input_table.model().frame, original)


def test_axis_aliases_optical_channels_and_unknown_streams_do_not_mix(window):
    frame = pd.DataFrame(
        {
            "time": [0.0, 1.0, 2.0],
            "ACC_X": [0.0, 1.0, 0.0],
            "accY": [1.0, 0.0, 1.0],
            "gyroX": [0.0, 1.0, 0.0],
            "GYR_Z": [1.0, 0.0, 1.0],
            "magnetometer_x": [2.0, 3.0, 4.0],
            "green": [0.0, 1.0, 0.0],
            "infrared": [1.0, 0.0, 1.0],
            "red": [0.0, 1.0, 0.0],
            "temperature": [30.0, 31.0, 32.0],
            "battery": [90.0, 89.0, 88.0],
            "wear_flag": [0, 1, 0],
        }
    )
    window.loaded(("sensor.csv", frame))
    window.set_input_channels(list(frame.columns[1:]))
    groups = [[line.get_label() for line in signals(ax)] for ax in window.data_figure.axes]
    assert groups[:-1] == [
        ["ACC_X", "accY"],
        ["gyroX", "GYR_Z"],
        ["magnetometer_x"],
        ["green", "infrared", "red"],
        ["temperature"],
        ["battery"],
    ]
    states = window.data_figure.axes[-1]
    assert groups[-1] == []
    np.testing.assert_array_equal(states.collections[0].get_offsets(), [[1.0, 1.0]])
    assert not states.get_yticks().size


def test_custom_mapping_groups_original_names_and_does_not_block_on_conflicting_choices(window):
    frame = pd.DataFrame(
        {"time": [0.0, 1.0, 2.0], "a": [2.0, 3.0, 4.0], "b": [4.0, 5.0, 6.0], "c": [7.0, 8.0, 9.0]}
    )
    window.loaded(("sensor.csv", frame))
    window.set_input_channels(["a", "b", "c"])
    assert len(window.data_figure.axes) == 3
    mapping = {"a": "accelerometer_x", "b": "accelerometer_y", "c": "gyroscope_x"}
    window.navigate(1)
    window.mapping.set_mapping(mapping)
    window.navigate(0)
    window.data_tabs.setCurrentIndex(1)
    assert [[line.get_label() for line in signals(ax)] for ax in window.data_figure.axes] == [
        ["a", "b"],
        ["c"],
    ]
    window.mapping.set_mapping({"a": "time", "b": "green"})
    window.mapping._combos["green"].setCurrentIndex(window.mapping._combos["green"].findData("a"))
    assert len(window.data_figure.axes) == 3
    window._result_state.provenance = {
        "source": "sensor.csv",
        "settings": {"column_mapping": mapping, "skip_preparation": True},
    }
    window.analyzed(
        {"quantifications": {"tremor": pd.DataFrame({"time": [1.0], "tremor_power": [2.0]})}}
    )
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    window.inspect_sensor_context()
    window.set_sensor_channels(["a", "b", "c"])
    assert [[line.get_label() for line in signals(ax)] for ax in window.sensor_figure.axes] == [
        ["a", "b"],
        ["c"],
    ]
    pd.testing.assert_frame_equal(window._input_state.frame, frame)


@pytest.mark.parametrize("epochs", [False, True], ids=["detailed", "30-minute"])
def test_compact_results_fit_four_graphs_with_readable_titles_and_fixed_time_axis(window, epochs):
    frame = pd.DataFrame(
        {"time": np.arange(4.0) * 1800, **{f"metric_{i}": [2.0, 3.0, 4.0, 5.0] for i in range(4)}}
    )
    window.analyzed({"quantifications": {"tremor": frame}})
    window.result_series.blockSignals(True)
    for item in window._result_state._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.result_graph_view.setCurrentIndex(int(epochs))
    window.plot()
    window.navigate(2)
    window.result_tabs.setCurrentIndex(1)
    window.resize(1200, 1000)
    QTest.qWait(40)
    with warnings.catch_warnings(record=True) as caught:
        window.canvas.draw()
        window.time_axis.draw()
    assert not [w for w in caught if "constrained_layout" in str(w.message)]
    assert len(window.figure.axes) == 4
    assert window.graph_scroll.verticalScrollBar().maximum() == 0
    renderer = window.canvas.get_renderer()
    for ax in window.figure.axes:
        bounds = ax.get_title(loc="left")
        assert bounds
        title_bounds = ax._left_title.get_window_extent(renderer)
        assert title_bounds.y0 >= 0 and title_bounds.y1 <= window.figure.bbox.y1
        assert ax.bbox.height >= 70
    assert window.time_axis.visibleRegion().contains(window.time_axis.rect())
