"""Data page construction with explicit layout, callback and graph dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..theme import tooltip_text
from ..widgets import button, card, combo, label, table
from .deferred import DeferredWidget
from .workspace_callbacks import WorkspaceCallbacks

ChannelGraphBuilder = Callable[
    [Callable[..., object], str, str], tuple[QWidget, QListWidget, DeferredWidget]
]


@dataclass(frozen=True)
class DataPageHost:
    parent: QMainWindow
    layout: QVBoxLayout
    status_layout: QHBoxLayout


class DataPage:
    """Own Data widgets and responsive layout without application-window access."""

    combo = staticmethod(combo)

    def __init__(
        self,
        host: DataPageHost,
        callbacks: WorkspaceCallbacks,
        channel_graph: ChannelGraphBuilder,
    ) -> None:
        self.parent, self._layout, self.status_layout = (
            host.parent,
            host.layout,
            host.status_layout,
        )
        self.callbacks, self.channel_graph = callbacks, channel_graph
        self._build_data()

    def _build_data(self) -> None:
        layout = self._layout
        self._build_data_header(layout)
        self.data_tabs = QTabWidget()
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(18, 18, 18, 18)
        overview_layout.setSpacing(16)
        metrics = QHBoxLayout()
        self.data_values = []
        for title in ("Sensor samples", "Channels", "Missing values"):
            panel, content = card()
            content.addWidget(label(title, "muted"))
            value = label("—", "metricValue")
            content.addWidget(value)
            self.data_values.append(value)
            metrics.addWidget(panel, 1)
        overview_layout.addLayout(metrics)
        details = self.data_details = QSplitter(Qt.Orientation.Horizontal)
        details.setHandleWidth(12)
        panel, content = card()
        content.addWidget(label("Sensor channels", "sectionTitle"))
        self.channel_table = table()
        content.addWidget(self.channel_table, 1)
        details.addWidget(panel)
        panel, content = card()
        time_controls = QHBoxLayout()
        content.addWidget(label("Time channel", "sectionTitle"))
        self.data_time_channel = self.combo()
        self.data_time_channel.setPlaceholderText("Select time column")
        self.data_time_channel.setToolTip(
            tooltip_text("Time column inspected here. Analysis uses its column mapping.")
        )
        time_controls.addWidget(self.data_time_channel, 1)
        self.data_time_unit = self.combo(
            [
                "relative_s",
                "relative_ms",
                "absolute_s",
                "absolute_ms",
                "difference_s",
                "difference_ms",
            ]
        )
        self.data_time_unit.setToolTip(
            tooltip_text(
                "Units for inspecting the raw time column. Analysis parameters are set on Analyze."
            )
        )
        time_controls.addWidget(self.data_time_unit)
        content.addLayout(time_controls)
        self.time_table = table()
        content.addWidget(self.time_table, 1)
        details.addWidget(panel)
        details.setSizes([660, 400])
        overview_layout.addWidget(details, 1)
        self.data_tabs.addTab(overview, "Overview")
        preview, self.data_channels, self._data_graph = self.channel_graph(
            self.callbacks.set_input_channels, "Sensor channels to plot", "data"
        )
        self.data_tabs.addTab(preview, "Graphs")
        self.input_table = table()
        self.data_tabs.addTab(self.input_table, "Tables")
        layout.addWidget(self.data_tabs, 1)
        self.continue_button = button("Configure analysis  →", lambda: self.callbacks.navigate(1))
        self.continue_button.setEnabled(False)
        self.status_layout.addWidget(self.continue_button)

    def _build_data_header(self, layout: QVBoxLayout) -> None:
        panel, content = card()
        row = QHBoxLayout()
        self.file_label = label("No recording loaded", "sectionTitle")
        row.addWidget(self.file_label, 1)
        self.input_recording = self.combo()
        self.input_recording.setAccessibleName("Recording to inspect")
        self.input_recording.hide()
        self.input_recording.currentIndexChanged.connect(self.callbacks.inspect_input_recording)
        row.addWidget(self.input_recording, 1)
        self.open_button = button("Open sensor files…", self.callbacks.open_file, primary=True)
        self.open_button.setToolTip("Ctrl+O · CSV, Parquet, CWA, Avro, TSDF or trusted pickle")
        self.open_action = QAction("Open recording", self.parent)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.callbacks.open_file)
        self.parent.addAction(self.open_action)
        row.addWidget(self.open_button)
        content.addLayout(row)
        layout.addWidget(panel)

    def resize_data(self, width: int) -> None:
        orientation = Qt.Orientation.Horizontal if width >= 1280 else Qt.Orientation.Vertical
        if self.data_details.orientation() != orientation:
            self.data_details.setOrientation(orientation)
            self.data_details.setSizes(
                [660, 400] if orientation == Qt.Orientation.Horizontal else [220, 300]
            )
