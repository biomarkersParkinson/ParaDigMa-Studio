"""GUI runs prepare declared inputs once, including inputs already in native units."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from PySide6.QtWidgets import QCheckBox

from paradigma_studio import app as desktop, core
from paradigma_studio.axis_mapping import IMU_COLUMNS


def capture_prepared_inputs(window, monkeypatch):
    submitted = []

    def official_run(**kwargs):
        # Studio has prepared these inputs; the official orchestrator must not
        # repeat preparation or reinterpret the desktop mapping/inversions.
        assert kwargs["skip_preparation"] is True
        assert kwargs["column_mapping"] is None
        assert "axis_inversions" not in kwargs and "signal_columns" not in kwargs
        submitted.append(kwargs["dfs"])
        return {"errors": []}

    monkeypatch.setattr(core, "run_paradigma", official_run)
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: core.analyze(frame, logger=logger, **settings),
    )
    monkeypatch.setattr(window, "start_job", lambda operation, completed: operation(None))
    return submitted


@pytest.mark.parametrize("converted_units", [False, True])
@pytest.mark.parametrize("inverted", [False, True])
def test_gui_prepares_declared_units_and_axes_once(window, monkeypatch, converted_units, inverted):
    expected = pd.DataFrame(
        {
            "time": np.arange(400) / 100,
            **{name: (index + 1.0) for index, name in enumerate(IMU_COLUMNS)},
        }
    )
    source = expected.copy(deep=True)
    if converted_units:
        source["time"] *= 1000
        source[list(IMU_COLUMNS[:3])] *= 9.81
        source[list(IMU_COLUMNS[3:])] *= np.pi / 180
    source = source.rename(columns={"time": "device_time", "accelerometer_x": "ax"})
    original = source.copy(deep=True)
    window.loaded(("sensor.csv", source))
    window.gaps.setChecked(False)
    if converted_units:
        window.acc.setCurrentIndex(window.acc.findData("m/s^2"))
        window.gyro.setCurrentText("rad/s")
        window.time.setCurrentText("relative_ms")
    if inverted:
        window.mapping._inversions["accelerometer_x"].click()
        window.mapping._inversions["gyroscope_y"].click()
        expected[["accelerometer_x", "gyroscope_y"]] *= -1
    assert not any("Already prepared" in field.text() for field in window.findChildren(QCheckBox))
    assert "Already prepared" not in window.analysis_help
    submitted = capture_prepared_inputs(window, monkeypatch)
    window.run_analysis()
    assert len(submitted) == 1
    pd.testing.assert_frame_equal(
        submitted[0], expected, check_exact=not converted_units, rtol=1e-12, atol=1e-12
    )
    assert "skip_preparation" not in window._run_state.current_run["settings"]
    pd.testing.assert_frame_equal(source, original, check_exact=True)


@pytest.mark.parametrize("split_by_gaps", [False, True])
def test_native_unit_inputs_honor_selected_gap_and_duration_rules(
    window, monkeypatch, split_by_gaps
):
    times = np.concatenate((np.arange(100) / 100, 10 + np.arange(200) / 100))
    source = pd.DataFrame({"time": times, **dict.fromkeys(IMU_COLUMNS, 1.0)})
    original = source.copy(deep=True)
    window.loaded(("sensor.csv", source))
    window.gaps.setChecked(split_by_gaps)
    window.min_segment.setValue(1.5)
    submitted = capture_prepared_inputs(window, monkeypatch)
    window.run_analysis()
    assert len(submitted) == 1
    if split_by_gaps:
        sections = list(submitted[0].values())
        assert len(sections) == 1
        np.testing.assert_array_equal(sections[0].time, times[100:])
    else:
        pd.testing.assert_frame_equal(submitted[0], source, check_exact=True)
    pd.testing.assert_frame_equal(source, original, check_exact=True)


@pytest.mark.parametrize("explicit_inversions", [False, True])
def test_reusing_retired_bypass_restores_effective_choices_without_a_hidden_skip(
    window, monkeypatch, explicit_inversions
):
    source = pd.DataFrame({"time": np.arange(400) / 100, **dict.fromkeys(IMU_COLUMNS, 1.0)})
    window.loaded(("sensor.csv", source))
    saved = {
        "pipelines": ["gait"],
        "skip_preparation": True,
        "accelerometer_units": "m/s^2",
        "gyroscope_units": "rad/s",
        "time_input_unit": "absolute_ms",
        "device_orientation": ["-y", "x", "z"],
        "split_by_gaps": True,
        "drop_missing_samples": True,
    }
    if explicit_inversions:
        saved["axis_inversions"] = ["accelerometer_x", "gyroscope_y"]
    original = deepcopy(saved)
    window._run_state.selected_run = {"settings": saved}
    window.use_run_parameters()
    assert window.acc.currentData() == "g" and window.gyro.currentText() == "deg/s"
    assert window.time.currentText() == "relative_s" and not window.gaps.isChecked()
    assert window.mapping.axis_inversions() == []
    assert window.time.isEnabled() and window.gaps.isEnabled()
    assert all(field.isEnabled() for field in window.mapping._inversions.values())
    submitted = capture_prepared_inputs(window, monkeypatch)
    window.run_analysis()
    pd.testing.assert_frame_equal(submitted[0], source, check_exact=True)
    assert "skip_preparation" not in window._run_state.current_run["settings"]
    assert saved == original
