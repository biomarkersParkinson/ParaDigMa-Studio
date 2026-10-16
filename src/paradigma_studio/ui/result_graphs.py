"""Results graph rendering, epoch caches and linked row inspection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtWidgets import (
    QComboBox,
    QPushButton,
    QTabWidget,
    QWidget,
)

from ..daily import DAY_SECONDS
from ..epoch_profile import format_profile_time
from ..epochs import (
    EPOCH_SECONDS,
)
from ..exploration import gait_context
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
from .result_plot_data import PROFILE_VIEW, ResultPlotData, _is_tremor_power


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
        self.data = ResultPlotData(results)

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
        grid = (
            self.view.figure.add_gridspec(
                len(chosen), 1, height_ratios=[0.34 if binary else 1 for binary in binaries]
            )
            if chosen
            else None
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
        self.view.result_overlay.invalidate()
        for artist in self.graphs._result_selection_artists:
            artist.remove()
        self.graphs._result_selection_artists = []
        existing = {
            (ax._paradigma_dataset, ax._paradigma_metric): ax
            for ax in self.view.figure.axes
            if hasattr(ax, "_paradigma_dataset")
        }
        # Keep already plotted arrays, paths and axes settings when adding a
        # series. A changed result or view still needs fresh scientific data.
        shared = self.graphs._result_shared_axes
        reuse = (
            previous_mode == mode
            and shared in self.view.figure.axes
            and shared is not None
            and (
                getattr(shared, "_paradigma_dataset", None),
                getattr(shared, "_paradigma_metric", None),
            )
            in chosen
        )
        if reuse:
            # Remove/re-add in tree order using the public Figure API. Rejoin
            # the existing X master after delaxes disconnects sharing groups.
            for ax in tuple(self.view.figure.axes):
                self.view.figure.delaxes(ax)
            existing = {key: ax for key, ax in existing.items() if key in chosen}
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
        if epochs:
            self._render_epoch_series(ax, name, metric, positions, binary)
        elif len(selected) and np.isfinite(times).any():
            # Aggregated views reuse their summaries; only Detailed needs
            # per-sample plotting arrays and recording-clock conversion here.
            ys = self._result_plot_values(name, metric, positions)
            xs = clock_times(times, self.results.display_clock)
            color = module_color(
                "preparation" if name.startswith("preparation/") else name.split("/")[1]
            )
            if binary:
                self._render_binary_series(ax, name, metric, positions, xs, ys, color)
            else:
                starts, ends = self.results._bar_bounds[name]
                bars = plot_bars(
                    ax,
                    clock_times(starts[positions], self.results.display_clock),
                    clock_times(ends[positions], self.results.display_clock),
                    ys,
                    color,
                )
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

        calendar = self.results.display_clock is not None
        timezone = clock_origin(self.results.display_clock).tz if calendar else None
        ax.xaxis.set_major_locator(RecordingDayLocator(timezone, calendar=calendar))
        ax.xaxis.set_major_formatter(RecordingDayFormatter(timezone, calendar=calendar))
        ax.set_xlabel(
            f"Recording date ({self.results.display_clock.get('timezone') or 'timezone unspecified'})"
            if calendar
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
        self.view.time_axis.bind(first_axes)
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

    def result_row_changed(self, current, previous):
        self.update_context_action(current)
        self.highlight_result_row()

    def update_context_action(self, current):
        frame = self.results.active_frame
        valid_row = current.isValid() and frame is not None
        timestamp = False
        if valid_row:
            # Empty Results plots also refresh this button during startup.
            # Inspect tabular values only after a real result row exists.
            import pandas as pd

            timestamp = (
                "time" in frame
                and pd.api.types.is_numeric_dtype(frame["time"].dtype)
                and pd.notna(frame["time"].iloc[current.row()])
                and np.isfinite(frame["time"].iloc[current.row()])
            )
        segment = (
            gait_context(
                self.results.results, self.view.dataset.currentText(), frame.iloc[current.row()]
            )
            if valid_row
            else None
        )
        profile = (
            self.view.result_graph_view.currentIndex() == PROFILE_VIEW
            and self.view.result_tabs.currentIndex() == 1
        )
        usable = (
            not profile
            and self.results.result_source_frame is not None
            and (timestamp or segment is not None)
        )
        self.view.context_button.setEnabled(bool(usable))
        self.view.context_button.setText(
            "Inspect gait segment"
            if segment is not None and not timestamp
            else "Inspect sensor context"
        )
        if valid_row:
            self.view.context_button.setToolTip("")
        if valid_row and not timestamp and segment is None:
            self.view.context_button.setToolTip("No sensor timing available")
        if self.results.result_source_frame is None:
            self.view.context_button.setToolTip("Original sensor data unavailable")
        if profile:
            self.view.context_button.setToolTip(
                "A 24-hour profile combines multiple days. Select another view to inspect an actual timepoint."
            )

    def highlight_result_row(self):
        if not self.view.graph_view.initialized:
            return
        with self.view.result_overlay.edit():
            self.update_result_marker()
        self.view.result_overlay.paint()

    def update_result_marker(self):
        """Link a table row to all plots without changing their data or limits."""
        from matplotlib import dates

        from ..plotting import time_selection_line

        for artist in self.graphs._result_selection_artists:
            artist.remove()
        self.graphs._result_selection_artists = []
        self.view.time_axis.set_selection(None)
        if self.view.result_graph_view.currentIndex() == PROFILE_VIEW:
            self._update_profile_marker()
            return
        name, frame = self.view.dataset.currentText(), self.results.active_frame
        current = self.view.result_table.currentIndex()
        if frame is None or not current.isValid() or name not in self.results._timings:
            return
        row = current.row()
        position = self.results.active_positions[row]
        timing = self.results._timings[name].iloc[position]
        seconds = float(timing["Timeline time (s)"])
        if not np.isfinite(seconds):
            return
        if self.results.display_clock is not None:
            timestamp = clock_times([seconds], self.results.display_clock)[0]
            x = float(dates.date2num(timestamp.to_pydatetime(warn=False)))
            label = timestamp.strftime("%d %b %Y %H:%M:%S.%f").rstrip("0").rstrip(".")
        else:
            x, label = seconds, f"{seconds:.6g} s"
        self.view.time_axis.set_selection(x, label)
        for ax in self.view.figure.axes:
            if not hasattr(ax, "_paradigma_dataset"):
                continue
            line = time_selection_line(ax, x, animated=self.view.canvas.supports_blit)
            self.graphs._result_selection_artists.append(line)
            if ax._paradigma_dataset != name:
                continue
            self._mark_selected_result(ax, name, row, seconds, x)

    def _mark_selected_result(self, ax, name, row, seconds, x):
        """Add a point only where the selected result has a visible value."""
        import pandas as pd

        if getattr(ax, "_paradigma_epoch", False):
            summary = ax._paradigma_epoch_data
            selected = summary.loc[(summary.start_s <= seconds) & (seconds < summary.end_s)]
            value = selected.value.iloc[0] if len(selected) else np.nan
        else:
            value = self._result_plot_values(
                name, ax._paradigma_metric, [self.results.active_positions[row]]
            )[0]
            if (
                name == "classifications/gait/arm_activity"
                and ax._paradigma_metric == "pred_no_other_arm_activity_window"
            ):
                pairs = self.gait_plot_presence()["filtered"]
                if not ((pairs[:, 0] <= seconds) & (seconds < pairs[:, 1])).any():
                    return
        if (
            pd.isna(value)
            or not np.isfinite(float(value))
            or getattr(ax, "_paradigma_binary", False)
            and float(value) != 1.0
        ):
            return
        self._mark_result_value(ax, name, x, float(value))

    def _mark_result_value(self, ax, name, x, value):
        from matplotlib.lines import Line2D

        point = Line2D(
            [x],
            [float(value)],
            linestyle="none",
            marker="o",
            markersize=9,
            markerfacecolor="white",
            markeredgecolor=module_color(name.split("/")[1]),
            markeredgewidth=2,
            zorder=8,
        )
        point.set_gid("selected-result-point")
        point.set_animated(self.view.canvas.supports_blit)
        ax.add_artist(point)
        self.graphs._result_selection_artists.append(point)

    def _update_profile_marker(self):
        from ..plotting import time_selection_line

        if self.results._profile_selection is None:
            return
        name, metric, x = self.results._profile_selection
        label = f"{format_profile_time(x - EPOCH_SECONDS / 2)}–{format_profile_time(x + EPOCH_SECONDS / 2)}"
        self.view.time_axis.set_selection(x, label)
        for ax in self.view.figure.axes:
            if not getattr(ax, "_paradigma_profile", False):
                continue
            line = time_selection_line(ax, x, animated=self.view.canvas.supports_blit)
            self.graphs._result_selection_artists.append(line)
            if (ax._paradigma_dataset, ax._paradigma_metric) != (name, metric):
                continue
            summary = ax._paradigma_epoch_data
            selected = summary.loc[(summary.start_s <= x) & (x < summary.end_s)]
            if len(selected) and np.isfinite(selected.value.iloc[0]):
                self._mark_result_value(ax, name, x, selected.value.iloc[0])
                days = int(selected.n_days.iloc[0])
                self.view.time_axis.set_selection(
                    x, f"{label} · {days} {'day' if days == 1 else 'days'}"
                )

    def _profile_clicked(self, event):
        ax = event.inaxes
        if not getattr(ax, "_paradigma_profile", False):
            return
        summary = ax._paradigma_epoch_data
        epoch = summary.loc[(summary.start_s <= event.xdata) & (event.xdata < summary.end_s)]
        if epoch.empty or not np.isfinite(epoch.value.iloc[0]):
            return
        self.results._profile_selection = (
            ax._paradigma_dataset,
            ax._paradigma_metric,
            float((epoch.start_s.iloc[0] + epoch.end_s.iloc[0]) / 2),
        )
        self.highlight_result_row()

    def graph_clicked(self, event):
        if event.inaxes is None or event.xdata is None or self.view.plot_toolbar.mode:
            return
        if self.view.result_graph_view.currentIndex() == PROFILE_VIEW:
            self._profile_clicked(event)
            return
        name = getattr(event.inaxes, "_paradigma_dataset", self.view.dataset.currentText())
        if name not in self.results.tables:
            return
        anchor = self._graph_click_anchor(name, event.xdata)
        self.view.dataset.setCurrentText(name)
        self.callbacks.sync_table_outputs(force_detail=True)
        metric = getattr(event.inaxes, "_paradigma_metric", None)
        if metric is not None:
            self.view.y_column.blockSignals(True)
            self.view.y_column.setCurrentIndex(self.view.y_column.findData(metric))
            self.view.y_column.blockSignals(False)
        frame = self.results.active_frame
        if frame is None or frame.empty:
            return
        row = self._graph_click_row(event.inaxes, name, metric, anchor)
        if row is None:
            return
        self.view.result_table.setCurrentIndex(self.view.result_table.model().index(row, 0))
        self.view.result_table.selectRow(row)
        self.view.result_table.scrollTo(self.view.result_table.currentIndex())
        self.view.plot_toolbar.active_axes = next(
            (
                ax
                for ax in self.view.figure.axes
                if getattr(ax, "_paradigma_dataset", None) == name
                and getattr(ax, "_paradigma_metric", None) == metric
            ),
            None,
        )
        if self.view.plot_toolbar.settings_action.isChecked():
            self.view.plot_toolbar.settings.read_axes()

    def _graph_click_anchor(self, name, xdata):
        import pandas as pd
        from matplotlib import dates

        anchor = float(xdata)
        if self.results.display_clock is not None:
            anchor = (
                anchor - dates.date2num(pd.Timestamp(self.results.display_clock["origin"]))
            ) * 86400
            # Matplotlib stores dates as floats in days; recover exact nearby
            # output anchors before choosing the interval that contains a click.
            all_times = self.results._timings[name]["Timeline time (s)"].to_numpy()
            close = np.flatnonzero(np.isfinite(all_times) & (np.abs(all_times - anchor) < 1e-5))
            if len(close):
                anchor = float(all_times[close[0]])
        return anchor

    def _graph_click_row(self, ax, name, metric, anchor):
        """Resolve clicks against unchanged source positions and interval bounds."""
        times = self.results._timings[name]["Timeline time (s)"].to_numpy()[
            self.results.active_positions
        ]
        distances = np.abs(times - anchor)
        finite = np.isfinite(distances)
        if not finite.any():
            return
        row = int(np.argmin(np.where(finite, distances, np.inf)))
        if getattr(ax, "_paradigma_epoch", False):
            summary = ax._paradigma_epoch_data
            epoch = summary.loc[(summary.start_s <= anchor) & (anchor < summary.end_s)]
            if epoch.empty or not np.isfinite(epoch.value.iloc[0]):
                return
            observed = (
                self.results._plot_tables[name][metric]
                .iloc[self.results.active_positions]
                .to_numpy(dtype=float, na_value=np.nan)
            )
            matching = (
                finite
                & np.isfinite(observed)
                & (times >= epoch.start_s.iloc[0])
                & (times < epoch.end_s.iloc[0])
            )
            if not matching.any():
                return
            row = int(np.argmin(np.where(matching, distances, np.inf)))
        elif (
            getattr(ax, "_paradigma_binary", False) or getattr(ax, "_paradigma_bars", False)
        ) and metric in self.results._plot_tables[name]:
            ends = self.results._interval_ends[name][self.results.active_positions]
            present = (
                self.results._plot_tables[name][metric]
                .iloc[self.results.active_positions]
                .eq(1)
                .fillna(False)
                .to_numpy(dtype=bool)
            )
            if getattr(ax, "_paradigma_bars", False):
                starts, all_ends = self.results._bar_bounds[name]
                times, ends = (
                    starts[self.results.active_positions],
                    all_ends[self.results.active_positions],
                )
                present = (
                    self.results._plot_tables[name][metric]
                    .iloc[self.results.active_positions]
                    .notna()
                    .to_numpy()
                )
            covering = np.flatnonzero(present & (times <= anchor) & (anchor < ends))
            if len(covering):
                row = int(covering[-1])
        return row
