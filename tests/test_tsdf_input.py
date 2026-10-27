"""TSDF decoding follows its documented channel-wise physical scaling."""

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from paradigma.load import load_tsdf_data

from paradigma_studio.core import load_sensor_file
from paradigma_studio.recordings import load_recordings
from paradigma_studio.tsdf_input import _scale_stream


@pytest.fixture
def stored_samples():
    return pd.DataFrame(
        {
            "time": [0, 10, 20],
            "gyroscope_x": [32000, -32000, 123],
            "gyroscope_y": [200, -100, 300],
            "gyroscope_z": [-10, 20, 30],
        }
    ).astype("int16")


def test_tsdf_scaling_matches_documented_reference_and_preserves_files(tsdf_writer, stored_samples):
    path = tsdf_writer(
        stored_samples, scale_factors=[2, 0.01, -0.5], time_scale_factors=[0.001], dtype="int16"
    )
    files = {file: hashlib.sha256(file.read_bytes()).digest() for file in path.parent.iterdir()}
    raw, time_metadata, value_metadata = load_tsdf_data(path.parent, "IMU")
    # Independent TSDF tutorial operation, including timestamp-stream scaling.
    expected = raw.astype(float).multiply(
        pd.Series(
            dict(zip(time_metadata.channels, time_metadata.scale_factors, strict=True))
        ).combine_first(
            pd.Series(dict(zip(value_metadata.channels, value_metadata.scale_factors, strict=True)))
        ),
        axis="columns",
    )[raw.columns]
    loaded = load_sensor_file(path)
    pd.testing.assert_frame_equal(loaded, expected)
    pd.testing.assert_frame_equal(raw, stored_samples)  # Upstream returns stored counts.
    assert loaded.attrs["desktop_recording_start"] == "2026-10-13 10:00:00+00:00"
    assert files == {file: hashlib.sha256(file.read_bytes()).digest() for file in files}
    _, recordings = load_recordings([path])
    pd.testing.assert_frame_equal(recordings["recording_001"], expected)


@pytest.mark.parametrize("factors", [(), [], [1, 1, 1]])
def test_tsdf_unscaled_streams_remain_unchanged(tsdf_writer, stored_samples, factors):
    path = tsdf_writer(stored_samples, scale_factors=factors, dtype="int16")
    pd.testing.assert_frame_equal(load_sensor_file(path), stored_samples)


@pytest.mark.parametrize(
    "factors",
    [
        None,
        0.1,
        [0.1, 0.2],
        [0.1, True, 0.3],
        ["0.1", 0.2, 0.3],
        [np.nan, 0.2, 0.3],
        [np.inf, 0.2, 0.3],
    ],
)
@pytest.mark.parametrize("stream", ["time", "values"])
def test_tsdf_rejects_invalid_scale_metadata(tsdf_writer, stored_samples, factors, stream):
    path = tsdf_writer(
        stored_samples,
        **{f"{stream}_scale_factors" if stream == "time" else "scale_factors": factors},
    )
    with pytest.raises(ValueError, match="TSDF scale_factors"):
        load_sensor_file(path)


def test_data_graphs_display_scaled_values(tsdf_writer, stored_samples, window):
    path = tsdf_writer(stored_samples, scale_factors=[0.1, 0.01, 0.5], dtype="int16")
    frame = load_sensor_file(path)
    window.loaded((str(path), frame))
    window.set_input_channels(["gyroscope_x", "gyroscope_y"])
    lines = window.data_figure.axes[0].lines
    assert [line.get_label() for line in lines] == ["gyroscope_x", "gyroscope_y"]
    for line in lines:
        scale = 0.1 if line.get_label() == "gyroscope_x" else 0.01
        np.testing.assert_allclose(line.get_ydata(), stored_samples[line.get_label()] * scale)
        np.testing.assert_array_equal(line.get_xdata(), stored_samples.time)


