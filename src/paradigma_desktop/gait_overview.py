"""Charts of official gait aggregates, without recomputing scientific values."""
import re

import numpy as np

from matplotlib.figure import Figure

from .plotting import ScrollableFigureCanvas
from .theme import style_axes
from .widgets import card, label


STATISTICS = (("median", "Median"), ("95p", "95th percentile"),
              ("median_cov", "Median CV"), ("mean_cov", "Mean CV"))


def duration_order(name):
    numbers = tuple(float(value) for value in re.findall(r'\d+(?:\.\d+)?', str(name)))
    return (0 if str(name).lower() in ('all', 'combined') else 1, numbers, str(name))


def duration_label(name):
    if str(name).lower() in ('all', 'combined', '0_inf', '0.0_inf'):
        return 'All durations'
    match = re.fullmatch(r'(\d+(?:\.\d+)?)_(\d+(?:\.\d+)?|inf)', str(name))
    if match:
        low, high = match.groups()
        return f'≥ {float(low):g} s' if high == 'inf' else f'{float(low):g}–{float(high):g} s'
    return str(name).replace('_', ' ')


def aggregate_rows(aggregates):
    rows = []
    if not isinstance(aggregates, dict):
        return rows
    for branch in sorted(aggregates, key=lambda name: ({'filtered': 0, 'unfiltered': 1}.get(name, 2), name)):
        categories = aggregates[branch]
        if not isinstance(categories, dict):
            continue
        for duration in sorted(categories, key=duration_order):
            values = categories[duration]
            if isinstance(values, dict):
                rows.append((branch, duration, values))
    return rows


def build_gait_charts(aggregates, *, scroll_area=None):
    """Return three aggregate cards, chart data for inspection, and consumed paths."""
    rows = aggregate_rows(aggregates)
    cards, charts, consumed = [], {}, set()
    groups = [('duration', 'Duration', [('duration_s', 'Duration', 'Seconds')]),
              ('range_of_motion', 'Range of motion', [(f'{key}_range_of_motion', title,
                  'CV (ratio)' if 'cov' in key else 'Degrees') for key, title in STATISTICS]),
              ('peak_velocity', 'Peak velocity', [(f'{key}_peak_velocity', title,
                  'CV (ratio)' if 'cov' in key else 'Degrees / second') for key, title in STATISTICS])]
    for group, title, metrics in groups:
        if not any(metric in values for branch, duration, values in rows for metric, _, _ in metrics):
            continue
        panel, content = card()
        panel.setProperty('gaitOverviewGroup', group)
        content.addWidget(label(title, 'sectionTitle'))
        figure = Figure(layout='constrained', facecolor='white')
        canvas = ScrollableFigureCanvas(figure)
        canvas.defer_when_hidden = True
        canvas.scroll_area = scroll_area
        canvas.setFixedHeight(max(240, len(rows) * 32 + 90) * (1 if group == 'duration' else 2))
        grid = figure.add_gridspec(1, 1) if group == 'duration' else figure.add_gridspec(2, 2)
        categories = [f'{branch.replace("_", " ").title()} · {duration_label(duration)}'
                      for branch, duration, values in rows]
        colors = ['#477DA3' if branch == 'filtered' else '#9CBACF' for branch, _, _ in rows]
        for index, (metric, heading, unit) in enumerate(metrics):
            axis = style_axes(figure, position=(grid[index // 2, index % 2],)) if len(metrics) > 1 else style_axes(figure, position=(grid[0, 0],))
            numbers = []
            for branch, duration, values in rows:
                value = values.get(metric)
                numbers.append(float(value) if isinstance(value, (int, float, np.number)) else np.nan)
                if metric in values:
                    consumed.add((branch, duration, metric))
            numbers = np.asarray(numbers)
            positions = np.arange(len(rows))
            valid = np.isfinite(numbers)
            axis.barh(positions[valid], numbers[valid], color=np.asarray(colors)[valid], height=.62, zorder=3)
            axis.set_yticks(positions, categories, fontsize=9)
            axis.set_ylim(len(rows) - .5, -.5)
            axis.set_title(heading, loc='left', fontsize=10, color='#243C57')
            axis.set_xlabel(unit, fontsize=9)
            axis.grid(False, axis='y')
            axis.grid(True, axis='x', color='#E8EDF3', linewidth=.7)
            axis.margins(x=.18)
            for position, value in zip(positions, numbers):
                if np.isfinite(value):
                    axis.annotate(f'{value:.5g}', (value, position), xytext=(5, 0),
                                  textcoords='offset points', va='center', fontsize=9, color='#243C57')
                else:
                    axis.text(.02, position, '—', transform=axis.get_yaxis_transform(), va='center', color='#68778C')
            for position in range(1, len(rows)):
                if rows[position][0] != rows[position - 1][0]:
                    axis.axhline(position - .5, color='#DCE5EE', linewidth=1)
            axis._paradigma_aggregate_metric = metric
            charts[metric] = {'canvas': canvas, 'axis': axis, 'categories': [(b, d) for b, d, _ in rows], 'values': numbers}
        content.addWidget(canvas)
        cards.append(panel)
        canvas.draw_idle()
    return cards, charts, consumed
