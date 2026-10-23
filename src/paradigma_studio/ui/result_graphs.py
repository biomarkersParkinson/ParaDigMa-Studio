"""Results graph rendering and linked interaction callbacks over shared plot data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from PySide6.QtCore import QModelIndex, QObject
from PySide6.QtWidgets import (
    QComboBox,
    QPushButton,
    QTabWidget,
    QWidget,
)

from ..daily import DAY_SECONDS
from ..epoch_profile import format_profile_time
from ..results_view import MODULE_NAMES, clock_origin, clock_times
from ..theme import module_color, style_axes, style_result_heading
from ..widgets import (
    ReadableTable,
)
from ..workspace_state import (
    GraphState,
    ResultState,
)
from .deferred import DeferredWidget
from .graph_views import ResultCanvasView
from .result_graph_interactions import ResultGraphInteractions
from .result_plot_data import PROFILE_VIEW, ResultPlotData, _is_tremor_power

if TYPE_CHECKING:
    from matplotlib.backend_bases import MouseEvent
    from matplotlib.gridspec import GridSpec


@dataclass(frozen=True)
class ResultGraphView:
    parent: QWidget
    context_button: QPushButton
    dataset: QComboBox
    graph_view: DeferredWidget
    result_graph_view: QComboBox
    result_table: ReadableTable
    result_tabs: QTabWidget
    y_column: QComboBox
    result_graphics: Callable[[], ResultCanvasView]

    @property
    def canvas(self):
        return self.result_graphics().canvas

    @property
    def figure(self):
        return self.result_graphics().figure

    @property
    def graphs_workspace(self):
        return self.result_graphics().graphs_workspace

    @property
    def plot_toolbar(self):
        return self.result_graphics().plot_toolbar

    @property
    def result_overlay(self):
        return self.result_graphics().result_overlay

    @property
    def result_time_scroll(self):
        return self.result_graphics().result_time_scroll

    @property
    def time_axis(self):
        return self.result_graphics().time_axis


@dataclass(frozen=True)
class ResultGraphCallbacks:
    selected_result_series: Callable[..., Any]
    sync_table_outputs: Callable[..., Any]


class ResultGraphs(QObject):
    """Own graph behavior through explicit state, frozen views and callbacks."""

    def __init__(
        self,
        graphs: GraphState,
        results: ResultState,
        view: ResultGraphView,
        callbacks: ResultGraphCallbacks,
    ) -> None:
        super().__init__(view.parent)
        self.graphs = graphs
        self.results = results
        self.view = view
        self.callbacks = callbacks
        self.data = ResultPlotData(results, graphs._result_plot_cache)
        self.interactions = ResultGraphInteractions(graphs, results, view, callbacks, self.data)

    def gait_plot_presence(self):
        return self.data.gait_plot_presence()

    def epoch_plot_data(self, name, metric, positions, binary):
        return self.data.epoch_plot_data(
            name, metric, positions, binary, self.view.result_graph_view.currentIndex()
        )

    def daily_plot_data(self, name, metric, positions, binary):
        return self.data.daily_plot_data(name, metric, positions, binary)

    def epoch_metric_presence(self, name):
        return self.data.epoch_metric_presence(name)

    def plot(self, *_):
        if self.results._installing_results:
            return
        chosen = self.callbacks.selected_result_series()
        if not chosen and not self.view.graph_view.initialized:
            return

        from ..plotting import binary_indicator

        mode = self.view.result_graph_view.currentIndex()
        epochs = mode != 0
        signature = mode, tuple(chosen)
        if self.results._plot_signature == signature and self.view.figure.axes:
            self.highlight_result_row()
            return
        self.view.plot_toolbar.stop_navigation()
        previous_mode, viewport, previous_y = self._result_plot_viewport(chosen, mode)
        self.results._plot_signature = signature
        existing, shared = self._retain_result_axes(chosen, mode, previous_mode)
        actual_binaries = [
            (
                name.startswith("classifications/gait/")
                and metric in ("pred_gait_window", "pred_no_other_arm_activity_window")
            )
            or binary_indicator(self.results._plot_tables[name][metric], metric)
            for name, metric in chosen
        ]
        binaries = [False] * len(chosen) if epochs else actual_binaries
        self._size_result_canvas(chosen, binaries)
        first_axes = None
        # Only a non-empty selection indexes this grid.
        grid = cast(
            "GridSpec",
            (
                self.view.figure.add_gridspec(
                    len(chosen), 1, height_ratios=[0.34 if binary else 1 for binary in binaries]
                )
                if chosen
                else None
            ),
        )
        for index, (name, metric) in enumerate(chosen):
            ax = existing.get((name, metric))
            if ax is not None:
                ax.set_subplotspec(grid[index])
                self.view.figure.add_axes(ax)
                if ax is not shared:
                    ax.sharex(shared)
            else:
                ax = style_axes(
                    self.view.figure, position=(grid[index],), sharex=shared or first_axes
                )
            if first_axes is None:
                first_axes = ax
            if (name, metric) in existing:
                continue
            self._render_result_series(ax, name, metric, actual_binaries[index], epochs)
        self._finish_result_plot(first_axes, shared, viewport, previous_y)

    def _result_plot_viewport(self, chosen, mode):
        previous_mode, previous_chosen = self.results._plot_signature or (None, ())
        if mode != previous_mode:
            # Each view starts at its own full extent. Aggregation changes the
            # time bounds, and the clock-slot profile uses different coordinates.
            return previous_mode, None, {}
        changed = set(chosen).symmetric_difference(previous_chosen)
        coverage_only = (
            self.results._plot_signature is not None
            and bool(changed)
            and mode == previous_mode
            and bool(set(chosen).intersection(previous_chosen))
            and all(name.startswith("preparation/") for name, metric in changed)
        )
        viewport = None
        previous_y = {}
        if self.results._plot_signature is not None and self.view.figure.axes:
            source = self.view.figure.axes[0]
            if coverage_only or not source.get_autoscalex_on():
                viewport = source.get_xlim(), source.get_autoscalex_on()
            if coverage_only:
                previous_y = {
                    (ax._paradigma_dataset, ax._paradigma_metric): (
                        ax.get_ylim(),
                        ax.get_autoscaley_on(),
                    )
                    for ax in self.view.figure.axes
                    if hasattr(ax, "_paradigma_dataset")
                }
        return previous_mode, viewport, previous_y

    def _retain_result_axes(self, chosen, mode, previous_mode):
        cache = self.graphs._result_plot_cache
        cache.bind(
            self.results._plot_tables, mode, self.results.display_clock, reset=previous_mode is None
        )
        self.view.result_overlay.invalidate()
        for artist in self.graphs._result_selection_artists:
            artist.remove()
        self.graphs._result_selection_artists = []
        existing = {
            (ax._paradigma_dataset, ax._paradigma_metric): ax
            for ax in self.view.figure.axes
            if hasattr(ax, "_paradigma_dataset")
        }
        if previous_mode == mode:
            for key, axes in existing.items():
                if key not in chosen:
                    cache.capture(key, axes)
        # Keep already plotted arrays, paths and axes settings when adding a
        # series. A changed result or view still needs fresh scientific data.
        shared = self.graphs._result_shared_axes
        reuse = (
            previous_mode == mode
            and shared in self.view.figure.axes
            and shared is not None
            and any(key in existing for key in chosen)
        )
        if reuse and shared is not None:
            # Remove/re-add in tree order using the public Figure API. delaxes
            # disconnects sharing groups, but leaves each Axes' parent pointer.
            for ax in tuple(self.view.figure.axes):
                self.view.figure.delaxes(ax)
            existing = {key: ax for key, ax in existing.items() if key in chosen}
            if shared not in existing.values():
                shared = next(existing[key] for key in chosen if key in existing)
            for ax in existing.values():
                # Matplotlib has no public reparenting API. Clear only the old
                # sharing parent, then plot() rejoins via public Axes.sharex.
                # This also releases a deselected owner's strong references.
                ax._sharex = None
            # Removing the last Figure axis can leave shared tick helpers
            # pointing at the discarded owner even after the groups rejoin.
            for helper in (
                shared.xaxis.get_major_locator(),
                shared.xaxis.get_minor_locator(),
                shared.xaxis.get_major_formatter(),
                shared.xaxis.get_minor_formatter(),
            ):
                helper.set_axis(shared.xaxis)
        else:
            self.view.figure.clear()
            existing = {}
            shared = None
        return existing, shared

    def _size_result_canvas(self, chosen, binaries):
        compact_states = bool(binaries) and all(binaries)
        height = max(
            88 if compact_states else 190, sum(62 if binary else 155 for binary in binaries)
        )
        self.view.canvas.setMinimumHeight(height)
        self.view.canvas.setMaximumHeight(height if compact_states else 16777215)
        self.view.graphs_workspace.setMinimumHeight(280 if binaries and all(binaries) else 310)
        if not chosen:
            ax = style_axes(self.view.figure)
            ax.text(
                0.5,
                0.5,
                "Select metrics to plot",
                ha="center",
                transform=ax.transAxes,
                color="#68778c",
            )

    def _render_result_series(self, ax, name, metric, binary, epochs):
        from ..plotting import plot_bars

        ax._paradigma_dataset = name
        ax._paradigma_metric = metric
        selected, positions = self.results._detail_selections.get(
            name, (self.results._plot_tables[name].iloc[:0], np.array([], dtype=int))
        )
        times = self.results._timings[name]["Timeline time (s)"].to_numpy()[positions]
        percentage = binary or name.startswith("preparation/")
        ax._paradigma_epoch = epochs
        ax._paradigma_profile = self.view.result_graph_view.currentIndex() == PROFILE_VIEW
        if self.graphs._result_plot_cache.restore((name, metric), ax):
            pass
        elif epochs:
            self._render_epoch_series(ax, name, metric, positions, binary)
        elif len(selected) and np.isfinite(times).any():
            # Aggregated views reuse their summaries; only Detailed needs
            # per-sample plotting arrays and recording-clock conversion here.
            ys = self._result_plot_values(name, metric, positions)
            color = module_color(
                "preparation" if name.startswith("preparation/") else name.split("/")[1]
            )
            if binary:
                xs = self.data.point_coordinates(name, positions)
                self._render_binary_series(ax, name, metric, positions, xs, ys, color)
            else:
                starts, ends = self.data.bar_coordinates(name, positions)
                bars = plot_bars(ax, starts, ends, ys, color)
                if _is_tremor_power(name, metric):
                    # A subpixel rectangle can vanish when zoomed out, hiding
                    # the very peak that determines the automatic Y range.
                    bars.set_edgecolor(color)
                    bars.set_linewidth(0.5)
        else:
            ax.text(
                0.5,
                0.5,
                "No timed outputs",
                ha="center",
                transform=ax.transAxes,
                color="#68778c",
            )
        self._style_result_series(ax, name, metric, binary, epochs, percentage)

    def _result_plot_values(self, name, metric, positions):
        return self.data._result_plot_values(name, metric, positions)

    def _render_epoch_series(self, ax, name, metric, positions, binary):
        from ..plotting import plot_bars

        summary = self.epoch_plot_data(name, metric, positions, binary)
        ax._paradigma_epoch_data = summary
        color = module_color(
            "preparation" if name.startswith("preparation/") else name.split("/")[1]
        )
        if len(summary):
            plot_bars(
                ax,
                summary.start_s
                if ax._paradigma_profile
                else clock_times(summary.start_s, self.results.display_clock),
                summary.end_s
                if ax._paradigma_profile
                else clock_times(summary.end_s, self.results.display_clock),
                summary.value,
                color,
            )
        if not len(summary) or not np.isfinite(summary.value).any():
            if ax._paradigma_profile:
                message = "No valid 30-minute epochs across days"
            elif "data_s" in summary:
                message = "No days with ≥14 min 24 s of valid metric data"
            elif "presence_s" in summary:
                subject = (
                    ("filtered gait" if name.endswith("/filtered") else "gait")
                    if "/gait/" in name
                    else "tremor"
                )
                message = f"No epochs with ≥90 s of {subject} presence and valid outcomes"
            else:
                message = "No valid outputs"
            ax.text(
                0.5,
                0.5,
                message,
                ha="center",
                transform=ax.transAxes,
                color="#68778c",
                fontsize=9,
            )

    def _render_binary_series(self, ax, name, metric, positions, xs, ys, color):
        from ..plotting import plot_states, time_coordinates

        if (
            name == "classifications/gait/arm_activity"
            and metric == "pred_no_other_arm_activity_window"
        ):
            presence = self.gait_plot_presence()
            pairs = presence["filtered"]
            plot_states(
                ax,
                clock_times(pairs[:, 0], self.results.display_clock),
                np.ones(len(pairs)),
                color,
                ends=clock_times(pairs[:, 1], self.results.display_clock),
            )
            domain = presence["domain"]
            if len(domain):
                extent = time_coordinates(
                    clock_times(
                        [domain[:, 0].min(), domain[:, 1].max()], self.results.display_clock
                    )
                )
                ax.update_datalim(np.column_stack((extent, [1, 1])))
                ax.autoscale_view(scaley=False)
        else:
            stops = clock_times(
                self.results._interval_ends[name][positions], self.results.display_clock
            )
            plot_states(ax, xs, ys, color, ends=stops)

    def _style_result_series(self, ax, name, metric, binary, epochs, percentage):
        from matplotlib import dates

        if epochs or not binary:
            ylabel = (
                ("Availability (%)" if name.startswith("preparation/") else "Presence (%)")
                if epochs and percentage
                else "Median log₁₀(power + 1)"
                if epochs and _is_tremor_power(name, metric)
                else "log₁₀(power + 1)"
                if _is_tremor_power(name, metric)
                else "Median"
                if epochs
                else str(metric).replace("_", " ")
            )
            if ax._paradigma_profile:
                ylabel = (
                    "Mean availability (%)"
                    if name.startswith("preparation/")
                    else "Mean presence (%)"
                    if percentage
                    else "Mean epoch median\nlog₁₀(power + 1)"
                    if _is_tremor_power(name, metric)
                    else "Mean epoch median"
                )
            ax.set_ylabel(ylabel, fontsize=9)
        item = self.results._series_items.get((name, metric))
        metric_title = (
            item.text(0)
            if item is not None
            else self.results._plot_labels.get((name, metric), str(metric).replace("_", " "))
        )
        module = "preparation" if name.startswith("preparation/") else name.split("/")[1]
        style_result_heading(
            ax,
            metric_title,
            module,
            MODULE_NAMES.get(
                module, "Data coverage" if module == "preparation" else module.title()
            ),
        )
        if self.results.display_clock is not None:
            timezone = clock_origin(self.results.display_clock).tz
            ax.set_xlabel(
                f"Recording time ({self.results.display_clock.get('timezone') or 'timezone unspecified'})"
            )
            ax.format_xdata = lambda value, tz=timezone: dates.num2date(value, tz=tz).strftime(
                "%d %b %Y %H:%M:%S"
            )
        else:
            ax.set_xlabel(
                "File-order timeline (s)"
                if len(self.results.provenance.get("sources", {})) > 1
                else "Elapsed analysis time (s)"
            )
        if ax._paradigma_profile:
            self._style_profile_axis(ax)
        elif self.view.result_graph_view.currentIndex() == 2:
            self._style_daily_axis(ax)
        else:
            self._style_grouped_time_axis(ax)
        ax.tick_params(axis="x", labelbottom=False)
        ax.xaxis.label.set_visible(False)
        ax.xaxis.offsetText.set_visible(False)

    def _style_profile_axis(self, ax):
        from ..profile_axis import style_profile_axis

        style_profile_axis(ax)
        ax.format_xdata = format_profile_time
        ax.set_xlabel(
            f"Time of day ({self.results.display_clock.get('timezone') or 'timezone unspecified'}) · average across days"
            if self.results.display_clock
            else "Time in elapsed 24-hour period · average across days"
        )
        ax.margins(x=0)
        ax.update_datalim([[0, 0], [DAY_SECONDS, 0]])

    def _style_grouped_time_axis(self, ax):
        from ..epoch_axis import MidnightSeparators, style_epoch_axis
        from ..time_axis import RecordingTimeFormatter

        calendar = self.results.display_clock is not None
        timezone = clock_origin(self.results.display_clock).tz if calendar else None
        style_epoch_axis(
            ax,
            timezone,
            calendar=calendar,
            clock_formatter=RecordingTimeFormatter(timezone, show_date=False),
        )
        ax._paradigma_day_groups = True
        if not calendar:
            ax.set_xlabel(
                "File-order timeline (days / hours)"
                if len(self.results.provenance.get("sources", {})) > 1
                else "Elapsed analysis time (days / hours)"
            )
        MidnightSeparators(ax, timezone, calendar=calendar)

    def _style_daily_axis(self, ax):
        from ..day_axis import RecordingDayFormatter, RecordingDayLocator

        clock = self.results.display_clock
        calendar = clock is not None
        timezone = clock_origin(clock).tz if calendar else None
        ax.xaxis.set_major_locator(RecordingDayLocator(timezone, calendar=calendar))
        ax.xaxis.set_major_formatter(RecordingDayFormatter(timezone, calendar=calendar))
        ax.set_xlabel(
            f"Recording date ({clock.get('timezone') or 'timezone unspecified'})"
            if clock is not None
            else "Day (elapsed 24-hour periods)"
        )

    def _finish_result_plot(self, first_axes, shared, viewport, previous_y):
        # Recompute the shared full extent even if the retained master was
        # zoomed. The current zoom is restored below, while Home sees all data.
        from ..epoch_axis import MidnightBridges
        from ..plotting import autoscale_bars

        self.graphs._result_shared_axes = shared or first_axes
        if first_axes is not None:
            first_axes.set_autoscalex_on(True)
            first_axes.autoscale_view(scaley=False)
        # Shared X limits settle only after every series has been added.
        # Fit each automatic Y range against that final shared view.
        for ax in self.view.figure.axes:
            autoscale_bars(ax)
        if (
            first_axes is not None
            and getattr(first_axes, "_paradigma_day_groups", False)
            and not any(isinstance(artist, MidnightBridges) for artist in self.view.figure.artists)
        ):
            locator = first_axes.xaxis.get_major_locator()
            MidnightBridges(self.view.figure, locator.timezone, calendar=locator.calendar)
        self.view.plot_toolbar.refresh()
        self.view.result_time_scroll.bind(first_axes)
        self.view.time_axis.bind(first_axes, defer=True)
        if viewport is not None and first_axes is not None:
            # Keep Home as the full extent, while coverage toggles retain the
            # user's current view instead of making outcomes appear to change.
            self.view.plot_toolbar.push_current()
            limits, automatic_x = viewport
            first_axes.set_xlim(*limits, auto=automatic_x)
            for ax in self.view.figure.axes:
                previous = previous_y.get((ax._paradigma_dataset, ax._paradigma_metric))
                if previous is not None and not previous[1]:
                    ax.set_ylim(*previous[0], auto=False)
                autoscale_bars(ax)
            self.view.plot_toolbar.push_current()
        self.result_row_changed(self.view.result_table.currentIndex(), None)
        self.view.canvas.draw_idle()

    def result_row_changed(self, current: QModelIndex, previous: QModelIndex | None) -> None:
        self.interactions.result_row_changed(current, previous)

    def update_context_action(self, current: QModelIndex) -> None:
        self.interactions.update_context_action(current)

    def highlight_result_row(self) -> None:
        self.interactions.highlight_result_row()

    def update_result_marker(self) -> None:
        self.interactions.update_result_marker()

    def graph_clicked(self, event: MouseEvent) -> None:
        self.interactions.graph_clicked(event)
