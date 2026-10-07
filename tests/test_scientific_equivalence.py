"""Numerical wrapper/reference comparisons, adapted from ParaDigMa's tests.

Upstream test authors: ParaDigMa contributors (Apache-2.0). The synthetic
generators are adapted with a fixed random seed; fixtures and exact source
revision are described in data/paradigma/README.md. Scientific functions are
never stubbed: observers call the originals and return their outputs unchanged.
"""
from copy import deepcopy
from functools import wraps
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
import hashlib
import json
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication

from paradigma.config import PulseRateConfig
from paradigma.orchestrator import run_paradigma
from paradigma.pipelines import gait_pipeline, pulse_rate_pipeline, tremor_pipeline
from paradigma.prepare_data import correct_watch_orientation, prepare_raw_data

from paradigma_desktop.app import MainWindow
from paradigma_desktop.core import analyze, export_results, export_table_csv, load_sensor_file
from paradigma_desktop.history import load_result_export


pytestmark = pytest.mark.scientific
DATA = Path(__file__).parent / "data" / "paradigma"
# Independent calls in the same process should agree much more closely than
# upstream's historical rtol=1e-5 / atol=1e-6 stored-reference comparisons.
RTOL, ATOL = 1e-10, 1e-12


def assert_equivalent(actual, expected, path="results", *, roundtrip=False):
    """Check the whole tree, including schema, row order and missingness.

    Discrete labels/identifiers and timestamps are exact. JSON intentionally
    converts non-finite scalars to null and dictionary keys to strings.
    """
    if isinstance(expected, pd.DataFrame):
        assert isinstance(actual, pd.DataFrame), path
        # JSON retains column labels, but not pandas' empty RangeIndex type.
        pd.testing.assert_index_equal(actual.columns, expected.columns, exact=not roundtrip, obj=path)
        assert actual.shape == expected.shape, path
        pd.testing.assert_index_equal(actual.index, expected.index, obj=path)
        for column in expected:
            left, right = actual[column], expected[column]
            pd.testing.assert_series_equal(left.isna(), right.isna(), obj=f"{path}/{column} missingness")
            discrete = (column == "time" or str(column).endswith(("_nr", "_id"))
                        or (str(column).startswith("pred_") and not str(column).endswith("_proba"))
                        or not pd.api.types.is_float_dtype(right.dtype))
            pd.testing.assert_series_equal(left, right, check_dtype=False,
                check_exact=discrete, rtol=RTOL, atol=ATOL, obj=f"{path}/{column}")
    elif isinstance(expected, dict):
        assert isinstance(actual, dict), path
        right = {str(k): v for k, v in expected.items()} if roundtrip else expected
        assert actual.keys() == right.keys(), f"{path}: different keys"
        for key in right:
            assert_equivalent(actual[key], right[key], f"{path}/{key}", roundtrip=roundtrip)
    elif isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple)) and len(actual) == len(expected), path
        for i, (left, right) in enumerate(zip(actual, expected)):
            assert_equivalent(left, right, f"{path}/{i}", roundtrip=roundtrip)
    elif isinstance(expected, np.ndarray):
        assert isinstance(actual, np.ndarray) and actual.shape == expected.shape, path
        if np.issubdtype(expected.dtype, np.floating):
            np.testing.assert_allclose(actual, expected, rtol=RTOL, atol=ATOL, equal_nan=True, err_msg=path)
        else:
            np.testing.assert_array_equal(actual, expected, err_msg=path)
    elif isinstance(expected, (float, np.floating)):
        if roundtrip and not np.isfinite(expected):
            assert actual is None, path
        else:
            np.testing.assert_allclose(actual, expected, rtol=RTOL, atol=ATOL, equal_nan=True, err_msg=path)
    else:
        assert actual == expected, path


