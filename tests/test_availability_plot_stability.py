"""Input coverage must not change how already selected outcomes are displayed."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_desktop.app import MainWindow
from paradigma_desktop.plotting import time_coordinates
from paradigma_desktop.results_view import clock_times


@pytest.mark.parametrize("absolute", [False, True])
@pytest.mark.parametrize("zoomed, manual_y", [(False, False), (True, False), (True, True)])
def test_toggling_availability_keeps_outcome_values_timing_and_axes(
    tmp_path, absolute, zoomed, manual_y
):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.show()
    if absolute:
        window.provenance = {
            "display_clock": {
                "origin": "2026-10-07T12:00:00+02:00",
                "timezone": "Europe/Amsterdam",
                "source": "Test",
            }
        }
    frame = pd.DataFrame({"time": [4.0, 8.0, 12.0, 16.0], "tremor_power": [2.0, np.nan, 7.0, 40.0]})
    original = deepcopy(frame)
    window.analyzed(
        {
            "quantifications": {"tremor": frame},
            "metadata": {
                "desktop_availability": {
                    "tremor": {"df_1": {"samples": 4000, "intervals": [[0.0, 40.0]]}}
                }
            },
        }
    )
    window.result_tabs.setCurrentIndex(1)
    coverage = next(
        item
        for (name, metric), item in window._series_items.items()
        if name.startswith("preparation/")
    )
    coverage.setCheckState(0, Qt.Unchecked)
    app.processEvents()

    def outcome():
        return next(
            ax for ax in window.figure.axes if ax._paradigma_dataset == "quantifications/tremor"
        )

    if zoomed:
        limits = time_coordinates(clock_times([5.0, 14.0], window.display_clock))
        outcome().set_xlim(*limits)
    if manual_y:
        outcome().set_ylim(0.0, 50.0)
    app.processEvents()
    window.canvas.draw()
    limits, ylimits = outcome().get_xlim(), outcome().get_ylim()
    paths = [path.vertices.copy() for path in outcome().collections[0].get_paths()]
    try:
        for state in (Qt.Checked, Qt.Unchecked, Qt.Checked):
            coverage.setCheckState(0, state)
            app.processEvents()
            window.canvas.draw()
            assert outcome().get_xlim() == pytest.approx(limits, abs=1e-12)
            assert outcome().get_ylim() == pytest.approx(ylimits)
            np.testing.assert_array_equal(
                [path.vertices for path in outcome().collections[0].get_paths()], paths
            )
            pd.testing.assert_frame_equal(frame, original)
        # Home can still expose the full prepared input after retaining a zoom.
        window.plot_toolbar.home()
        app.processEvents()
        start, end = time_coordinates(clock_times([0.0, 40.0], window.display_clock))
        assert outcome().get_xlim()[0] <= start
        assert outcome().get_xlim()[1] >= end
        # Selecting coverage from an empty workspace starts with its full range.
        window.result_series.blockSignals(True)
        for item in window._series_items.values():
            item.setCheckState(0, Qt.Unchecked)
        window.result_series.blockSignals(False)
        window.plot()
        coverage.setCheckState(0, Qt.Checked)
        app.processEvents()
        assert window.figure.axes[0].get_xlim()[0] <= start
        assert window.figure.axes[0].get_xlim()[1] >= end
    finally:
        window.close()
        app.processEvents()
