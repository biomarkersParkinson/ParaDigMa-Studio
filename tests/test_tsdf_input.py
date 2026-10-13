"""TSDF decoding follows its documented channel-wise physical scaling."""

import hashlib

import numpy as np
import pandas as pd
import pytest
from paradigma.load import load_tsdf_data

from paradigma_studio.core import load_sensor_file
from paradigma_studio.recordings import load_recordings


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