def observe_stages(operation):
    """Observe real preprocessing, features, probabilities and labels.

    ParaDigMa 1.1.2's orchestrator does not forward pipeline classification
    tables. Observe those stages in both runs without changing what executes
    or requesting extra pipeline steps. Quantification inputs include the
    actual merged gait labels, which the gait pipeline also does not return.
    """
    stages = []
    functions = {
        gait_pipeline: ("preprocess_imu_data", "extract_gait_features", "detect_gait",
                        "extract_arm_activity_features", "filter_gait", "quantify_arm_swing"),
        tremor_pipeline: ("preprocess_imu_data", "extract_tremor_features", "detect_tremor"),
        pulse_rate_pipeline: ("preprocess_ppg_data", "extract_signal_quality_features",
                              "signal_quality_classification", "estimate_pulse_rate"),
    }

    def observer(original, name):
        @wraps(original)
        def call(*args, **kwargs):
            # Only record tabular/array arguments, not mutable configuration
            # objects or classifier packages. Copy before upstream can mutate.
            inputs = [deepcopy(arg) for arg in args if isinstance(arg, (pd.DataFrame, np.ndarray))]
            inputs += [deepcopy(value) for value in kwargs.values()
                       if isinstance(value, (pd.DataFrame, np.ndarray))]
            result = original(*args, **kwargs)
            stages.append({"stage": name, "inputs": inputs, "output": deepcopy(result)})
            return result
        return call

    with pytest.MonkeyPatch.context() as patch:
        for module, names in functions.items():
            for name in names:
                patch.setattr(module, name, observer(getattr(module, name), f"{module.__name__}/{name}"))
        result = operation()
    return result, stages


def official_preparation(frame, **settings):
    """Independent documented official preparation; never call app helpers."""
    prepared = prepare_raw_data(frame.copy(),
        column_mapping=settings.get("column_mapping"),
        accelerometer_units=settings.get("accelerometer_units", "g"),
        gyroscope_units=settings.get("gyroscope_units", "deg/s"),
        time_input_unit=settings.get("time_input_unit", "relative_s"),
        device_orientation=None)
    for sensor in ("accelerometer", "gyroscope"):
        if all(f"{sensor}_{axis}" in prepared for axis in "xyz"):
            prepared = correct_watch_orientation(prepared,
                device_orientation=settings.get("device_orientation", ["x", "y", "z"]), sensor=sensor)
    return prepared


def compare_workflows(frame, reference_input, pipelines, directory, **settings):
    """Separate direct official run and real desktop run with fresh configs."""
    original = frame.copy(deep=True)
    reference_original = deepcopy(reference_input)
    reference_settings = {key: deepcopy(value) for key, value in settings.items()
                          if key not in {"column_mapping", "drop_missing_samples", "output_dir",
                                         "skip_preparation", "split_by_gaps"}}
    expected, reference_stages = observe_stages(lambda: run_paradigma(
        dfs=deepcopy(reference_input), pipelines=pipelines, skip_preparation=True,
        split_by_gaps=False, save_intermediate=["classification"],
        return_intermediate=["classification", "quantification"],
        output_dir=directory / "official", custom_logger=logging.Logger("official-reference", logging.INFO),
        **reference_settings))
    # Read the independently generated official classification files. The
    # reference does not use the desktop's classification-retention helper.
    expected["classifications"] = {}
    names = {"gait": {"detection": "gait_predictions.parquet", "arm_activity": "arm_activity_predictions.parquet"},
             "tremor": {"": "tremor_predictions.parquet"}, "pulse_rate": {"": "ppg_quality_predictions.parquet"}}
    file_keys = list(reference_input) if isinstance(reference_input, dict) else ["df_1"]
    for pipeline in pipelines:
        for stage, filename in names[pipeline].items():
            frames = []
            for key in file_keys:
                exported = directory / "official" / "individual_files" / key / "classification" / filename
                if exported.exists():
                    frame_out = pd.read_parquet(exported)
                    if len(file_keys) > 1:
                        frame_out["file_key"] = key
                    frames.append(frame_out)
            if frames:
                joined = pd.concat(frames, ignore_index=True)
                if stage:
                    expected["classifications"].setdefault(pipeline, {})[stage] = joined
                else:
                    expected["classifications"][pipeline] = joined
    actual, app_stages = observe_stages(lambda: analyze(frame, pipelines=pipelines,
        output_dir=directory / "desktop", **deepcopy(settings)))
    assert expected["errors"] == [], "Reference must complete successfully, not merely fail identically"
    assert actual["errors"] == []
    assert reference_stages, "The real scientific pipeline must execute"
    assert_equivalent(app_stages, reference_stages, "intermediate stages")
    for name in ("quantifications", "aggregations", "classifications", "errors"):
        assert_equivalent(actual[name], expected[name], name)
    metadata = {key: value for key, value in actual["metadata"].items() if key != "desktop_preparation"}
    assert_equivalent(metadata, expected["metadata"], "scientific metadata")
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert_equivalent(reference_input, reference_original, "unchanged reference input")
    return actual, expected, reference_stages


