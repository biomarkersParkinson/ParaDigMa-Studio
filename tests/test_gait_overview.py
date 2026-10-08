"""Gait overview uses exact official aggregate values and keeps native tables."""
from copy import deepcopy

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QFrame

from paradigma_desktop.app import MainWindow
from paradigma_desktop.gait_overview import aggregate_rows, duration_label


def aggregates():
    output = {}
    for branch_index, branch in enumerate(('unfiltered', 'filtered')):
        output[branch] = {}
        for duration_index, duration in enumerate(('20_inf', '0_20', '0_inf')):
            values = {'duration_s': 10. * (duration_index + 1)}
            for metric in ('range_of_motion', 'peak_velocity'):
                for index, statistic in enumerate(('median', '95p', 'median_cov', 'mean_cov')):
                    values[f'{statistic}_{metric}'] = branch_index * 10 + duration_index + index / 10
            output[branch][duration] = values
    output['filtered']['0_20']['95p_range_of_motion'] = np.nan
    output['unfiltered']['20_inf']['median_cov_peak_velocity'] = None
    return output


def test_overview_three_cards_with_all_statistics_and_ordered_exact_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    source = aggregates()
    original = deepcopy(source)
    window.show()
    window.analyzed({'aggregations': {'gait': source}})
    app.processEvents()
    try:
        cards = [widget for widget in window.findChildren(QFrame) if widget.property('gaitOverviewGroup')]
        assert {widget.property('gaitOverviewGroup') for widget in cards} == {'duration', 'range_of_motion', 'peak_velocity'}
        assert len(window.overview_gait_charts) == 9
        ordered = aggregate_rows(source)
        assert [(branch, duration) for branch, duration, _ in ordered] == [
            (branch, duration) for branch in ('filtered', 'unfiltered') for duration in ('0_inf', '0_20', '20_inf')]
        for metric, chart in window.overview_gait_charts.items():
            expected = np.asarray([np.nan if values.get(metric) is None else values[metric]
                                   for _, _, values in ordered])
            np.testing.assert_array_equal(chart['values'], expected)
            np.testing.assert_array_equal([bar.get_width() for bar in chart['axis'].patches], expected[np.isfinite(expected)])
            chart['canvas'].draw()
        assert not any(module == 'gait' and group == 'Aggregates' for module, group, path in window.overview_values)
        assert source == original  # No derived statistics or edits to aggregate dictionaries.
        assert window.aggregation_tables
        scroll = window._result_view_scrolls[0].verticalScrollBar()
        scroll.setValue(0)
        canvas = window.overview_gait_charts['duration_s']['canvas']
        event = QWheelEvent(QPointF(50, 50), QPointF(canvas.mapToGlobal(QPoint(50, 50))),
                            QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
        app.sendEvent(canvas, event)
        assert scroll.value() > 0  # Scrolling works while the pointer is over a chart.
    finally:
        window.close()
        app.processEvents()


def test_missing_statistics_and_unknown_aggregate_fields_are_retained(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.analyzed({'aggregations': {'gait': {'unfiltered': {'all': {
        'duration_s': 0., 'median_range_of_motion': None, 'custom_measure': 123}}}}})
    try:
        assert window.overview_gait_charts['duration_s']['values'].tolist() == [0.]
        assert np.isnan(window.overview_gait_charts['median_range_of_motion']['values'][0])
        assert window.overview_values[('gait', 'Aggregates', ('unfiltered', 'all', 'custom_measure'))].text() == '123'
        assert duration_label('0_inf') == 'All durations'
        assert duration_label('20_inf') == '≥ 20 s'
    finally:
        window.close()
        app.processEvents()


def test_charts_match_official_gait_aggregation_output(tmp_path):
    import pandas as pd
    from paradigma.pipelines.gait_pipeline import aggregate_arm_swing_params

    frame = pd.DataFrame({'gait_segment_nr': [1, 1, 1, 2, 2, 2],
                          'range_of_motion': [10., 12., 14., 20., 22., 24.],
                          'peak_velocity': [30., 40., 50., 60., 70., 80.]})
    metadata = {'per_segment': {1: {'duration_s': 10.}, 2: {'duration_s': 30.}}}
    official = aggregate_arm_swing_params(frame, segment_meta=metadata,
                gait_segment_categories=[(0, float('inf')), (0, 20), (20, float('inf'))],
                aggregates=['median', '95p', 'cov'])
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.analyzed({'aggregations': {'gait': {'unfiltered': official}}})
    try:
        assert len(window.overview_gait_charts) == 9
        for metric, chart in window.overview_gait_charts.items():
            expected = [official[duration][metric] for branch, duration in chart['categories']]
            np.testing.assert_array_equal(chart['values'], expected)
    finally:
        window.close()
        app.processEvents()
