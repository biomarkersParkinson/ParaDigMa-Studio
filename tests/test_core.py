import json

import numpy as np
import pandas as pd
import pytest

from paradigma_desktop.core import analyze, export_results, load_sensor_file, result_tables


@pytest.fixture
def sensor():
    t = np.arange(12000) / 100
    rng = np.random.default_rng(42)
    data = {"time": t}
    for axis in "xyz":
        data[f"gyroscope_{axis}"] = 0.1 * np.sin(2 * np.pi * 5 * t) + rng.normal(0, 0.02, len(t))
    return pd.DataFrame(data)


@pytest.mark.parametrize("suffix", ["csv", "parquet", "pkl"])
def test_loading(tmp_path, sensor, suffix):
    path = tmp_path / f"sensor.{suffix}"
    {
        "csv": lambda: sensor.to_csv(path, index=False),
        "parquet": lambda: sensor.to_parquet(path),
        "pkl": lambda: sensor.to_pickle(path),
    }[suffix]()
    pd.testing.assert_frame_equal(
        load_sensor_file(path, allow_pickle=suffix == "pkl"), sensor, check_exact=False
    )


def test_real_tremor_pipeline(tmp_path, sensor):
    path = tmp_path / "sensor.csv"
    sensor.to_csv(path, index=False)
    results = analyze(
        load_sensor_file(path),
        pipelines=["tremor"],
        skip_preparation=False,
        output_dir=tmp_path / "pipeline",
    )
    assert results["errors"] == []
    tables = result_tables(results)
    quantification = tables["quantifications/tremor"]
    assert len(quantification) > 0
    assert "tremor_power" in quantification.columns
    classified = results["classifications"]["tremor"]
    assert len(classified) > 0 and "time" in classified
    assert any(str(column).startswith("pred_") for column in classified)
    output = tmp_path / "results.json"
    export_results(output, results, {"source": path.name})
    saved = json.loads(output.read_text())
    assert saved["results"]["errors"] == []
    assert len(saved["results"]["quantifications"]["tremor"]["data"]) == len(quantification)


def test_missing_channels(sensor):
    with pytest.raises(ValueError, match="Missing sensor columns"):
        analyze(sensor, pipelines=["gait"])


def test_combined_workflows_retain_success_when_other_group_lacks_channels(sensor, tmp_path):
    result = analyze(sensor, pipelines=["tremor", "pulse_rate"], output_dir=tmp_path)
    assert not result["quantifications"]["tremor"].empty
    assert not result["classifications"]["tremor"].empty
    assert len(result["errors"]) == 1
    assert result["errors"][0]["pipelines"] == ["pulse_rate"]
    assert "Missing sensor columns" in result["errors"][0]["error"]
    assert result["metadata"]["desktop_preparation"]["analysis_groups"] == [
        ["tremor"],
        ["pulse_rate"],
    ]


def test_duplicate_time(sensor):
    sensor.loc[1, "time"] = 0
    with pytest.raises(ValueError, match="strictly increasing"):
        analyze(sensor, pipelines=["tremor"])


def test_nested_gait_results():
    frame = pd.DataFrame({"time": [1], "range_of_motion": [20]})
    tables = result_tables(
        {
            "quantifications": {"gait": {"filtered": frame, "unfiltered": frame}},
            "aggregations": {"gait": {"filtered": {"median": 20}}},
        }
    )
    assert "quantifications/gait/filtered" in tables
    assert "quantifications/gait/unfiltered" in tables
    assert tables["aggregations/gait/filtered"].iloc[0]["value"] == 20


def test_real_gait_pipeline(tmp_path, sensor):
    for axis in "xyz":
        sensor[f"accelerometer_{axis}"] = (1 if axis == "z" else 0) + 0.1 * np.sin(
            2 * np.pi * 1.5 * sensor["time"]
        )
    result = analyze(sensor, pipelines=["gait"], watch_side="left", output_dir=tmp_path)
    assert result["errors"] == []
    assert set(result["quantifications"]["gait"]) == {"filtered", "unfiltered"}
    assert isinstance(result["quantifications"]["gait"]["unfiltered"], pd.DataFrame)
    assert not result["classifications"]["gait"]["detection"].empty


def test_real_pulse_rate_rejects_synthetic_signal(tmp_path):
    t = np.arange(3600) / 30
    frame = pd.DataFrame(
        {
            "time": t,
            "green": np.sin(2 * np.pi * 1.2 * t),
            "accelerometer_x": np.sin(t) * 0.01,
            "accelerometer_y": np.cos(t) * 0.01,
            "accelerometer_z": np.ones(len(t)),
        }
    )
    result = analyze(frame, pipelines=["pulse_rate"], output_dir=tmp_path)
    assert result["errors"] == []
    # A pure sine wave is not a physiological PPG recording: the quality
    # classifier rejects it. Exercise the real pipeline and preserve this outcome.
    assert result["quantifications"]["pulse_rate"].empty
    assert result["aggregations"]["pulse_rate"] == {}
    assert not result["classifications"]["pulse_rate"].empty