def upstream_synthetic(pipeline):
    """Adapt official create_test_*_data with seed 42 (100 Hz IMU / 50 Hz PPG)."""
    rng = np.random.default_rng(42)
    rate = 50 if pipeline == "pulse_rate" else 100
    t = np.linspace(0, 120, 120 * rate)
    data = {"time": t}
    if pipeline == "pulse_rate":
        data["green"] = np.sin(2 * np.pi * (70 / 60) * t) + .1 * rng.random(len(t))
        data.update(accelerometer_x=.1 * rng.random(len(t)),
                    accelerometer_y=.1 * rng.random(len(t)),
                    accelerometer_z=9.8 + .1 * rng.random(len(t)))
    else:
        frequency = 5 if pipeline == "tremor" else 2
        data.update(gyroscope_x=.1 * np.sin(2 * np.pi * frequency * t) + .05 * rng.random(len(t)),
                    gyroscope_y=.1 * np.cos(2 * np.pi * frequency * t) + .05 * rng.random(len(t)),
                    gyroscope_z=.05 * rng.random(len(t)))
        if pipeline == "gait":
            data.update(accelerometer_x=.2 * np.sin(2 * np.pi * 1.5 * t) + .1 * rng.random(len(t)),
                        accelerometer_y=.2 * np.cos(2 * np.pi * 1.5 * t) + .1 * rng.random(len(t)),
                        accelerometer_z=9.8 + .2 * rng.random(len(t)))
    return pd.DataFrame(data)


def test_reference_fixture_integrity_and_toolbox_version():
    manifest = json.loads((DATA / "manifest.json").read_text())
    assert version("paradigma") == manifest["paradigma_version"], "Review scientific references when changing ParaDigMa"
    for name, specification in manifest["fixtures"].items():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == specification["sha256"]
        assert len(pd.read_parquet(DATA / name)) == specification["rows"]


@pytest.mark.parametrize("pipeline", ["gait", "tremor", "pulse_rate"])
def test_upstream_synthetic_pipeline_equivalence(pipeline, tmp_path):
    frame = upstream_synthetic(pipeline)
    compare_workflows(frame, frame, [pipeline], tmp_path, skip_preparation=True, watch_side="left")


def test_all_three_modules_equal_independent_official_workflows(tmp_path):
    frame = upstream_synthetic("gait")
    frame["green"] = np.sin(2 * np.pi * (70 / 60) * frame.time)
    original = frame.copy(deep=True)
    expected = {key: {} for key in ("quantifications", "classifications", "aggregations", "metadata")}
    stages = []
    for index, group in enumerate((["gait", "tremor"], ["pulse_rate"])):
        _, reference, reference_stages = compare_workflows(frame, frame, group,
            tmp_path / str(index), skip_preparation=True, watch_side="left")
        for key in expected:
            expected[key].update(reference[key])
        stages.extend(reference_stages)
    actual, actual_stages = observe_stages(lambda: analyze(frame,
        pipelines=["gait", "tremor", "pulse_rate"], skip_preparation=True, watch_side="left",
        output_dir=tmp_path / "combined"))
    assert actual["errors"] == []
    assert_equivalent(actual_stages, stages, "combined scientific stages")
    for key in ("quantifications", "classifications", "aggregations"):
        assert_equivalent(actual[key], expected[key], key)
    assert_equivalent({k: v for k, v in actual["metadata"].items() if k != "desktop_preparation"},
                      expected["metadata"], "combined scientific metadata")
    assert actual["metadata"]["desktop_preparation"]["analysis_groups"] == [["gait", "tremor"], ["pulse_rate"]]
    pd.testing.assert_frame_equal(frame, original, check_exact=True)


@pytest.fixture(scope="module", params=["left", "right"])
def recorded_results(request, tmp_path_factory):
    frame = pd.read_parquet(DATA / "prepared_imu.parquet")
    actual, expected, stages = compare_workflows(frame, frame, ["gait", "tremor"],
        tmp_path_factory.mktemp(f"scientific-{request.param}"), skip_preparation=True, watch_side=request.param)
    return actual, expected, stages, request.param


def test_recorded_gait_and_tremor_outputs_are_numerically_equivalent(recorded_results):
    actual, expected, stages, side = recorded_results
    assert not expected["quantifications"]["gait"]["unfiltered"].empty
    assert expected["quantifications"]["tremor"]["pred_tremor_checked"].sum() > 1
    assert expected["quantifications"]["tremor"]["tremor_power"].notna().sum() > 1
    assert expected["aggregations"]["gait"]["unfiltered"]
    assert expected["aggregations"]["tremor"]
    # Right-side orientation provides positive clean-gait coverage as well as
    # the left-side fixture's legitimate empty filtered branch.
    if side == "right":
        assert not expected["quantifications"]["gait"]["filtered"].empty
        assert expected["aggregations"]["gait"]["filtered"]
    for name in ("detect_gait", "filter_gait", "detect_tremor"):
        assert any(stage["stage"].endswith("/" + name) for stage in stages)


