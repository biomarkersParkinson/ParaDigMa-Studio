"""Recording loading, inspection previews and raw graph controls."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import numpy as np
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QWidget,
)

from .inspection import inspect_recordings
from .sensor_controller import ChannelServices
from .ui.column_mapping import ColumnMappingEditor
from .ui.graph_views import ChannelCanvasView
from .widgets import FrameModel, ReadableTable
from .workspace_state import AnalysisState, DataState, InputState, JobState, PreviewServices

if TYPE_CHECKING:
    import logging
    from datetime import tzinfo

    import pandas as pd
    from matplotlib.figure import Figure

    from .contracts import (
        NoticeCallback,
        PathInput,
        RecordingDescription,
        RecordingLoadPayload,
        RecordingsLoadPayload,
        StartJobCallback,
    )
    from .plot_controls import GraphToolbar
    from .plotting import ScrollableFigureCanvas


class RecordingsLoader(Protocol):
    def __call__(
        self,
        paths: Iterable[PathInput],
        *,
        allow_pickle: bool = False,
        logger: logging.Logger | None = None,
    ) -> tuple[dict[str, str], dict[str, pd.DataFrame]]: ...


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
    mapping: ColumnMappingEditor
    pages: QStackedWidget
    status: QLabel
    time_table: ReadableTable
    data_graphics: Callable[[], ChannelCanvasView]

    @property
    def data_canvas(self) -> ScrollableFigureCanvas:
        return self.data_graphics().canvas

    @property
    def data_figure(self) -> Figure:
        return self.data_graphics().figure

    @property
    def data_toolbar(self) -> GraphToolbar:
        return self.data_graphics().toolbar


@dataclass(frozen=True)
class DataCallbacks:
    append_log: Callable[[str], None]
    modules_changed: Callable[[], None]
    navigate: Callable[[int], None]
    show_notice: NoticeCallback
    start_job: StartJobCallback


@dataclass(frozen=True)
class DataServices:
    load_recordings: RecordingsLoader
    inspect_recording: Callable[[pd.DataFrame, str], RecordingDescription]
    sensor_descriptives: Callable[[pd.DataFrame, Hashable | None], pd.DataFrame]
    time_descriptives: Callable[[pd.Series, str], pd.DataFrame]
    input_plot_time: Callable[[pd.Series, str], tuple[pd.Series | None, str, tzinfo | None]]


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

    def open_file(self) -> None:
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
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            allow_pickle = True
        self.callbacks.show_notice("")
        self.view.status.setText("Loading recordings…")
        unit = self.view.data_time_unit.currentText()

        def load(logger: logging.Logger) -> RecordingsLoadPayload:
            sources, frames = self.services.load_recordings(
                paths, allow_pickle=allow_pickle, logger=logger
            )
            descriptions = inspect_recordings(
                frames, unit, describe=self.services.inspect_recording, logger=logger
            )
            return sources, frames, descriptions

        self.callbacks.start_job(load, self.loaded_recordings)

    def loaded_recordings(self, payload: RecordingsLoadPayload) -> None:
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
                self.view.input_recording.count() - 1, path, Qt.ItemDataRole.ToolTipRole
            )
        self.view.input_recording.blockSignals(False)
        self.inputs.sources, self.inputs.recordings = sources, recordings
        self._supply_mapping_schemas()
        self.state._input_descriptions = descriptions
        self.inspect_input_recording(new_selection=True)
        self.callbacks.modules_changed()
        self.view.status.setText(f"{len(recordings)} recordings loaded for one subject.")

    def inspect_input_recording(self, *_: object, new_selection: bool = False) -> None:
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

    def loaded(self, payload: RecordingLoadPayload) -> None:
        self.previews._origin_preview.clear()
        self.previews._time_preview.clear()
        self.previews._sensor_preview.clear()
        self.inputs.source, self.inputs.frame = payload[:2]
        self.inputs.sources, self.inputs.recordings = {"recording_001": self.inputs.source}, {}
        self._supply_mapping_schemas()
        self.state._input_descriptions = {}
        self.view.input_recording.hide()
        description = (
            payload[2]
            if len(payload) > 2
            else self.services.inspect_recording(
                self.inputs.frame, self.view.data_time_unit.currentText()
            )
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

    def _supply_mapping_schemas(self) -> None:
        frames = self.inputs.recordings or {
            "recording_001": cast("pd.DataFrame", self.inputs.frame)
        }
        self.view.mapping.set_recordings(
            {
                key: [column for column in frame.columns if isinstance(column, str)]
                for key, frame in frames.items()
            },
            {key: f"{key} · {Path(source).name}" for key, source in self.inputs.sources.items()},
        )

    def display_input_recording(
        self, description: RecordingDescription, *, new_selection: bool
    ) -> None:
        """Refresh inspection only; changing the viewed file never realigns the batch."""
        # Both load paths install the selected frame before refreshing its widgets.
        frame = cast("pd.DataFrame", self.inputs.frame)
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
            f"{len(frame):,} samples · {len(frame.columns)} channels"
        )
        self.view.data_values[0].setText(f"{len(frame):,}")
        self.view.data_values[1].setText(str(len(frame.columns)))
        self.view.data_values[2].setText(f"{description['missing']:,}")
        self.view.data_time_channel.blockSignals(True)
        self.view.data_time_channel.clear()
        for column in frame:
            self.view.data_time_channel.addItem(str(column), column)
        self.view.data_time_channel.setCurrentIndex(
            self.view.data_time_channel.findData(description["time_column"])
        )
        self.view.data_time_channel.blockSignals(False)
        # The Data format is shared by the batch; cached descriptions retain
        # their load-time format and must never overwrite the user's selection.
        self.view.channel_table.setModel(FrameModel(description["sensors"], compact=True))
        self.view.time_table.setModel(
            FrameModel(description["time"], compact=True)
            if description["time"] is not None
            and description["time_unit"] == self.view.data_time_unit.currentText()
            else None
        )
        if description["time_unit"] != self.view.data_time_unit.currentText():
            self.update_time_statistics()
        else:
            self.update_time_unit_control()
        self.populate_input_channels(channels)
        if new_selection or self.view.data_tabs.currentIndex() == 1:
            self.plot_input()
        else:
            self.state._data_plot_dirty = True
        self.view.continue_button.setEnabled(True)

    def data_tab_changed(self, index: int) -> None:
        if index == 1 and self.state._data_plot_dirty:
            self.plot_input()

    def update_time_unit_control(self) -> None:
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

    def refresh_data_descriptives(self, *_: object) -> None:
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

    def apply_sensor_preview(self, description: pd.DataFrame | None) -> None:
        self.view.channel_table.setModel(
            FrameModel(description, compact=True) if description is not None else None
        )
        self.view.channel_table.setEnabled(True)

    def update_time_statistics(self, *_: object) -> None:
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

    def apply_time_preview(self, description: pd.DataFrame | None) -> None:
        self.view.time_table.setModel(
            FrameModel(description, compact=True) if description is not None else None
        )
        self.view.time_table.setEnabled(True)

    def selected_input_channels(self) -> list[str]:
        return self.channels.selected_channels(self.view.data_channels)

    def set_input_channels(self, channels: list[str]) -> None:
        self.channels.check_channels(self.view.data_channels, channels)
        self.plot_input()

    def populate_input_channels(self, selection: list[str] | None = None) -> None:
        self.state._channel_colors = self.channels.populate_channels(
            self.view.data_channels,
            self.inputs.frame,
            excluded={self.view.data_time_channel.currentData()},
            selection=selection,
        )

    def input_plot_changed(self) -> None:
        self.state._data_plot_dirty = True
        if self.view.pages.currentIndex() == 0:
            self.data_tab_changed(self.view.data_tabs.currentIndex())

    def plot_input(self, *_: object) -> None:
        self.state._data_plot_dirty = False
        try:
            mapping = self.view.mapping.mapping()
        except (ValueError, TypeError):
            # Conflicting Analyze choices must not prevent original-data inspection.
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
        # A usable timeline has passed the non-None check above.
        xs: pd.Series | np.ndarray | list[float] = (
            cast("pd.Series", times)
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
            calendar=usable
            and pd.api.types.is_datetime64_any_dtype(cast("pd.Series", times).dtype),
            empty_text="Open a recording with numeric sensor channels",
        )
        self.view.data_toolbar.refresh()
        self.view.data_canvas.draw_idle()
