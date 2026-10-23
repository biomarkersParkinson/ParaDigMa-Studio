"""Graph clicks, linked table selection and result markers, separate from rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import numpy as np
from PySide6.QtCore import QModelIndex

from ..epoch_profile import format_profile_time
from ..epochs import EPOCH_SECONDS
from ..exploration import gait_context
from ..results_view import clock_times
from ..theme import module_color
from ..workspace_state import GraphState, ResultState
from .result_plot_data import PROFILE_VIEW, ResultPlotData

if TYPE_CHECKING:
    from matplotlib.backend_bases import MouseEvent

    from .result_graphs import ResultGraphCallbacks, ResultGraphView


class ResultGraphInteractions:
    """Use the renderer's explicit view, state and cached data without owning a canvas."""

    def __init__(
        self,
        graphs: GraphState,
        results: ResultState,
        view: ResultGraphView,
        callbacks: ResultGraphCallbacks,
        data: ResultPlotData,
    ) -> None:
        self.graphs, self.results = graphs, results
        self.view, self.callbacks, self.data = view, callbacks, data

    def result_row_changed(self, current: QModelIndex, previous: QModelIndex | None) -> None:
        self.update_context_action(current)
        self.highlight_result_row()

    def update_context_action(self, current: QModelIndex) -> None:
        frame = self.results.active_frame
        valid_row = current.isValid() and frame is not None
        timestamp = False
        if valid_row and frame is not None:
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
            if valid_row and frame is not None
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

    def highlight_result_row(self) -> None:
        if not self.view.graph_view.initialized:
            return
        with self.view.result_overlay.edit():
            self.update_result_marker()
        self.view.result_overlay.paint()

    def update_result_marker(self) -> None:
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
        # Positions are installed alongside the selected frame.
        position = cast(np.ndarray, self.results.active_positions)[row]
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
            line = time_selection_line(ax, x, animated=self.view.canvas.supports_blit, linked=True)
            self.graphs._result_selection_artists.append(line)
            if ax._paradigma_dataset != name:
                continue
            self._mark_selected_result(ax, name, row, seconds, x)
        self._bridge_result_marker()

    def _bridge_result_marker(self):
        from matplotlib.lines import Line2D

        from ..selection_lines import TimeSelectionBridges

        lines = [
            artist
            for artist in self.graphs._result_selection_artists
            if isinstance(artist, Line2D) and artist.get_gid() == "selected-result-time"
        ]
        if len(lines) > 1:
            bridge = TimeSelectionBridges(self.view.figure, lines[0])
            self.graphs._result_selection_artists.append(bridge)

    def _mark_selected_result(self, ax, name, row, seconds, x):
        """Add a point only where the selected result has a visible value."""
        import pandas as pd

        if getattr(ax, "_paradigma_epoch", False):
            summary = ax._paradigma_epoch_data
            selected = summary.loc[(summary.start_s <= seconds) & (seconds < summary.end_s)]
            value = selected.value.iloc[0] if len(selected) else np.nan
        else:
            value = self.data._result_plot_values(
                name, ax._paradigma_metric, [cast(np.ndarray, self.results.active_positions)[row]]
            )[0]
            if (
                name == "classifications/gait/arm_activity"
                and ax._paradigma_metric == "pred_no_other_arm_activity_window"
            ):
                pairs = self.data.gait_plot_presence()["filtered"]
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
            line = time_selection_line(ax, x, animated=self.view.canvas.supports_blit, linked=True)
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
        self._bridge_result_marker()

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

    def graph_clicked(self, event: MouseEvent) -> None:
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