@pytest.mark.parametrize("time_unit", ["relative_s", "relative_ms", "absolute_s", "absolute_ms",
                                       "difference_s", "difference_ms"])
def test_raw_units_orientation_mapping_and_time_equivalence(time_unit, tmp_path):
    frame = upstream_synthetic("gait")
    times = frame.time.to_numpy().copy()
    encodings = {"relative_s": times, "relative_ms": times * 1000,
                 "absolute_s": 1_700_000_000 + times, "absolute_ms": 1_700_000_000_000 + times * 1000,
                 "difference_s": np.r_[0., np.diff(times)], "difference_ms": np.r_[0., np.diff(times)] * 1000}
    frame["time"] = encodings[time_unit]
    for axis in "xyz":
        frame[f"gyroscope_{axis}"] *= np.pi / 180  # Express the original signal in radians/s.
    names = {column: f"device_{column}" for column in frame}
    frame = frame.rename(columns=names)
    settings = dict(column_mapping={value: key for key, value in names.items()},
                    accelerometer_units="m/s^2", gyroscope_units="rad/s",
                    device_orientation=["-y", "x", "z"], time_input_unit=time_unit)
    prepared = official_preparation(frame, **settings)
    compare_workflows(frame, prepared, ["tremor"], tmp_path, **settings)


@pytest.mark.parametrize("side", ["left", "right"])
def test_official_cwa_loading_preparation_and_gait_equivalence(side, tmp_path):
    frame = load_sensor_file(files("paradigma_desktop") / "data" / "test_data.CWA")
    prepared = official_preparation(frame)
    actual, expected, _ = compare_workflows(frame, prepared, ["gait"], tmp_path, watch_side=side)
    assert not expected["quantifications"]["gait"]["unfiltered"].empty


@pytest.mark.parametrize("minimum,time_unit", [(1.5, "relative_s"), (30., "relative_s"),
                                                (1.5, "difference_ms")])
def test_physilog_exclusion_and_gap_equivalence(minimum, time_unit, tmp_path):
    frame = load_sensor_file(files("paradigma_desktop") / "data" / "physilog_excerpt.parquet")
    # Independently known raw-row intervals: missing gyro rows [2000,2010),
    # time gaps at rows 6010 and 8010. Explicit slices avoid reimplementing
    # the desktop boundary detection as the reference.
    ranges = [(0, 2000), (2010, 6010), (6010, 8010), (8010, 12010)]
    if minimum == 30:
        ranges = [ranges[1], ranges[3]]  # Discard the two 20-second sections.
    if time_unit == "difference_ms":
        times = frame.time.to_numpy().copy()
        frame["time"] = np.r_[0., np.diff(times)] * 1000
        reference_frame = frame.copy()
        reference_frame["time"] = np.cumsum(frame.time.to_numpy()) / 1000
    else:
        reference_frame = frame
    sections = {}
    for i, (start, stop) in enumerate(ranges, 1):
        section = official_preparation(reference_frame.iloc[start:stop].reset_index(drop=True))
        section["data_segment_nr"] = i
        sections[f"segment_{i}"] = section
    actual, expected, stages = compare_workflows(frame, sections, ["gait"], tmp_path,
        watch_side="left", drop_missing_samples=True, split_by_gaps=True,
        min_segment_seconds=minimum, max_gap_seconds=1.5, time_input_unit=time_unit)
    details = actual["metadata"]["desktop_preparation"]
    assert details["excluded_samples"] == 10
    assert details["continuous_sections"] == len(ranges)
    assert details["analyzed_samples"] == sum(stop - start for start, stop in ranges)
    assert not expected["quantifications"]["gait"]["unfiltered"].empty
    assert set(expected["quantifications"]["gait"]["unfiltered"]["file_key"]) <= set(sections)
    # Sections with no detected gait legitimately contribute no output rows.
    assert sum(stage["stage"].endswith("gait_pipeline/preprocess_imu_data")
               for stage in stages) == len(sections)


