"""Data page construction with explicit layout, callback and graph dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
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
        self._build_time_controls(content)
        self.time_table = table()
        content.addWidget(self.time_table, 1)
        details.addWidget(panel)
        details.setSizes([660, 400])
        overview_layout.addWidget(details, 1)
        self.data_overview_scroll = QScrollArea()
        self.data_overview_scroll.setWidgetResizable(True)
        self.data_overview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.data_overview_scroll.setWidget(overview)
        self.data_tabs.addTab(self.data_overview_scroll, "Overview")
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

    def _build_time_controls(self, content: QVBoxLayout) -> None:
        controls = QHBoxLayout()
        self.data_time_channel = self.combo()
        self.data_time_channel.setPlaceholderText("Select time column")
        self.data_time_channel.setAccessibleName("Time column (shared with Analyze)")
        self.data_time_channel.setMinimumContentsLength(8)
        self.data_time_channel.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.data_time_channel.setToolTip(
            tooltip_text("Time column shared with Analyze. Changes apply to all loaded recordings.")
        )
        field, self.data_time_channel_badge = self._time_field(
            "Time column", self.data_time_channel
        )
        controls.addWidget(field, 1)
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
        self.data_time_unit.setAccessibleName("Time format (shared with Analyze)")
        self.data_time_unit.setToolTip(
            tooltip_text("Time format shared with Analyze, sampling diagnostics and raw graphs.")
        )
        self.data_time_unit_field, self.data_time_unit_badge = self._time_field(
            "Time format", self.data_time_unit
        )
        controls.addWidget(self.data_time_unit_field, 1)
        content.addLayout(controls)

    @staticmethod
    def _time_field(title: str, control: QComboBox) -> tuple[QWidget, QLabel]:
        field = QWidget()
        field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(field)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(label(title, "sectionTitle"))
        badge = label("From file", "muted")
        badge.setObjectName("fileDefaultBadge")
        badge.setAccessibleName(f"{title}: from file")
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setRetainSizeWhenHidden(True)
        badge.setSizePolicy(policy)
        badge.hide()
        layout.addWidget(badge)
        layout.addWidget(control)
        return field, badge

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
