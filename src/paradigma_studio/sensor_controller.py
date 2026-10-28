"""Sensor inspection/navigation with explicit result state and plotting services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from weakref import ref

import numpy as np
from PySide6.QtCore import Qt

from .channels import mark_sensor_time
from .exploration import SensorContext, gait_context, source_timeline
from .recordings import source_key
from .results_view import clock_origin, clock_times
from .sensor_navigation import SensorNavigator, SensorTimeIndex
from .widgets import FrameModel
from .workspace_state import ResultState, SensorState

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    from PySide6.QtWidgets import QComboBox, QLabel, QListWidget, QPushButton, QTabWidget

    from .raw_navigation import RawToolbar
    from .widgets import ReadableTable


@dataclass(frozen=True)
class SensorView:
    result_table: ReadableTable
    context_button: QPushButton
    dataset: QComboBox
    result_tabs: QTabWidget
    sensor_tab_index: int
    status: QLabel
    sensor_tabs: QTabWidget
    sensor_table: ReadableTable
    sensor_channels: QListWidget
    sensor_figure: Figure
    sensor_toolbar: RawToolbar
    sensor_canvas: FigureCanvasQTAgg


@dataclass(frozen=True)
class ChannelServices:
    selected_channels: Callable[[QListWidget], list[str]]
    check_channels: Callable[[QListWidget, list[str]], None]
    populate_channels: Callable[..., dict[str, str | tuple[float, ...] | np.ndarray]]
    plot_channel_signals: Callable[..., None]


class SensorController:
    def __init__(
        self, state: SensorState, results: ResultState, view: SensorView, channels: ChannelServices
    ):
        self.state, self.results, self.view, self.channels = state, results, view, channels
        self._plotted_source: ref[SensorNavigator | pd.DataFrame] | None = None
        self.view.sensor_tabs.currentChanged.connect(self.refresh_sensor_table)

    def inspect_sensor_context(self):
        import pandas as pd

        row = self.view.result_table.currentIndex().row()
        if not self.view.context_button.isEnabled() or row < 0:
            return
        try:
            selected = self.results.active_frame.iloc[row]
            parts = self.view.dataset.currentText().split("/")
            module = parts[1] if len(parts) > 1 else ""
            source_frame = self.results.result_source_frame
            if isinstance(source_frame, dict):
                key = source_key(selected.get("file_key"), self.results.results)
                source_frame = source_frame[key]
                common = self.results.result_timeline[key]
                module_timeline = self.results._source_timelines.get(module, {}).get(key, common)
                index = self.sensor_time_index(common, self.results._recording_bases[key])
                display_timeline = index.times
            else:
                if self.results.result_timeline is None:
                    self.results.result_timeline = source_timeline(
                        source_frame, self.results.provenance.get("settings", {})
                    )
                module_timeline = self.results._source_timelines.get(
                    module, self.results.result_timeline
                )
                index = self.sensor_time_index(self.results.result_timeline)
                display_timeline = index.times
            segment = gait_context(self.results.results, self.view.dataset.currentText(), selected)
            if "time" in selected and pd.notna(selected["time"]):
                anchor = float(selected["time"])
                radius = 10.0
                start, end = anchor - radius, anchor + radius
                include_end = True
            elif segment is not None:
                start, end, _ = segment
                include_end = False
            else:
                raise ValueError("No explicit sensor time context is available.")
            source_name = ""
            if isinstance(self.results.result_source_frame, dict):
                path = self.results.provenance.get("sources", {}).get(key, key)
                source_name = Path(path).name
            timing = self.results._timings[self.view.dataset.currentText()].iloc[
                self.results.active_positions[row]
            ]
            self.state._sensor_context = SensorContext(
                source_frame,
                module_timeline,
                display_timeline,
                start,
                end,
                float(timing["Timeline time (s)"]),
                source_name=source_name,
                include_end=include_end,
            )
            self.state._sensor_navigator = SensorNavigator(
                self.state._sensor_context, self.results.display_clock, index=index
            )
            self.show_sensor_context()
            self.view.result_tabs.setTabVisible(self.view.sensor_tab_index, True)
            self.view.result_tabs.setCurrentIndex(self.view.sensor_tab_index)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            message = f"Sensor context unavailable: {exc}"
            self.view.context_button.setToolTip(message)
            self.view.status.setText(message)

    def show_sensor_context(self):
        context = self.state._sensor_context
        positions = context.positions()
        self.state.sensor_frame = context.frame.iloc[positions]
        self.state.sensor_times = context.display_times[positions]
        self.refresh_sensor_table()
        self.populate_sensor_channels()
        self.plot_sensor()

    def refresh_sensor_table(self) -> None:
        """Size the latest samples only when Tables is selected, once per frame."""
        if self.view.sensor_tabs.currentWidget() is not self.view.sensor_table:
            return
        frame = self.state.sensor_frame
        model = self.view.sensor_table.model()
        if frame is not None and (model is None or model.frame is not frame):
            self.view.sensor_table.setModel(FrameModel(frame))

    def sensor_time_index(self, times, offset=0.0):
        key = id(times), offset
        if key not in self.state._sensor_time_indices:
            display = np.asarray(times, dtype=float)
            if offset:
                display = display + offset
            # Retain the timeline reference so a later array cannot reuse its id.
            self.state._sensor_time_indices[key] = times, SensorTimeIndex(display)
        self.state._sensor_time_indices.move_to_end(key)
        while len(self.state._sensor_time_indices) > 4:
            self.state._sensor_time_indices.popitem(last=False)
        return self.state._sensor_time_indices[key][1]

    def update_sensor_view(self, axes):
        navigator = self.state._sensor_navigator
        if navigator is None or axes not in self.view.sensor_figure.axes:
            return
        limits = navigator.bounded_limits(axes.get_xlim())
        if tuple(axes.get_xlim()) != limits:
            axes.set_xlim(*limits, emit=False)
        if limits == navigator.limits:
            return
        navigator.limits = limits
        positions = navigator.positions(limits)
        self.update_sensor_samples(positions, limits)

    def update_sensor_samples(self, positions, limits):
        from .raw_signals import RawSignalTime, update_raw_signal

        navigator = self.state._sensor_navigator
        self.state.sensor_frame = navigator.context.frame.iloc[positions]
        self.state.sensor_times = navigator.context.display_times[positions]
        self.refresh_sensor_table()
        xs = navigator.coordinates_at(self.state.sensor_times)
        time_index = RawSignalTime(xs)
        channels = self.selected_sensor_channels()
        for ax in self.view.sensor_figure.axes:
            for line in ax.lines:
                if line.get_label() in channels and line.get_gid() is None:
                    update_raw_signal(line, time_index, self.state.sensor_frame[line.get_label()])
                elif line.get_gid() is not None:
                    line.set_visible(limits[0] <= navigator.anchor <= limits[1])
            for collection in ax.collections:
                if collection.get_label() in channels:
                    present = (
                        self.state.sensor_frame[collection.get_label()]
                        .eq(1)
                        .fillna(False)
                        .to_numpy(dtype=bool)
                    )
                    collection.set_offsets(np.column_stack((xs[present], np.ones(present.sum()))))
            for text in ax.texts:
                if text.get_gid() == "sensor-no-data":
                    text.set_visible(self.state.sensor_frame.empty)
                elif text.get_gid() == "selected-result-label":
                    text.set_visible(limits[0] <= navigator.anchor <= limits[1])
            ax.relim()

    def reset_sensor_context(self):
        navigator = self.state._sensor_navigator
        if navigator is None or navigator.home_limits is None:
            return
        self.view.sensor_toolbar.push_current()
        navigator.limits = navigator.home_limits
        for ax in self.view.sensor_figure.axes:
            ax.set_xlim(*navigator.home_limits, emit=False)
        self.update_sensor_samples(navigator.context.positions(), navigator.home_limits)
        for ax in self.view.sensor_figure.axes:
            if any(line.get_gid() is None for line in ax.lines):
                ax.set_autoscaley_on(True)
                ax.autoscale_view(scalex=False, scaley=True)
        self.view.sensor_toolbar.push_current()
        if self.view.sensor_toolbar.settings_action.isChecked():
            self.view.sensor_toolbar.settings.read_axes()
        self.view.sensor_canvas.draw_idle()

    def hide_sensor_context(self):
        if self.view.result_tabs.currentIndex() == self.view.sensor_tab_index:
            self.view.result_tabs.setCurrentIndex(1)
        self.view.result_tabs.setTabVisible(self.view.sensor_tab_index, False)

    def selected_sensor_channels(self):
        return self.channels.selected_channels(self.view.sensor_channels)

    def set_sensor_channels(self, channels):
        self.channels.check_channels(self.view.sensor_channels, channels)
        self.plot_sensor()

    def populate_sensor_channels(self):
        selection = self.selected_sensor_channels() if self.view.sensor_channels.count() else None
        mapping = self.results.provenance.get("settings", {}).get("column_mapping", {})
        self.state._sensor_channel_colors = self.channels.populate_channels(
            self.view.sensor_channels,
            self.state.sensor_frame,
            excluded={column for column, target in mapping.items() if target == "time"},
            selection=selection,
        )
        # Keep the chosen channels across context windows. A different recording
        # with no matching channels gets its first channel; an explicit Clear
        # remains empty until the user selects channels again.
        if selection and not self.selected_sensor_channels() and self.view.sensor_channels.count():
            self.channels.check_channels(
                self.view.sensor_channels, [self.view.sensor_channels.item(0).data(Qt.UserRole)]
            )

    def plot_sensor(self, *_):
        # Clearing axes emits limit changes. These belong to the old figure,
        # not a user pan, and must not replace the current context samples.
        self.disconnect_sensor_view()
        context = self.state._sensor_context
        navigator = self._prepare_sensor_navigator(context)
        view_limits = navigator.limits if navigator is not None else None
        source = navigator if navigator is not None else self.state.sensor_frame
        with self.view.sensor_toolbar.redraw_channels(
            preserve_view=source is not None
            and self._plotted_source is not None
            and source is self._plotted_source(),
            time_limits=navigator.source_limits if navigator is not None else None,
        ):
            self._render_sensor_channels()
            self._restore_sensor_navigation(context, navigator, view_limits)
        self._plotted_source = ref(source) if source is not None else None
        self.view.sensor_canvas.draw_idle()

    def _prepare_sensor_navigator(self, context: SensorContext | None) -> SensorNavigator | None:
        navigator = self.state._sensor_navigator
        if context is not None and (
            navigator is None
            or navigator.context is not context
            or navigator.clock != self.results.display_clock
        ):
            navigator = self.state._sensor_navigator = SensorNavigator(
                context,
                self.results.display_clock,
                index=self.sensor_time_index(context.display_times),
            )
        return navigator

    def _render_sensor_channels(self) -> None:
        xs = (
            clock_times(self.state.sensor_times, self.results.display_clock)
            if self.state.sensor_frame is not None
            else []
        )
        calendar = self.results.display_clock is not None
        settings = self.results.provenance.get("settings", {})
        self.channels.plot_channel_signals(
            self.view.sensor_figure,
            self.state.sensor_frame,
            self.selected_sensor_channels(),
            self.state._sensor_channel_colors,
            xs,
            "Recording date/time" if calendar else "Analysis time (s)",
            column_mapping=settings.get("column_mapping", {}),
            sensor_units={
                "Accelerometer": settings.get("accelerometer_units"),
                "Gyroscope": settings.get("gyroscope_units"),
            },
            calendar=calendar,
            timezone=clock_origin(self.results.display_clock).tz if calendar else None,
            allow_empty=self.state._sensor_context is not None,
            empty_schema=self.state._sensor_context.frame
            if self.state._sensor_context is not None
            else None,
        )

    def _restore_sensor_navigation(
        self,
        context: SensorContext | None,
        navigator: SensorNavigator | None,
        view_limits: tuple[float, float] | None,
    ) -> None:
        if context is not None and self.selected_sensor_channels():
            mark_sensor_time(
                self.view.sensor_figure, context.selected_time, self.results.display_clock
            )
            if navigator is not None:
                if view_limits is not None or self.state.sensor_frame.empty:
                    for ax in self.view.sensor_figure.axes:
                        ax.set_xlim(*(view_limits or navigator.initial_limits), emit=False)
                navigator.limits = navigator.bounded_limits(
                    self.view.sensor_figure.axes[0].get_xlim()
                )
                automatic_x = self.view.sensor_figure.axes[0].get_autoscalex_on() and (
                    navigator.limits == navigator.source_limits
                )
                for ax in self.view.sensor_figure.axes:
                    ax.set_xlim(*navigator.limits, emit=False, auto=automatic_x)
                if navigator.home_limits is None:
                    navigator.home_limits = navigator.limits
                for ax in self.view.sensor_figure.axes:
                    for artist in [*ax.lines, *ax.texts]:
                        if artist.get_gid() is not None:
                            artist.set_visible(
                                navigator.limits[0] <= navigator.anchor <= navigator.limits[1]
                            )
                    self.state._sensor_view_callbacks[ax] = ax.callbacks.connect(
                        "xlim_changed", self.update_sensor_view
                    )
                    message = ax.text(
                        0.5,
                        0.5,
                        "No original samples in this context",
                        ha="center",
                        transform=ax.transAxes,
                        color="#60728A",
                    )
                    message.set_gid("sensor-no-data")
                    message.set_visible(self.state.sensor_frame.empty)

    def disconnect_sensor_view(self):
        for ax, callback in self.state._sensor_view_callbacks.items():
            ax.callbacks.disconnect(callback)
        self.state._sensor_view_callbacks.clear()