@pytest.mark.parametrize("configured", [False, True], ids=["official-defaults", "explicit-100hz-10s"])
def test_recorded_ppg_quality_and_pulse_rate_equivalence(configured, tmp_path):
    frame = pd.read_parquet(DATA / "prepared_ppg.parquet")
    settings = {"pulse_rate_config": PulseRateConfig(ppg_sampling_frequency=100, min_window_length_s=10)} if configured else {}
    actual, expected, stages = compare_workflows(frame, frame, ["pulse_rate"], tmp_path,
        skip_preparation=True, **settings)
    classification = next(stage["output"] for stage in stages
                          if stage["stage"].endswith("/signal_quality_classification"))
    assert not classification.empty
    if configured:
        assert not expected["quantifications"]["pulse_rate"].empty
        assert np.isfinite(expected["quantifications"]["pulse_rate"]["pulse_rate"]).all()
        assert expected["aggregations"]["pulse_rate"]
    else:
        assert expected["quantifications"]["pulse_rate"].empty
        assert expected["aggregations"]["pulse_rate"] == {}
    path = tmp_path / "pulse-results.json"
    export_results(path, actual, {"paradigma_version": version("paradigma")})
    _, restored = load_result_export(path)
    assert_equivalent(restored, expected, "PPG JSON round trip", roundtrip=True)


def test_real_results_json_and_csv_preserve_official_values(recorded_results, tmp_path):
    actual, expected, _, _ = recorded_results
    path = tmp_path / "results.json"
    export_results(path, actual, {"paradigma_version": version("paradigma")})
    provenance, restored = load_result_export(path)
    assert provenance["paradigma_version"] == "1.1.2"
    assert_equivalent(restored, expected, "JSON round trip", roundtrip=True)
    for branch, frame in expected["quantifications"]["gait"].items():
        path = tmp_path / f"gait-{branch}.csv"
        export_table_csv(path, actual["quantifications"]["gait"][branch])
        # round_trip prevents pandas' default parser introducing float changes.
        assert_equivalent(pd.read_csv(path, float_precision="round_trip"), frame, f"CSV/{branch}")
    path = tmp_path / "tremor.csv"
    export_table_csv(path, actual["quantifications"]["tremor"])
    assert_equivalent(pd.read_csv(path, float_precision="round_trip"),
                      expected["quantifications"]["tremor"], "CSV/tremor")


def test_real_result_filters_graphs_and_tables_preserve_official_values(recorded_results, tmp_path):
    actual, expected, _, _ = recorded_results
    originals = deepcopy(actual)
    application = QApplication.instance() or QApplication([])
    window = MainWindow(history_dir=tmp_path / "runs")
    try:
        window.analyzed(actual)
        window.dataset.setCurrentText("quantifications/gait/unfiltered")
        window.y_column.setCurrentText("range_of_motion")
        reference = expected["quantifications"]["gait"]["unfiltered"]
        reference_times = np.full(len(reference), np.nan)
        for number, rows in reference.groupby("gait_segment_nr", sort=False).indices.items():
            meta = expected["metadata"]["gait"]["unfiltered"]["per_segment"][number]
            reference_times[rows] = float(meta["start_s"]) + (np.arange(len(rows)) + .5) / len(rows) * (float(meta["end_s"]) - float(meta["start_s"]))
        low = float(np.nanmedian(reference_times))
        window.time_from.setText(repr(low))
        window.apply_filters()
        positions = np.flatnonzero(reference_times >= low)
        selected = reference.iloc[positions]
        assert len(selected) > 0 and len(selected) < len(reference)
        np.testing.assert_array_equal(window.active_positions, positions)
        assert_equivalent(window.result_table.model().frame[selected.columns], selected, "visible scientific table columns")
        axes = next(ax for ax in window.figure.axes if ax._paradigma_dataset == "quantifications/gait/unfiltered")
        line = axes.lines[0]
        # Positions are estimates for presentation, computed before filtering
        # from independent official segment metadata; measurements stay exact.
        np.testing.assert_allclose(line.get_xdata(), reference_times[positions], rtol=RTOL, atol=ATOL)
        np.testing.assert_array_equal(line.get_ydata(), selected.range_of_motion.to_numpy())
        for key, value in expected["aggregations"]["gait"]["unfiltered"].items():
            if isinstance(value, (int, float)):
                shown = window.overview_values[("gait", "Aggregates", ("unfiltered", key))]
                assert float(shown.toolTip()) == value
        window.reset_filters()
        assert_equivalent(window.active_frame, reference, "reset selection")
        assert_equivalent(actual, originals, "unaltered scientific results")
    finally:
        window.close()
        application.processEvents()
