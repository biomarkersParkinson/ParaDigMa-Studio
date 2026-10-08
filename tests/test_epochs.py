"""Graph-only epoch summaries preserve missingness, clocks and original outputs."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paradigma_desktop.app import MainWindow
from paradigma_desktop.epochs import epoch_phase, epoch_summary, availability_epoch_summary
from paradigma_desktop.results_view import clock_times


def test_continuous_epochs_use_medians_and_leave_missing_and_unobserved_bins_blank():
    times = np.array([0., 900., 1799., 1800., 1801., 3600., 7200., np.nan])
    values = np.array([1., 99., 10., np.nan, np.inf, 5., np.nan, 1000.])
    original = values.copy()
    summary = epoch_summary(times, values)
    np.testing.assert_array_equal(summary.start_s, [0, 1800, 3600, 7200])
    np.testing.assert_array_equal(summary.value, [10, np.nan, 5, np.nan])
    np.testing.assert_array_equal(summary.n_observations, [3, 0, 1, 0])
    np.testing.assert_array_equal(values, original)


@pytest.mark.parametrize('clock', [
    {'origin': '2026-10-08T10:07:15+02:00', 'timezone': 'Europe/Amsterdam'},
    {'origin': '2026-10-08T10:07:15+05:45', 'timezone': 'Asia/Kathmandu'},
    {'origin': '2026-10-08T10:07:15', 'timezone': None},
])
def test_binary_percentages_ignore_missing_observations_and_align_to_local_half_hours(clock):
    phase = epoch_phase(clock)
    assert phase == -435
    summary = epoch_summary([0, 1364, 1365, 1800, 2000, 2010],
                            [0, 1, 1, np.nan, np.inf, 2], binary=True, phase=phase)
    np.testing.assert_array_equal(summary.start_s, [-435, 1365])
    np.testing.assert_array_equal(summary.value, [50, 100])
    np.testing.assert_array_equal(summary.n_observations, [2, 1])
    assert clock_times(summary.start_s, clock).strftime('%H:%M:%S').tolist() == ['10:00:00', '10:30:00']


def test_dst_repeated_half_hours_remain_separate_epochs():
    clock = {'origin': '2026-10-25T02:45:00+02:00', 'timezone': 'Europe/Amsterdam'}
    summary = epoch_summary([0, 1800, 3600, 5400], [1, 2, 3, 4], phase=epoch_phase(clock))
    dates = clock_times(summary.start_s, clock)
    assert dates.strftime('%H:%M %Z').tolist() == ['02:30 CEST', '02:00 CET', '02:30 CET', '03:00 CET']
    np.testing.assert_array_equal(np.diff(summary.start_s), [1800, 1800, 1800])


@pytest.mark.parametrize('binary', [False, True])
def test_empty_epoch_outputs_remain_empty(binary):
    assert epoch_summary([], [], binary=binary).empty
    assert epoch_phase(None) == 0


def test_availability_unions_overlaps_and_splits_intervals_across_boundaries():
    summary = availability_epoch_summary([60, 1200, 1300, 3000, 3600],
                                          [600, 2000, 1900, 3600, 4000], bounds=(0, 5400))
    np.testing.assert_array_equal(summary.covered_s, [1140, 800, 400])
    np.testing.assert_allclose(summary.value, np.array([1140, 800, 400]) / 18)
    np.testing.assert_array_equal(summary.observed_s, [1800, 1800, 1800])


def test_availability_uses_partial_edge_spans_and_includes_known_empty_epochs():
    summary = availability_epoch_summary([900, 1800], [1500, 3000], bounds=(600, 3300))
    np.testing.assert_array_equal(summary.value, [50, 80])
    np.testing.assert_array_equal(summary.observed_s, [1200, 1500])
    summary = availability_epoch_summary([1800], [3600], bounds=(0, 5400))
    np.testing.assert_array_equal(summary.value, [0, 100, 0])
    summary = availability_epoch_summary([], [], bounds=(0, 3600))
    np.testing.assert_array_equal(summary.value, [0, 0])
    assert availability_epoch_summary([], []).empty


def test_long_availability_interval_covers_every_epoch_without_double_counting():
    summary = availability_epoch_summary([0, 900], [18000, 9000])
    assert len(summary) == 10
    np.testing.assert_array_equal(summary.value, np.full(10, 100.))


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.show()
    yield window
    window.close()
    app.processEvents()


def select_all(window):
    window.result_series.blockSignals(True)
    for item in window._series_items.values():
        item.setCheckState(0, Qt.Checked)
    window.result_series.blockSignals(False)
    window.plot()


def test_shared_view_switches_binary_continuous_probability_and_availability_and_keeps_raw_outputs(window):
    times = [10., 20., 1790., 1800., 1810., 4000.]
    output = {'classifications': {'tremor': pd.DataFrame({'time': times,
                    'pred_tremor_checked': [0, 1, 1, 0, 0, 1], 'pred_tremor_proba': [.1, .7, .9, .2, .4, .8]})},
              'quantifications': {'tremor': pd.DataFrame({'time': times, 'tremor_power': [1, 100, 5, 2, 8, 20]}),
                                  'pulse_rate': pd.DataFrame({'time': [0., 1800., 4000.], 'pulse_rate': [60., 80., 70.]})},
              'metadata': {'desktop_availability': {'tremor': {'df_1': {'intervals': [[0., 1800.], [3600., 4200.]]}}}}}
    original = deepcopy(output)
    window.analyzed(output)
    window.result_tabs.setCurrentIndex(1)
    select_all(window)
    chosen = window.selected_result_series()
    window.result_graph_view.setCurrentIndex(1)
    QApplication.instance().processEvents()
    axes = {(ax._paradigma_dataset, ax._paradigma_metric): ax for ax in window.figure.axes}
    assert all(ax._paradigma_epoch and ax._paradigma_bars for ax in axes.values())
    for key, ax in axes.items():
        assert ax.get_title(loc='left') == window._series_items[key].text(0)
        assert ax._left_title.get_bbox_patch() is not None
    assert len({ax.get_xlim() for ax in axes.values()}) == 1
    power = axes['quantifications/tremor', 'tremor_power']
    np.testing.assert_array_equal(power._paradigma_epoch_data.value, [5, 5, 20])
    np.testing.assert_allclose(axes['classifications/tremor', 'pred_tremor_checked']._paradigma_epoch_data.value,
                               [200 / 3, 0, 100])
    np.testing.assert_allclose(axes['classifications/tremor', 'pred_tremor_proba']._paradigma_epoch_data.value, [.7, .3, .8])
    np.testing.assert_array_equal(axes['quantifications/pulse_rate', 'pulse_rate']._paradigma_epoch_data.value, [60, 80, 70])
    coverage = next(ax for (name, metric), ax in axes.items() if name.startswith('preparation/'))
    np.testing.assert_array_equal(coverage._paradigma_epoch_data.value, [100, 0, 100])
    assert axes['classifications/tremor', 'pred_tremor_checked'].get_ylim() == (0, 100)
    # Selecting an aggregate bar links to an actual row; its marker uses the
    # aggregate height rather than the original value (100 versus median 5).
    window.graph_clicked(SimpleNamespace(inaxes=power, xdata=900.))
    assert window.result_table.currentIndex().row() == 1
    marker = next(artist for artist in window._result_selection_artists if artist.get_gid() == 'selected-result-point')
    assert marker.get_ydata()[0] == 5
    cached = power._paradigma_epoch_data
    coverage_key = next(key for key in window._series_items if key[0].startswith('preparation/'))
    window._series_items[coverage_key].setCheckState(0, Qt.Unchecked)
    power = next(ax for ax in window.figure.axes if ax._paradigma_dataset == 'quantifications/tremor')
    assert power._paradigma_epoch_data is cached
    window._series_items[coverage_key].setCheckState(0, Qt.Checked)
    window.result_graph_view.setCurrentIndex(0)
    assert window.selected_result_series() == chosen
    assert not any(ax._paradigma_epoch for ax in window.figure.axes)
    for ax in window.figure.axes:
        assert ax.get_title(loc='left') == window._series_items[ax._paradigma_dataset, ax._paradigma_metric].text(0)
    for stage in ('classifications', 'quantifications'):
        for module, frame in output[stage].items():
            pd.testing.assert_frame_equal(frame, original[stage][module], check_exact=True)
            pd.testing.assert_frame_equal(window.tables[f'{stage}/{module}'], frame, check_exact=True)
    window.result_graph_view.setCurrentIndex(1)
    assert next(ax for ax in window.figure.axes if ax._paradigma_dataset == 'quantifications/tremor')._paradigma_epoch_data is cached


def test_view_switch_preserves_manual_time_zoom_and_estimated_gait_bins_and_resets_cache_for_new_results(window):
    gait = pd.DataFrame({'gait_segment_nr': [1, 1, 1, 1], 'range_of_motion': [10., 30., 50., 90.]})
    window.analyzed({'quantifications': {'gait': {'unfiltered': gait}}, 'metadata': {'gait': {
        'unfiltered': {'per_segment': {1: {'start_s': 0., 'end_s': 3600., 'duration_s': 3600.}}}}}})
    window.result_tabs.setCurrentIndex(1)
    window.figure.axes[0].set_xlim(600., 2400.)
    window.result_graph_view.setCurrentIndex(1)
    axes = window.figure.axes[0]
    assert axes.get_xlim() == (600., 2400.)
    np.testing.assert_array_equal(axes._paradigma_epoch_data.value, [20, 70])
    window.result_graph_view.setCurrentIndex(0)
    assert window.figure.axes[0].get_xlim() == (600., 2400.)
    np.testing.assert_array_equal(window.figure.axes[0]._paradigma_bar_data[2], [10, 30, 50, 90])
    window.result_graph_view.setCurrentIndex(1)
    window.analyzed({'quantifications': {'gait': {'unfiltered': pd.DataFrame({'time': [0., 1.], 'range_of_motion': [2., 4.]})}}})
    np.testing.assert_array_equal(window.figure.axes[0]._paradigma_epoch_data.value, [3])
