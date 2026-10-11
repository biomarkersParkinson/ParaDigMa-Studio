"""Readable recording dates and times across zoom and date boundaries."""

import numpy as np
import pandas as pd
from matplotlib import dates
from matplotlib.figure import Figure

from paradigma_studio.plotting import time_coordinates
from paradigma_studio.time_axis import RecordingTimeFormatter


def test_time_formatter_separates_time_date_at_midnight_and_keeps_date_when_zoomed():
    figure = Figure()
    axis = figure.add_subplot()
    values = dates.date2num(
        pd.to_datetime(["2026-10-07T23:59:55Z", "2026-10-08T00:00:00Z", "2026-10-08T00:00:05Z"])
    )
    axis.set_xlim(values[0], values[-1])
    formatter = RecordingTimeFormatter("UTC")
    axis.xaxis.set_major_formatter(formatter)
    formatter.set_locs(values)
    assert formatter(values[0]) == "23:59:55\n07 Oct 2026"
    assert formatter(values[1]) == "00:00:00\n08 Oct 2026"
    assert formatter(values[2]) == "00:00:05\n"
    axis.set_xlim(values[1], values[2])
    formatter.set_locs(values)
    assert formatter(values[1]).endswith("08 Oct 2026")
    fine = dates.date2num(pd.date_range("2026-10-07T12:00:00Z", periods=7, freq="500ms"))
    axis.set_xlim(fine[0], fine[-1])
    formatter.set_locs(fine)
    assert formatter(fine[0]).startswith("12:00:00.000")
    assert formatter(fine[1]).startswith("12:00:00.500")


def test_vectorized_plot_dates_preserve_absolute_time_across_dst():
    timestamps = pd.date_range("2026-10-25T00:30:00Z", periods=5, freq="30min").tz_convert(
        "Europe/Amsterdam"
    )
    np.testing.assert_allclose(
        time_coordinates(timestamps), dates.date2num(timestamps.to_pydatetime()), atol=1e-12, rtol=0
    )
