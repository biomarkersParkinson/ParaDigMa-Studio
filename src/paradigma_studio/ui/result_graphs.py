"""Results graph rendering, epoch caches and linked row inspection."""

import numpy as np
from matplotlib import dates
from matplotlib.lines import Line2D

from ..epochs import availability_epoch_summary, epoch_phase, epoch_summary, require_epoch_presence
from ..exploration import PARTICIPANT_COLUMNS, gait_context
from ..gait_presence import gait_epoch_summaries, gait_presence_intervals
from ..plotting import (
    autoscale_bars,
    binary_indicator,
    plot_bars,
    plot_states,
    time_coordinates,
    time_selection_line,
)
from ..results_view import MODULE_NAMES, clock_origin, clock_times
from ..theme import module_color, style_axes, style_result_heading
from ..time_axis import RecordingDateLocator, RecordingTimeFormatter


class ResultGraphs:
    """Results rendering using the host MainWindow selection and cache state."""

    def gait_plot_presence(self):
        import pandas as pd

        if self._gait_presence_cache is None:

            def frame(stage, metric):
                name = "classifications/gait/" + stage
                source = self._plot_tables.get(name)
                if source is None or metric not in source:
                    return None
                data = pd.DataFrame(
                    {
                        "start": self._timings[name]["Timeline time (s)"].to_numpy(),
                        "end": self._interval_ends[name],
                        "state": source[metric].to_numpy(dtype=float, na_value=np.nan),
                    }
                )
                for key in ("file_key", *PARTICIPANT_COLUMNS):
                    if key in source:
                        data[key] = source[key].to_numpy()
                return data

            detection = frame("detection", "pred_gait_window")
            self._gait_presence_cache = gait_presence_intervals(
                detection
                if detection is not None
                else pd.DataFrame(columns=["start", "end", "state"]),
                frame("arm_activity", "pred_no_other_arm_activity_window"),
            )
        return self._gait_presence_cache

    def epoch_plot_data(self, name, metric, positions, binary):
        key = name, metric, id(positions)
        if key not in self._epoch_views:
            times = self._timings[name]["Timeline time (s)"].to_numpy()[positions]
            phase = epoch_phase(self.display_clock)
            if name.startswith("classifications/gait/") and metric in (
                "pred_gait_window",
                "pred_no_other_arm_activity_window",
            ):
                if self._gait_epoch_cache is None:
                    self._gait_epoch_cache = gait_epoch_summaries(self.gait_plot_presence(), phase)
                frame = self._gait_epoch_cache[
                    "gait" if metric == "pred_gait_window" else "filtered"
                ]
            elif name.startswith("preparation/"):
                extent = self.provenance.get("recording_extent", {})
                try:
                    bounds = float(extent["start_s"]), float(extent["end_s"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    bounds = None
                frame = availability_epoch_summary(
                    times, self._interval_ends[name][positions], phase=phase, bounds=bounds
                )
            else:
                values = (
                    self._plot_tables[name][metric]
                    .iloc[positions]
                    .to_numpy(dtype=float, na_value=np.nan)
                )
                frame = epoch_summary(times, values, binary=binary, phase=phase)
                if (
                    name.startswith("quantifications/gait/")
                    and any(part in str(metric) for part in ("range_of_motion", "peak_velocity"))
                    or name.startswith("quantifications/tremor")
                    and "tremor_power" in str(metric)
                ):
                    frame = require_epoch_presence(frame, self.epoch_metric_presence(name))
            self._epoch_views[key] = frame
        return self._epoch_views[key]

    def epoch_metric_presence(self, name):
        if name not in self._epoch_presence_views:
            pairs = np.empty((0, 2))
            if name.startswith("quantifications/gait/"):
                filtered = name.endswith("/filtered")
                stage = "classifications/gait/" + ("arm_activity" if filtered else "detection")
                indicator = "pred_no_other_arm_activity_window" if filtered else "pred_gait_window"
                if stage in self._plot_tables and indicator in self._plot_tables[stage]:
                    if filtered:
                        pairs = self.gait_plot_presence()["filtered"]
                    else:
                        # Unfiltered gait does not require an arm-filter label.
                        source = self._plot_tables[stage]
                        positive = source.pred_gait_window.eq(1).fillna(False).to_numpy(dtype=bool)
                        pairs = np.column_stack(
                            (
                                self._timings[stage]["Timeline time (s)"].to_numpy()[positive],
                                self._interval_ends[stage][positive],
                            )
                        )
                elif "gait_segment_nr" in self._plot_tables[name]:
                    # Older saved runs may only contain quantified segments.
                    # Their known full bounds, not swing counts, establish time.
                    timing = self._timings[name]
                    offset = timing["Timeline time (s)"] - timing["Analysis time (s)"]
                    pairs = np.column_stack(
                        (timing["Segment start (s)"] + offset, timing["Segment end (s)"] + offset)
                    )
            else:
                for candidate in ("classifications/tremor", name):
                    source = self._plot_tables.get(candidate)
                    if source is not None and "pred_tremor_checked" in source:
                        positive = (
                            source.pred_tremor_checked.eq(1).fillna(False).to_numpy(dtype=bool)
                        )
                        pairs = np.column_stack(
                            (
                                self._timings[candidate]["Timeline time (s)"].to_numpy()[positive],
                                self._interval_ends[candidate][positive],
                            )
                        )
                        break
            self._epoch_presence_views[name] = availability_epoch_summary(
                pairs[:, 0], pairs[:, 1], phase=epoch_phase(self.display_clock)
            )
        return self._epoch_presence_views[name]

    def plot(self, *_):
        chosen = self.selected_result_series()
        epochs = self.result_graph_view.currentIndex() == 1
        signature = epochs, tuple(chosen)
        if self._plot_signature == signature and self.figure.axes:
            self.highlight_result_row()
            return
        previous_mode, viewport, previous_y = self._result_plot_viewport(chosen, epochs)
        self._plot_signature = signature
        existing, shared = self._retain_result_axes(chosen, epochs, previous_mode)
        actual_binaries = [
            (
                name.startswith("classifications/gait/")
                and metric in ("pred_gait_window", "pred_no_other_arm_activity_window")
            )
            or binary_indicator(self._plot_tables[name][metric], metric)
            for name, metric in chosen
        ]
        binaries = [False] * len(chosen) if epochs else actual_binaries
        self._size_result_canvas(chosen, binaries)
        first_axes = None
        grid = (
            self.figure.add_gridspec(
                len(chosen), 1, height_ratios=[0.34 if binary else 1 for binary in binaries]
            )
            if chosen
            else None
        )
        for index, (name, metric) in enumerate(chosen):
            ax = existing.get((name, metric))
            if ax is not None:
                ax.set_subplotspec(grid[index])
                self.figure.add_axes(ax)
                if ax is not shared:
                    ax.sharex(shared)
            else:
                ax = style_axes(self.figure, position=(grid[index],), sharex=shared or first_axes)
            if first_axes is None:
                first_axes = ax
            if (name, metric) in existing:
                continue
            self._render_result_series(ax, name, metric, actual_binaries[index], epochs)
        self._finish_result_plot(first_axes, shared, viewport, previous_y)

    def _result_plot_viewport(self, chosen, epochs):
        previous_mode, previous_chosen = self._plot_signature or (None, ())
        changed = set(chosen).symmetric_difference(previous_chosen)
        coverage_only = (
            self._plot_signature is not None
            and bool(changed)
            and epochs == previous_mode
            and bool(set(chosen).intersection(previous_chosen))
            and all(name.startswith("preparation/") for name, metric in changed)
        )
        viewport = None
        previous_y = {}
        if self._plot_signature is not None and self.figure.axes:
            source = self.figure.axes[0]
            if coverage_only or not source.get_autoscalex_on():
                viewport = source.get_xlim(), source.get_autoscalex_on()
            if coverage_only:
                previous_y = {
                    (ax._paradigma_dataset, ax._paradigma_metric): (
                        ax.get_ylim(),
                        ax.get_autoscaley_on(),
                    )
                    for ax in self.figure.axes
                    if hasattr(ax, "_paradigma_dataset")
                }
        return previous_mode, viewport, previous_y

    def _retain_result_axes(self, chosen, epochs, previous_mode):
        self.result_overlay.invalidate()
        for artist in self._result_selection_artists:
            artist.remove()
        self._result_selection_artists = []
        existing = {
            (ax._paradigma_dataset, ax._paradigma_metric): ax
            for ax in self.figure.axes
            if hasattr(ax, "_paradigma_dataset")
        }
        # Keep already plotted arrays, paths and axes settings when adding a
        # series. A changed result or view still needs fresh scientific data.
        shared = self._result_shared_axes
        reuse = (
            previous_mode == epochs
            and shared in self.figure.axes
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
            for ax in tuple(self.figure.axes):
                self.figure.delaxes(ax)
            existing = {key: ax for key, ax in existing.items() if key in chosen}
        else:
            self.figure.clear()
            existing = {}
            shared = None
        return existing, shared

    def _size_result_canvas(self, chosen, binaries):
        compact_states = bool(binaries) and all(binaries)
        height = max(
            88 if compact_states else 190, sum(62 if binary else 155 for binary in binaries)
        )
        self.canvas.setMinimumHeight(height)
        self.canvas.setMaximumHeight(height if compact_states else 16777215)
        self.graphs_workspace.setMinimumHeight(280 if binaries and all(binaries) else 310)
        if not chosen:
            ax = style_axes(self.figure)
            ax.text(
                0.5,
                0.5,
                "Select metrics to plot",
                ha="center",
                transform=ax.transAxes,
                color="#68778c",
            )

    def _render_result_series(self, ax, name, metric, binary, epochs):
        ax._paradigma_dataset = name
        ax._paradigma_metric = metric
        selected, positions = self._detail_selections.get(
            name, (self._plot_tables[name].iloc[:0], np.array([], dtype=int))
        )
        times = self._timings[name]["Timeline time (s)"].to_numpy()[positions]
        percentage = binary or name.startswith("preparation/")
        ys = self._plot_tables[name][metric].iloc[positions].to_numpy(dtype=float, na_value=np.nan)
        xs = clock_times(times, self.display_clock)
        ax._paradigma_epoch = epochs
        if epochs:
            self._render_epoch_series(ax, name, metric, positions, binary, percentage)
        elif len(selected) and np.isfinite(times).any():
            color = module_color(
                "preparation" if name.startswith("preparation/") else name.split("/")[1]
            )
            if binary:
                self._render_binary_series(ax, name, metric, positions, xs, ys, color)
            else:
                starts, ends = self._bar_bounds[name]
                plot_bars(
                    ax,
                    clock_times(starts[positions], self.display_clock),
                    clock_times(ends[positions], self.display_clock),
                    ys,
                    color,
                )
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

    def _render_epoch_series(self, ax, name, metric, positions, binary, percentage):
        summary = self.epoch_plot_data(name, metric, positions, binary)
        ax._paradigma_epoch_data = summary
        color = module_color(
            "preparation" if name.startswith("preparation/") else name.split("/")[1]
        )
        if len(summary):
            plot_bars(
                ax,
                clock_times(summary.start_s, self.display_clock),
                clock_times(summary.end_s, self.display_clock),
                summary.value,
                color,
            )
        if not len(summary) or not np.isfinite(summary.value).any():
            if "presence_s" in summary:
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
        if percentage:
            ax.set_ylim(0, 100)

    def _render_binary_series(self, ax, name, metric, positions, xs, ys, color):
        if (
            name == "classifications/gait/arm_activity"
            and metric == "pred_no_other_arm_activity_window"
        ):
            presence = self.gait_plot_presence()
            pairs = presence["filtered"]
            plot_states(
                ax,
                clock_times(pairs[:, 0], self.display_clock),
                np.ones(len(pairs)),
                color,
                ends=clock_times(pairs[:, 1], self.display_clock),
            )
            domain = presence["domain"]
            if len(domain):
                extent = time_coordinates(
                    clock_times([domain[:, 0].min(), domain[:, 1].max()], self.display_clock)
                )
                ax.update_datalim(np.column_stack((extent, [1, 1])))
                ax.autoscale_view(scaley=False)
        else:
            stops = clock_times(self._interval_ends[name][positions], self.display_clock)
            plot_states(ax, xs, ys, color, ends=stops)

    def _style_result_series(self, ax, name, metric, binary, epochs, percentage):
        if epochs or not binary:
            ax.set_ylabel(
                ("Availability (%)" if name.startswith("preparation/") else "Presence (%)")
                if epochs and percentage
                else "Median"
                if epochs
                else str(metric).replace("_", " "),
                fontsize=9,
            )
        item = self._series_items.get((name, metric))
        metric_title = (
            item.text(0)
            if item is not None
            else self._plot_labels.get((name, metric), str(metric).replace("_", " "))
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
        if self.display_clock is not None:
            timezone = clock_origin(self.display_clock).tz
            locator = RecordingDateLocator(tz=timezone)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(RecordingTimeFormatter(timezone))
            ax.set_xlabel(
                f"Recording time ({self.display_clock.get('timezone') or 'timezone unspecified'})"
            )
            ax.format_xdata = lambda value, tz=timezone: dates.num2date(value, tz=tz).strftime(
                "%d %b %Y %H:%M:%S"
            )
        else:
            ax.set_xlabel(
                "File-order timeline (s)"
                if len(self.provenance.get("sources", {})) > 1
                else "Elapsed analysis time (s)"
            )
        ax.tick_params(axis="x", labelbottom=False)
        ax.xaxis.label.set_visible(False)
        ax.xaxis.offsetText.set_visible(False)

    def _finish_result_plot(self, first_axes, shared, viewport, previous_y):
        # Recompute the shared full extent even if the retained master was
        # zoomed. The current zoom is restored below, while Home sees all data.
        self._result_shared_axes = shared or first_axes
        if first_axes is not None:
            first_axes.set_autoscalex_on(True)
            first_axes.autoscale_view(scaley=False)
        # Shared X limits settle only after every series has been added.
        # Fit each automatic Y range against that final shared view.
        for ax in self.figure.axes:
            autoscale_bars(ax)
        self.time_axis.bind(first_axes)
        self.plot_toolbar.refresh()
        if viewport is not None and first_axes is not None:
            # Keep Home as the full extent, while coverage toggles retain the
            # user's current view instead of making outcomes appear to change.
            self.plot_toolbar.push_current()
            limits, automatic_x = viewport
            first_axes.set_xlim(*limits, auto=automatic_x)
            for ax in self.figure.axes:
                previous = previous_y.get((ax._paradigma_dataset, ax._paradigma_metric))
                if previous is not None and not previous[1]:
                    ax.set_ylim(*previous[0], auto=False)
                autoscale_bars(ax)
            self.plot_toolbar.push_current()
        self.highlight_result_row()
        self.canvas.draw_idle()

    def result_row_changed(self, current, previous):
        import pandas as pd

        frame = self.active_frame
        valid_row = current.isValid() and frame is not None
        timestamp = (
            valid_row
            and "time" in frame
            and pd.api.types.is_numeric_dtype(frame["time"].dtype)
            and pd.notna(frame["time"].iloc[current.row()])
            and np.isfinite(frame["time"].iloc[current.row()])
        )
        segment = (
            gait_context(self.results, self.dataset.currentText(), frame.iloc[current.row()])
            if valid_row
            else None
        )
        usable = self.result_source_frame is not None and (timestamp or segment is not None)
        self.context_button.setEnabled(bool(usable))
        self.context_button.setText(
            "Inspect gait segment"
            if segment is not None and not timestamp
            else "Inspect sensor context"
        )
        if valid_row:
            self.context_button.setToolTip("")
        if valid_row and not timestamp and segment is None:
            self.context_button.setToolTip("No sensor timing available")
        if self.result_source_frame is None:
            self.context_button.setToolTip("Original sensor data unavailable")
        self.highlight_result_row()

    def highlight_result_row(self):
        with self.result_overlay.edit():
            self.update_result_marker()
        self.result_overlay.paint()

    def update_result_marker(self):
        """Link a table row to all plots without changing their data or limits."""
        for artist in self._result_selection_artists:
            artist.remove()
        self._result_selection_artists = []
        self.time_axis.set_selection(None)
        name, frame = self.dataset.currentText(), self.active_frame
        current = self.result_table.currentIndex()
        if frame is None or not current.isValid() or name not in self._timings:
            return
        row = current.row()
        position = self.active_positions[row]
        timing = self._timings[name].iloc[position]
        seconds = float(timing["Timeline time (s)"])
        if not np.isfinite(seconds):
            return
        if self.display_clock is not None:
            timestamp = clock_times([seconds], self.display_clock)[0]
            x = float(dates.date2num(timestamp.to_pydatetime(warn=False)))
            label = timestamp.strftime("%d %b %Y %H:%M:%S.%f").rstrip("0").rstrip(".")
        else:
            x, label = seconds, f"{seconds:.6g} s"
        self.time_axis.set_selection(x, label)
        for ax in self.figure.axes:
            if not hasattr(ax, "_paradigma_dataset"):
                continue
            line = time_selection_line(ax, x, animated=self.canvas.supports_blit)
            self._result_selection_artists.append(line)
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
            value = self._plot_tables[name][ax._paradigma_metric].iloc[self.active_positions[row]]
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
        point.set_animated(self.canvas.supports_blit)
        ax.add_artist(point)
        self._result_selection_artists.append(point)

    def graph_clicked(self, event):
        if event.inaxes is None or event.xdata is None or self.plot_toolbar.mode:
            return
        name = getattr(event.inaxes, "_paradigma_dataset", self.dataset.currentText())
        if name not in self.tables:
            return
        anchor = self._graph_click_anchor(name, event.xdata)
        self.dataset.setCurrentText(name)
        self.sync_table_outputs(force_detail=True)
        metric = getattr(event.inaxes, "_paradigma_metric", None)
        if metric is not None:
            self.y_column.blockSignals(True)
            self.y_column.setCurrentIndex(self.y_column.findData(metric))
            self.y_column.blockSignals(False)
        frame = self.active_frame
        if frame is None or frame.empty:
            return
        row = self._graph_click_row(event.inaxes, name, metric, anchor)
        if row is None:
            return
        self.result_table.setCurrentIndex(self.result_table.model().index(row, 0))
        self.result_table.selectRow(row)
        self.result_table.scrollTo(self.result_table.currentIndex())
        self.plot_toolbar.active_axes = next(
            (
                ax
                for ax in self.figure.axes
                if getattr(ax, "_paradigma_dataset", None) == name
                and getattr(ax, "_paradigma_metric", None) == metric
            ),
            None,
        )
        if self.plot_toolbar.settings_action.isChecked():
            self.plot_toolbar.settings.read_axes()

    def _graph_click_anchor(self, name, xdata):
        import pandas as pd

        anchor = float(xdata)
        if self.display_clock is not None:
            anchor = (anchor - dates.date2num(pd.Timestamp(self.display_clock["origin"]))) * 86400
            # Matplotlib stores dates as floats in days; recover exact nearby
            # output anchors before choosing the interval that contains a click.
            all_times = self._timings[name]["Timeline time (s)"].to_numpy()
            close = np.flatnonzero(np.isfinite(all_times) & (np.abs(all_times - anchor) < 1e-5))
            if len(close):
                anchor = float(all_times[close[0]])
        return anchor

    def _graph_click_row(self, ax, name, metric, anchor):
        """Resolve clicks against unchanged source positions and interval bounds."""
        times = self._timings[name]["Timeline time (s)"].to_numpy()[self.active_positions]
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
                self._plot_tables[name][metric]
                .iloc[self.active_positions]
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
        ) and metric in self._plot_tables[name]:
            ends = self._interval_ends[name][self.active_positions]
            present = (
                self._plot_tables[name][metric]
                .iloc[self.active_positions]
                .eq(1)
                .fillna(False)
                .to_numpy(dtype=bool)
            )
            if getattr(ax, "_paradigma_bars", False):
                starts, all_ends = self._bar_bounds[name]
                times, ends = starts[self.active_positions], all_ends[self.active_positions]
                present = (
                    self._plot_tables[name][metric].iloc[self.active_positions].notna().to_numpy()
                )
            covering = np.flatnonzero(present & (times <= anchor) & (anchor < ends))
            if len(covering):
                row = int(covering[-1])
        return row