def test_difference_ms_tsdf_graph_shows_one_minute_as_sixty_seconds(tsdf_writer, window):
    time = np.full(6001, 20, dtype="int16")
    time[0] = 0
    raw = pd.DataFrame({"time": time, "gyroscope_x": np.arange(len(time), dtype="int16")})
    path = tsdf_writer(raw, time_scale_factors=[0.5], dtype="int16")
    metadata = json.loads(path.read_text())
    for stream in metadata["datasets"]:
        if stream["channels"] == ["time"]:
            stream["units"] = ["difference_ms"]
    path.write_text(json.dumps(metadata))
    frame = load_sensor_file(path)
    original = frame.copy(deep=True)
    window.loaded((str(path), frame))
    assert window.data_time_unit.currentText() == window.time.currentText() == "difference_ms"
    window.set_input_channels(["gyroscope_x"])
    axes = window.data_figure.axes[0]
    window.data_canvas.draw()
    np.testing.assert_allclose(axes.lines[0].time_index.coordinates, np.arange(6001) / 100)
    assert axes.get_xlabel() == "Elapsed time (s)"
    assert frame.time.iloc[1] == 10
    pd.testing.assert_frame_equal(window.input_table.model().frame, original)
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("dtype", ["int16", "int64", "float32", "float64"])
def test_tsdf_loaded_data_is_exactly_equal_to_previous_scaling(tsdf_writer, dtype):
    samples = pd.DataFrame(
        {
            "time": [0, 10, 20, 30],
            "gyroscope_x": [32767, -32768, 123, 0],
            "gyroscope_y": [-4, 3, -2, 1],
            "gyroscope_z": [1, 2, 3, 4],
        }
    )
    if dtype == "int64":
        samples["gyroscope_x"] = [2**63 - 1, -(2**63), 2**53 + 1, 0]
    if dtype.startswith("float"):
        samples["gyroscope_x"] = [-0.0, np.nan, np.inf, -np.inf]
    factors = [0.1, -0.5, 1]
    path = tsdf_writer(samples, dtype=dtype, scale_factors=factors, time_scale_factors=[0.001])
    hashes = {file: hashlib.sha256(file.read_bytes()).digest() for file in path.parent.iterdir()}
    expected, time_metadata, value_metadata = load_tsdf_data(path.parent, "IMU")
    for metadata in (time_metadata, value_metadata):
        for channel, factor in zip(metadata.channels, metadata.scale_factors, strict=True):
            if factor != 1:
                expected[channel] = expected[channel].astype(float) * factor
    loaded = load_sensor_file(path)
    pd.testing.assert_frame_equal(loaded, expected, check_exact=True)
    for column in ("time", "gyroscope_x", "gyroscope_y"):
        np.testing.assert_array_equal(
            loaded[column].to_numpy().view("uint64"), expected[column].to_numpy().view("uint64")
        )
    assert loaded.attrs["desktop_recording_start"] == "2026-10-13 10:00:00+00:00"
    assert hashes == {file: hashlib.sha256(file.read_bytes()).digest() for file in hashes}


@pytest.mark.parametrize("dtype", ["int16", "int64", "uint64", "float32", "float64", ">i2", ">f8"])
def test_scaling_preserves_shared_read_only_counts_and_float_bit_patterns(dtype):
    observations = [0, 1, 2, 32767] if "u" in dtype else [0, 1, -2, -32768]
    if dtype == "uint64":
        observations = [0, 2**53 + 1, 2**63 + 1, 2**64 - 1]
    if "f" in dtype:
        observations = [-0.0, np.nan, np.inf, -np.inf]
    source = np.asarray(observations, dtype=dtype)
    source.flags.writeable = False
    stored_bytes = source.tobytes()
    for factor in (0.1, -0.5, 2, -0.0, 1e300):
        frame = pd.DataFrame({"sensor": source}, copy=False)
        alias = frame.copy(deep=False)
        expected = frame.sensor.astype(float) * factor
        with np.errstate(all="raise"):
            _scale_stream(frame, SimpleNamespace(channels=["sensor"], scale_factors=[factor]))
        pd.testing.assert_series_equal(frame.sensor, expected, check_exact=True)
        np.testing.assert_array_equal(
            frame.sensor.to_numpy().view("uint64"), expected.to_numpy().view("uint64")
        )
        assert source.tobytes() == stored_bytes
        assert alias.sensor.to_numpy().tobytes() == stored_bytes
