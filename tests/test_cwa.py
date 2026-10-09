"""Regressions for NumPy 2 and real Axivity fractional timestamps."""

from importlib.resources import files

import numpy as np
import pandas as pd
import pytest
from openmovement.load import CwaData

from paradigma_desktop.core import analyze, load_sensor_file


def test_official_cwa_sample_loading_and_gait():
    source = files("paradigma_desktop") / "data" / "test_data.CWA"
    frame = load_sensor_file(source)
    assert len(frame) == 36400
    assert set(frame.columns) == {
        "time",
        "time_dt",
        *{f"accelerometer_{axis}" for axis in "xyz"},
        *{f"gyroscope_{axis}" for axis in "xyz"},
    }
    assert frame.time.iloc[0] == 0
    assert frame.time.iloc[-1] == pytest.approx(364.323670272, abs=1e-6)
    assert (np.diff(frame.time) > 0).all()
    assert np.median(np.diff(frame.time)) == pytest.approx(0.01, abs=2e-5)
    assert str(frame.time_dt.iloc[0]) == "2025-11-17 09:00:02.324188160"
    # Independently known raw counts and scales in the first AX6 sample.
    assert frame.loc[0, "accelerometer_x"] == pytest.approx(3431 / 4096)
    assert frame.loc[0, "gyroscope_x"] == pytest.approx(-196 / 32.768)
    results = analyze(frame, pipelines=["gait"], watch_side="left")
    assert results["errors"] == []
    gait = results["quantifications"]["gait"]["unfiltered"]
    assert not gait.empty
    assert {"gait_segment_nr", "range_of_motion", "peak_velocity"} <= set(gait.columns)
    assert np.isfinite(gait[["range_of_motion", "peak_velocity"]].to_numpy()).all()


@pytest.mark.parametrize("frequency", [100, 3200])
def test_fractional_timestamp_arithmetic_does_not_wrap(frequency):
    # Test the largest fraction and a negative offset. Multiplication in
    # uint16 could silently wrap even before the NumPy 2 division exception.
    recording = CwaData.__new__(CwaData)
    recording.verbose = False
    recording.data_format = {"deviceFractional": 0xFFFF, "frequency": frequency}
    packed = ((2025 - 2000) << 26) | (11 << 22) | (17 << 17) | (9 << 12) | 2
    recording.df = pd.DataFrame(
        {
            "device_fractional": np.array([0xFFFF, 0xC000], dtype=np.uint16),
            "timestamp_packed": np.array([packed, packed], dtype=np.uint32),
            "timestamp_offset": np.array([-72, -50], dtype=np.int16),
            "sample_index": [0, 40],
        }
    )
    recording._parse_times()
    fractions = [65534, 32768]
    expected_offsets = [
        offset + (fraction * frequency) // 65536 for offset, fraction in zip([-72, -50], fractions)
    ]
    assert recording.df.timestamp_offset.tolist() == expected_offsets
    np.testing.assert_allclose(
        recording.df.timestamp,
        [1763370002 + fraction / 65536 for fraction in fractions],
        rtol=0,
        atol=1e-7,
    )
    assert recording.df.timestamp_index.tolist() == [expected_offsets[0], 40 + expected_offsets[1]]
