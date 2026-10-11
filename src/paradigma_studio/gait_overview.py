"""Charts of official gait aggregates, without recomputing scientific values."""

import re

import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from .plotting import ScrollableFigureCanvas
from .theme import style_axes
from .widgets import card, label

STATISTICS = (
    ("median", "Median"),
    ("95p", "95th percentile"),
    ("median_cov", "Median CV"),
    ("mean_cov", "Mean CV"),
)


def duration_order(name):
    numbers = tuple(float(value) for value in re.findall(r"\d+(?:\.\d+)?", str(name)))
    return (0 if str(name).lower() in ("all", "combined") else 1, numbers, str(name))


def duration_label(name):
    if str(name).lower() in ("all", "combined", "0_inf", "0.0_inf"):
        return "All durations"
    match = re.fullmatch(r"(\d+(?:\.\d+)?)_(\d+(?:\.\d+)?|inf)", str(name))
    if match:
        low, high = match.groups()
        return f"≥ {float(low):g} s" if high == "inf" else f"{float(low):g}–{float(high):g} s"
    return str(name).replace("_", " ")


def aggregate_rows(aggregates):
    rows = []
    if not isinstance(aggregates, dict):
        return rows
    for branch in sorted(
        aggregates, key=lambda name: ({"filtered": 0, "unfiltered": 1}.get(name, 2), name)
    ):
        categories = aggregates[branch]
        if not isinstance(categories, dict):
            continue
        for duration in sorted(categories, key=duration_order):
            values = categories[duration]
            if isinstance(values, dict):
                rows.append((branch, duration, values))
    return rows


def segment_count_rows(metadata):
    """Count segment metadata using ParaDigMa's unfiltered-duration bins.

    Missing metadata or invalid durations remain unknown rather than implying
    no gait. Known empty segment dictionaries produce zero counts.
    """
    rows = []
    for branch in ("filtered", "unfiltered"):
        segments = (metadata or {}).get(branch, {}).get("per_segment")
        counts = [np.nan, np.nan]
        if isinstance(segments, dict):
            lengths = []
            for segment in segments.values():
                try:
                    if "unfiltered_duration_s" in segment:
                        length = float(segment["unfiltered_duration_s"])
                    elif "duration_s" in segment:
                        length = float(segment["duration_s"])
                    else:
                        length = float(segment["end_s"]) - float(segment["start_s"])
                    if not np.isfinite(length) or length < 0:
                        break
                    lengths.append(length)
                except (KeyError, TypeError, ValueError, OverflowError):
                    break
            else:
                counts = [
                    sum(length < 20 for length in lengths),
                    sum(length >= 20 for length in lengths),
                ]
        rows.extend(
            (branch, duration, {"segment_count": count})
            for duration, count in zip(("0_20", "20_inf"), counts, strict=False)
        )
    return rows


def build_gait_charts(aggregates, *, metadata=None, scroll_area=None):
    """Return three aggregate cards, chart data for inspection, and consumed paths."""
    rows = aggregate_rows(aggregates)
    count_rows = segment_count_rows(metadata)
    cards, charts, consumed = [], {}, set()
    groups = [
        (
            "quantity",
            "Quantity",
            [
                ("duration_s", "Duration", "Minutes"),
                ("segment_count", "Gait segments", "Number of segments"),
            ],
        ),
        (
            "range_of_motion",
            "Range of motion",
            [
                (f"{key}_range_of_motion", title, "CV (ratio)" if "cov" in key else "Degrees")
                for key, title in STATISTICS
            ],
        ),
        (
            "peak_velocity",
            "Peak velocity",
            [
                (
                    f"{key}_peak_velocity",
                    title,
                    "CV (ratio)" if "cov" in key else "Degrees / second",
                )
                for key, title in STATISTICS
            ],
        ),
    ]
    for group, title, metrics in groups:
        if not any(
            metric in values for branch, duration, values in rows for metric, _, _ in metrics
        ) and not (
            group == "quantity"
            and any(np.isfinite(values["segment_count"]) for _, _, values in count_rows)
        ):
            continue
        panel, content = card()
        panel.setProperty("gaitOverviewGroup", group)
        content.addWidget(label(title, "sectionTitle"))
        figure = Figure(layout="constrained", facecolor="white")
        canvas = ScrollableFigureCanvas(figure)
        canvas.defer_when_hidden = True
        canvas.scroll_area = scroll_area
        canvas.setFixedHeight(
            max(240, max(len(rows), len(count_rows) if group == "quantity" else 0) * 32 + 90)
            * (1 if group == "quantity" else 2)
        )
        grid = figure.add_gridspec(1, 2) if group == "quantity" else figure.add_gridspec(2, 2)
        for index, (metric, heading, unit) in enumerate(metrics):
            metric_rows = count_rows if metric == "segment_count" else rows
            charts[metric] = _render_gait_metric(
                figure, canvas, grid, index, metric, heading, unit, metric_rows, consumed
            )
        content.addWidget(canvas)
        cards.append(panel)
        canvas.draw_idle()
    return cards, charts, consumed


