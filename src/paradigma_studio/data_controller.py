"""Recording loading, inspection previews and raw graph controls."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QWidget,
)

from .core import (
    validate_column_mapping,
)
from .sensor_controller import ChannelServices
from .ui.graph_views import ChannelCanvasView
from .widgets import FrameModel, ReadableTable
from .workspace_state import AnalysisState, DataState, InputState, JobState, PreviewServices


@dataclass(frozen=True)
class DataView:
    parent: QWidget
    analysis_input: QLabel
    analysis_input_detail: QLabel
    channel_table: ReadableTable
    continue_button: QPushButton
    data_channels: QListWidget
    data_tabs: QTabWidget
    data_time_channel: QComboBox
    data_time_unit: QComboBox
    data_values: list[QLabel]
    file_label: QLabel
    input_recording: QComboBox
    input_table: ReadableTable
    mapping: QPlainTextEdit
    pages: QStackedWidget
    status: QLabel
    time: QComboBox
    time_table: ReadableTable
    data_graphics: Callable[[], ChannelCanvasView]

    @property
    def data_canvas(self):
        return self.data_graphics().canvas

    @property
    def data_figure(self):
        return self.data_graphics().figure

    @property
    def data_toolbar(self):
        return self.data_graphics().toolbar


@dataclass(frozen=True)
class DataCallbacks:
    append_log: Callable[..., Any]
    modules_changed: Callable[..., Any]
    navigate: Callable[..., Any]
    show_notice: Callable[..., Any]
    start_job: Callable[..., Any]


@dataclass(frozen=True)
class DataServices:
    load_recordings: Callable[..., Any]
    inspect_recording: Callable[..., Any]
    sensor_descriptives: Callable[..., Any]
    time_descriptives: Callable[..., Any]
    input_plot_time: Callable[..., Any]


class DataController(QObject):
    """Own data behavior through explicit state, frozen views and callbacks."""

    def __init__(
        self,
        analysis: AnalysisState,
        state: DataState,
        inputs: InputState,
        jobs: JobState,
        view: DataView,
        callbacks: DataCallbacks,
        services: DataServices,
        channels: ChannelServices,
        previews: PreviewServices,
    ) -> None:
        super().__init__(view.parent)
        self.analysis = analysis
        self.state = state
        self.inputs = inputs
        self.jobs = jobs
        self.view = view
        self.callbacks = callbacks
        self.services = services
        self.channels = channels
        self.previews = previews

    def open_file(self):
        if self.jobs.worker is not None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self.view.parent,
            "Open recordings for the same subject",
            "",
            "Sensor files (*.csv *.parquet *.pkl *.pickle *.json *.avro *.cwa *.CWA);;All files (*)",
        )
        if not paths:
            return
        allow_pickle = False
        if any(Path(path).suffix.lower() in (".pkl", ".pickle") for path in paths):
            reply = QMessageBox.warning(
                self.view.parent,
                "Trusted pickle files only",
                "Pickle files can execute code when opened. Only continue if you trust every selected pickle file's source.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            allow_pickle = True
        self.callbacks.show_notice("")
        self.view.status.setText("Loading recordings…")
        unit = self.view.time.currentText()

        def load(logger):
            sources, frames = self.services.load_recordings(
                paths, allow_pickle=allow_pickle, logger=logger
            )
            descriptions = {
                key: self.services.inspect_recording(frame, unit) for key, frame in frames.items()
            }
            return sources, frames, descriptions

        self.callbacks.start_job(load, self.loaded_recordings)

    def loaded_recordings(self, payload):
        sources, recordings, descriptions = payload
        if len(recordings) == 1:
            key = next(iter(recordings))
            self.loaded((sources[key], recordings[key], descriptions[key]))
            return
        self.previews._origin_preview.clear()
        self.previews._time_preview.clear()
        self.previews._sensor_preview.clear()
        self.view.input_recording.blockSignals(True)
        self.view.input_recording.clear()
        for key, path in sources.items():
            self.view.input_recording.addItem(f"{key} · {Path(path).name}", key)
            self.view.input_recording.setItemData(
                self.view.input_recording.count() - 1, path, Qt.ToolTipRole
            )
        self.view.input_recording.blockSignals(False)
        self.inputs.sources, self.inputs.recordings = sources, recordings
        self.state._input_descriptions = descriptions
        self.analysis._origin_override = False
        self.inspect_input_recording(new_selection=True)
        self.callbacks.modules_changed()
        self.view.status.setText(f"{len(recordings)} recordings loaded for one subject.")

    def inspect_input_recording(self, *_, new_selection=False):
        key = self.view.input_recording.currentData()
        if key not in self.inputs.recordings:
            return
        self.inputs.source, self.inputs.frame = (
            self.inputs.sources[key],
            self.inputs.recordings[key],
        )
        self.display_input_recording(
            self.state._input_descriptions[key], new_selection=new_selection
        )
        self.view.input_recording.show()
        self.view.file_label.setText(f"{len(self.inputs.recordings)} recordings")
        self.view.file_label.setToolTip("\n".join(self.inputs.sources.values()))
        self.view.analysis_input.setText(f"{len(self.inputs.recordings)} recordings · One subject")
        self.view.analysis_input_detail.setText(
            f"{sum(len(frame) for frame in self.inputs.recordings.values()):,} samples"
        )

    def loaded(self, payload):
        self.previews._origin_preview.clear()
        self.previews._time_preview.clear()
        self.previews._sensor_preview.clear()
        self.inputs.source, self.inputs.frame = payload[:2]
        self.analysis._origin_override = False
        self.inputs.sources, self.inputs.recordings = {"recording_001": self.inputs.source}, {}
        self.state._input_descriptions = {}
        self.view.input_recording.hide()
        description = (
            payload[2]
            if len(payload) > 2
            else self.services.inspect_recording(self.inputs.frame, self.view.time.currentText())
        )
        self.display_input_recording(description, new_selection=True)
        self.callbacks.modules_changed()
        self.callbacks.show_notice("")
        self.callbacks.navigate(0)
        if self.inputs.frame.attrs.get("source_format") == "empatica" and not any(
            f"gyroscope_{axis}" in self.inputs.frame for axis in "xyz"
        ):
            message = (
                "Empatica accelerometer samples loaded. Gait and tremor require gyroscope data; "
                "pulse rate requires raw green PPG. This import contains neither."
            )
            self.view.status.setText(message)
            self.callbacks.show_notice(message)
            self.callbacks.append_log(message)
        else:
            self.view.status.setText("Recording loaded.")

    def display_input_recording(self, description, *, new_selection):
        """Refresh inspection only; changing the viewed file never realigns the batch."""
        self.previews._time_preview.cancel_pending()
        self.view.time_table.setEnabled(True)
        self.previews._sensor_preview.cancel_pending()
        self.view.channel_table.setEnabled(True)
        channels = None if new_selection else self.selected_input_channels()
        if new_selection:
            self.view.data_tabs.setCurrentIndex(0)
        self.view.input_table.setModel(FrameModel(self.inputs.frame))
        self.view.file_label.setText(Path(self.inputs.source).name)
        self.view.file_label.setToolTip(self.inputs.source)
        self.view.analysis_input.setText(Path(self.inputs.source).name)
        self.view.analysis_input_detail.setText(
            f"{len(self.inputs.frame):,} samples · {len(self.inputs.frame.columns)} channels"
        )
        self.view.data_values[0].setText(f"{len(self.inputs.frame):,}")
        self.view.data_values[1].setText(str(len(self.inputs.frame.columns)))
        self.view.data_values[2].setText(f"{description['missing']:,}")
        self.view.data_time_channel.blockSignals(True)
        self.view.data_time_channel.clear()
        for column in self.inputs.frame:
            self.view.data_time_channel.addItem(str(column), column)
        self.view.data_time_channel.setCurrentIndex(
            self.view.data_time_channel.findData(description["time_column"])
        )
        self.view.data_time_channel.blockSignals(False)
        self.view.data_time_unit.blockSignals(True)
        self.view.data_time_unit.setCurrentText(description["time_unit"])
        self.view.data_time_unit.blockSignals(False)
        self.view.channel_table.setModel(FrameModel(description["sensors"], compact=True))
        self.view.time_table.setModel(
            FrameModel(description["time"], compact=True)
            if description["time"] is not None
            else None
        )
        self.update_time_unit_control()
        self.populate_input_channels(channels)
        if new_selection or self.view.data_tabs.currentIndex() == 1:
            self.plot_input()
        else:
            self.state._data_plot_dirty = True
        self.view.continue_button.setEnabled(True)

    def data_tab_changed(self, index):
        if index == 1 and self.state._data_plot_dirty:
            self.plot_input()

    def update_time_unit_control(self):
        import pandas as pd

        column = self.view.data_time_channel.currentData()
        numeric_time = (
            self.inputs.frame is not None
            and column in self.inputs.frame
            and not (
                pd.api.types.is_datetime64_any_dtype(self.inputs.frame[column].dtype)
                or pd.api.types.is_timedelta64_dtype(self.inputs.frame[column].dtype)
            )
        )
        self.view.data_time_unit.setVisible(numeric_time)
        self.view.data_time_unit.setEnabled(self.jobs.worker is None)

    def refresh_data_descriptives(self, *_):
        if self.inputs.frame is not None:
            frame, column = self.inputs.frame, self.view.data_time_channel.currentData()
            self.view.channel_table.setEnabled(False)
            self.previews._sensor_preview.request(
                (self.inputs.source, column),
                lambda: self.services.sensor_descriptives(frame, column),
            )
            self.populate_input_channels(self.selected_input_channels())
            self.update_time_statistics()
            if self.view.data_tabs.currentIndex() == 1:
                self.plot_input()
            else:
                self.state._data_plot_dirty = True

    def apply_sensor_preview(self, description):
        self.view.channel_table.setModel(
            FrameModel(description, compact=True) if description is not None else None
        )
        self.view.channel_table.setEnabled(True)

    def update_time_statistics(self, *_):
        column = self.view.data_time_channel.currentData()
        if self.inputs.frame is not None and column in self.inputs.frame:
            frame, unit = self.inputs.frame, self.view.data_time_unit.currentText()
            self.view.time_table.setEnabled(False)
            self.previews._time_preview.request(
                (self.inputs.source, column, unit),
                lambda: self.services.time_descriptives(frame[column], unit),
            )
        else:
            self.previews._time_preview.cancel_pending()
            self.view.time_table.setModel(None)
            self.view.time_table.setEnabled(True)
        self.update_time_unit_control()

    def apply_time_preview(self, description):
        self.view.time_table.setModel(
            FrameModel(description, compact=True) if description is not None else None
        )
        self.view.time_table.setEnabled(True)

    def selected_input_channels(self):
        return self.channels.selected_channels(self.view.data_channels)

    def set_input_channels(self, channels):
        self.channels.check_channels(self.view.data_channels, channels)
        self.plot_input()

    def populate_input_channels(self, selection=None):
        self.state._channel_colors = self.channels.populate_channels(
            self.view.data_channels,
            self.inputs.frame,
            excluded={self.view.data_time_channel.currentData()},
            selection=selection,
        )

    def input_plot_changed(self):
        self.state._data_plot_dirty = True
        if self.view.pages.currentIndex() == 0:
            self.data_tab_changed(self.view.data_tabs.currentIndex())

    def plot_input(self, *_):
        self.state._data_plot_dirty = False
        try:
            mapping = validate_column_mapping(json.loads(self.view.mapping.toPlainText()))
        except (ValueError, TypeError):
            # An incomplete Analyze mapping must not prevent original-data inspection.
            mapping = {}
        channels = self.selected_input_channels()
        times, time_label, timezone = None, "Time (file units)", None
        if self.inputs.frame is not None:
            import pandas as pd

            column = self.view.data_time_channel.currentData()
            if column in self.inputs.frame:
                times, time_label, timezone = self.services.input_plot_time(
                    self.inputs.frame[column], self.view.data_time_unit.currentText()
                )
        usable = times is not None and times.notna().all()
        xs = (
            times
            if usable
            else np.arange(len(self.inputs.frame))
            if self.inputs.frame is not None
            else []
        )
        self.channels.plot_channel_signals(
            self.view.data_figure,
            self.inputs.frame,
            channels,
            self.state._channel_colors,
            xs,
            time_label if usable else "Sample position",
            column_mapping=mapping,
            timezone=timezone,
            calendar=usable and pd.api.types.is_datetime64_any_dtype(times.dtype),
            empty_text="Open a recording with numeric sensor channels",
        )
        self.view.data_toolbar.refresh()
        self.view.data_canvas.draw_idle()
