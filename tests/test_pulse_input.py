"""Raw PPG-only inputs retain official pulse processing and input validation."""

import numpy as np
import pandas as pd
import pytest
from conftest import wait_for_previews
from paradigma.config import PulseRateConfig
from paradigma.prepare_data import prepare_time_column
from test_scientific_equivalence import DATA, compare_workflows

from paradigma_studio import core
from paradigma_studio.exploration import source_timeline


@pytest.mark.scientific
@pytest.mark.parametrize("unit", sorted(core.TIME_UNITS))
def test_raw_ppg_only_matches_official_stages_and_positive_outputs(unit, tmp_path):
    recorded = pd.read_parquet(DATA / "prepared_ppg.parquet")
    times = recorded.time.to_numpy()
    encodings = {
        "relative_s": times,
        "relative_ms": times * 1000,
        "absolute_s": 1_700_000_000 + times,
        "absolute_ms": 1_700_000_000_000 + times * 1000,
        "difference_s": np.r_[0.0, np.diff(times)],
        "difference_ms": np.r_[0.0, np.diff(times)] * 1000,
    }
    frame = (
        recorded.assign(time=encodings[unit])
        .rename(columns={"time": "device_clock", "green": "optical"})
        .astype(str)
    )
    mapping = {"device_clock": "time", "optical": "green"}
    # Independent public preparation step: the generic upstream validator is
    # IMU-specific, while pulse preprocessing itself accepts only time + green.
    reference = prepare_time_column(
        frame.rename(columns=mapping).apply(pd.to_numeric), input_unit_type=unit
    )
    actual, expected, stages = compare_workflows(
        frame,
        reference,
        ["pulse_rate"],
        tmp_path,
        column_mapping=mapping,
        time_input_unit=unit,
        pulse_rate_config=PulseRateConfig(ppg_sampling_frequency=100, min_window_length_s=10),
    )
    assert not actual["classifications"]["pulse_rate"].empty
    assert not actual["quantifications"]["pulse_rate"].empty
    assert np.isfinite(actual["quantifications"]["pulse_rate"].pulse_rate).all()
    assert actual["aggregations"]["pulse_rate"] == expected["aggregations"]["pulse_rate"]
    preprocessing = next(
        stage for stage in stages if stage["stage"].endswith("/preprocess_ppg_data")
    )
    assert list(preprocessing["inputs"][0]) == ["time", "green"]


@pytest.mark.parametrize("column", ["time", "green"])
@pytest.mark.parametrize("value", [np.nan, np.inf])
def test_ppg_only_still_rejects_missing_required_values(column, value):
    frame = pd.DataFrame({"time": np.arange(20) / 10, "green": np.ones(20)})
    frame.loc[4, column] = value
    with pytest.raises(ValueError, match="missing values"):
        core.analyze(frame, pipelines=["pulse_rate"])


@pytest.mark.parametrize(
    "unit,value,message",
    [("relative_s", 0.2, "strictly increasing"), ("difference_ms", -1, "Time differences")],
)
def test_ppg_only_still_rejects_invalid_time(unit, value, message):
    frame = pd.DataFrame({"time": np.arange(20) / 10, "green": np.ones(20)})
    if unit == "difference_ms":
        frame["time"] = np.r_[0.0, np.full(19, 100.0)]
    frame.loc[4, "time"] = value
    with pytest.raises(ValueError, match=message):
        core.analyze(frame, pipelines=["pulse_rate"], time_input_unit=unit)


def test_ppg_only_missing_samples_keep_source_clock_and_independent_sections(monkeypatch):
    frame = pd.DataFrame({"time": 1_700_000_000 + np.arange(20) / 10, "green": np.ones(20)})
    frame.loc[[0, 8, 9], "green"] = np.nan
    original = frame.copy(deep=True)
    captured = []
    monkeypatch.setattr(
        core, "run_paradigma", lambda **kwargs: captured.append(kwargs["dfs"]) or {"errors": []}
    )
    settings = {
        "pipelines": ["pulse_rate"],
        "time_input_unit": "absolute_s",
        "drop_missing_samples": True,
    }
    timeline = source_timeline(frame, settings)
    assert timeline[1] == 0
    results = core.analyze(frame, **settings)
    sections = list(captured[0].values())
    assert [len(section) for section in sections] == [7, 10]
    np.testing.assert_array_equal(
        pd.concat(sections).time.to_numpy(), timeline[frame.green.notna()]
    )
    assert results["metadata"]["desktop_preparation"]["excluded_samples"] == 3
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


@pytest.mark.parametrize("module", ["gait", "tremor"])
def test_ppg_only_does_not_relax_imu_module_requirements(module):
    frame = pd.DataFrame({"time": np.arange(20) / 10, "green": np.ones(20)})
    with pytest.raises(ValueError, match="Missing sensor columns.*gyroscope_x"):
        core.analyze(frame, pipelines=[module])


def test_combined_modules_retain_ppg_results_when_imu_channels_are_missing(tmp_path):
    frame = pd.read_parquet(DATA / "prepared_ppg.parquet")
    original = frame.copy(deep=True)
    results = core.analyze(
        frame,
        pipelines=["gait", "pulse_rate"],
        pulse_rate_config=PulseRateConfig(ppg_sampling_frequency=100, min_window_length_s=10),
        output_dir=tmp_path,
    )
    assert len(results["errors"]) == 1
    assert results["errors"][0]["pipelines"] == ["gait"]
    assert "Missing sensor columns" in results["errors"][0]["error"]
    assert not results["classifications"]["pulse_rate"].empty
    assert not results["quantifications"]["pulse_rate"].empty
    assert results["aggregations"]["pulse_rate"]
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


def test_raw_pulse_only_ui_requests_ppg_without_accelerometer(window):
    window.loaded(("ppg.csv", pd.DataFrame({"time": [0.0, 0.1, 0.2], "green": [1.0, 2.0, 1.0]})))
    window.set_modules(["pulse_rate"])
    wait_for_previews(window)
    assert window.module_requirements.text() == "Raw green PPG required."
    assert window.run_button.isEnabled()
    assert not window.prepared.isChecked()
    window.prepared.setChecked(True)
    assert window.module_requirements.text() == "Raw green PPG required."