def _render_gait_metric(figure, canvas, grid, index, metric, heading, unit, metric_rows, consumed):
    categories = [
        f"{branch.replace('_', ' ').title()} · {duration_label(duration)}"
        for branch, duration, values in metric_rows
    ]
    colors = ["#477DA3" if branch == "filtered" else "#9CBACF" for branch, _, _ in metric_rows]
    axis = style_axes(figure, position=(grid[index // 2, index % 2],))
    numbers = []
    for branch, duration, values in metric_rows:
        value = values.get(metric)
        numbers.append(float(value) if isinstance(value, (int, float, np.number)) else np.nan)
        if metric in values and metric != "segment_count":
            consumed.add((branch, duration, metric))
    numbers = np.asarray(numbers)
    display_numbers = numbers / 60 if metric == "duration_s" else numbers
    positions = np.arange(len(metric_rows))
    valid = np.isfinite(numbers)
    axis.barh(
        positions[valid],
        display_numbers[valid],
        color=np.asarray(colors)[valid],
        height=0.62,
        zorder=3,
    )
    axis.set_yticks(positions, categories, fontsize=9)
    axis.set_ylim(max(len(metric_rows), 1) - 0.5, -0.5)
    axis.set_title(heading, loc="left", fontsize=10, color="#243C57")
    axis.set_xlabel(unit, fontsize=9)
    axis.grid(False, axis="y")
    axis.grid(True, axis="x", color="#E8EDF3", linewidth=0.7)
    axis.margins(x=0.18)
    if metric == "segment_count":
        axis.xaxis.set_major_locator(MaxNLocator(nbins=4, integer=True, min_n_ticks=2))
        canvas.setToolTip(
            "Segment counts use original unfiltered segment durations, matching ParaDigMa.\n"
            "0–20 s excludes 20 s; ≥ 20 s includes it. Missing metadata is shown as —."
        )
    precision = 0 if metric == "segment_count" else 2 if "_cov_" in metric else 1
    for position, value in zip(positions, display_numbers, strict=False):
        if np.isfinite(value):
            axis.annotate(
                f"{value:.{precision}f}",
                (value, position),
                xytext=(5, 0),
                textcoords="offset points",
                va="center",
                fontsize=9,
                color="#243C57",
            )
        else:
            axis.text(
                0.02,
                position,
                "—",
                transform=axis.get_yaxis_transform(),
                va="center",
                color="#68778C",
            )
    for position in range(1, len(metric_rows)):
        if metric_rows[position][0] != metric_rows[position - 1][0]:
            axis.axhline(position - 0.5, color="#DCE5EE", linewidth=1)
    axis._paradigma_aggregate_metric = metric
    return {
        "canvas": canvas,
        "axis": axis,
        "categories": [(b, d) for b, d, _ in metric_rows],
        "values": numbers,
        "display_values": display_numbers,
    }
