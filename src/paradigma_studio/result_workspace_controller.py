"""Result tables, series selection and workspace presentation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .result_data import detail_table_view
from .results_view import (
    MODULE_NAMES,
    output_label,
    plot_metrics,
    preferred_metric,
)
from .theme import module_color
from .ui.graph_views import ChannelCanvasView, ResultCanvasView
from .ui.result_overview import ResultOverview
from .ui.result_series import ResultSeries
from .widgets import FrameModel, ReadableTable, SeriesTree
from .workspace_state import GraphState, ResultState, SensorState


@dataclass(frozen=True)
class ResultWorkspaceView:
    parent: QWidget
    _result_view_layouts: list[QVBoxLayout]
    _result_view_scrolls: list[QScrollArea]
    aggregation_table: ReadableTable
    context_button: QPushButton
    context_controls: QWidget
    dataset: QComboBox
    dataset_field: QWidget
    detail_controls: QWidget
    export_button: QPushButton
    graph_footer_layout: QHBoxLayout
    result_series: SeriesTree
    result_table: ReadableTable
    result_tabs: QTabWidget
    results_header: QWidget
    save_results_button: QPushButton
    selection_note: QLabel
    sensor_close: QPushButton
    sensor_tab_index: int
    sensor_table: ReadableTable
    table_actions_layout: QHBoxLayout
    table_dataset: QComboBox
    table_module_tabs: Any
    table_stack: QStackedWidget
    timing_toggle: QCheckBox
    y_column: QComboBox
    result_graphics: Callable[[], ResultCanvasView]
    sensor_graphics: Callable[[], ChannelCanvasView]

    @property
    def canvas(self):
        return self.result_graphics().canvas

    @property
    def figure(self):
        return self.result_graphics().figure

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
    def sensor_figure(self):
        return self.sensor_graphics().figure

    @property
    def sensor_toolbar(self):
        return self.sensor_graphics().toolbar

    @property
    def time_axis(self):
        return self.result_graphics().time_axis


@dataclass(frozen=True)
class ResultWorkspaceCallbacks:
    disconnect_sensor_view: Callable[..., Any]
    hide_sensor_context: Callable[..., Any]
    highlight_result_row: Callable[..., Any]
    plot: Callable[..., Any]
    result_row_changed: Callable[..., Any]
    update_context_action: Callable[..., Any]


def set_results_tab(
    state: ResultState, view: ResultWorkspaceView, update_context_action: Callable, index: int
) -> None:
    if index < 0:
        return
    body = view._result_view_layouts[index]
    # The tab bar stays outside every view's scrolling content. Shared
    # controls move below it rather than changing the navigation position.
    if index != state._result_layout_index:
        for widget in (view.results_header, view.detail_controls):
            for previous in view._result_view_layouts:
                previous.removeWidget(widget)
        body.insertWidget(0, view.results_header)
        body.insertWidget(1, view.detail_controls)
        view.graph_footer_layout.removeWidget(view.context_controls)
        view.table_actions_layout.removeWidget(view.context_controls)
        if index == 1:
            view.graph_footer_layout.addWidget(view.context_controls, alignment=Qt.AlignRight)
        else:
            view.table_actions_layout.addWidget(view.context_controls, alignment=Qt.AlignRight)
        state._result_layout_index = index
    state.results_scroll = view._result_view_scrolls[index]
    aggregation = index == 2 and view.table_dataset.currentData() in state.aggregation_tables
    detailed = index in (1, 2) and not aggregation
    view.results_header.show()
    view.sensor_close.setVisible(index == view.sensor_tab_index)
    view.detail_controls.setVisible(index == 2)
    view.context_controls.setVisible(detailed)
    view.dataset_field.setVisible(index == 2)
    view.table_module_tabs.setVisible(index == 2)
    view.timing_toggle.setVisible(index == 2 and not aggregation)
    view.selection_note.setVisible(index == 2)
    if state.results is not None:
        update_context_action(view.result_table.currentIndex())


class ResultWorkspaceController(QObject):
    """Own workspace behavior through explicit state, frozen views and callbacks."""

    def __init__(
        self,
        graphs: GraphState,
        results: ResultState,
        sensors: SensorState,
        view: ResultWorkspaceView,
        callbacks: ResultWorkspaceCallbacks,
        overview: ResultOverview,
        series: ResultSeries,
    ) -> None:
        super().__init__(view.parent)
        self.graphs = graphs
        self.results = results
        self.sensors = sensors
        self.view = view
        self.callbacks = callbacks
        self.overview = overview
        self.series = series

    def clear_results(self):
        self.callbacks.disconnect_sensor_view()
        self.view.plot_toolbar.stop_navigation()
        for toolbar in (self.view.plot_toolbar, self.view.sensor_toolbar):
            if toolbar._pan_info is not None:
                toolbar.release_pan(None)
        self.results._plot_signature = None
        self.graphs._result_shared_axes = None
        self.graphs._result_selection_artists.clear()
        self.results._epoch_views.clear()
        self.results._epoch_presence_views.clear()
        self.results._profile_selection = None
        self.results._gait_presence_cache = self.results._gait_epoch_cache = None
        self.results._table_views.clear()
        self.view.result_overlay.invalidate()
        self.results.results, self.results.active_frame = None, None
        self.results.display_clock = None
        self.results._source_timelines, self.results._display_offsets = {}, {}
        self.results.tables = {}
        self.results.aggregation_tables, self.results._table_choices = {}, {}
        self.results._timings, self.results._detail_selections, self.results._series_items = (
            {},
            {},
            {},
        )
        self.results._interval_ends, self.results._bar_bounds = {}, {}
        self.results._plot_tables, self.results._plot_labels = {}, {}
        self.view.result_series.blockSignals(True)
        self.view.result_series.clear()
        self.view.result_series.blockSignals(False)
        self.view.dataset.clear()
        self.view.result_table.setModel(None)
        self.view.aggregation_table.setModel(None)
        self.sync_table_outputs()
        self.build_result_overview()
        self.view.export_button.setEnabled(False)
        self.view.save_results_button.setEnabled(False)
        self.callbacks.hide_sensor_context()
        self.results.display_frame = self.sensors.sensor_frame = self.sensors.sensor_times = None
        self.sensors._sensor_context = None
        self.sensors._sensor_navigator = None
        self.sensors._sensor_time_indices.clear()
        self.view.sensor_table.setModel(None)
        self.view.sensor_figure.clear()
        self.view.context_button.setEnabled(False)
        self.view.figure.clear()
        self.view.time_axis.bind(None)
        self.view.result_time_scroll.bind(None)
        self.view.plot_toolbar.refresh()
        self.view.sensor_toolbar.refresh()
        self.view.canvas.draw_idle()

    def results_tab_changed(self, index):
        set_results_tab(self.results, self.view, self.callbacks.update_context_action, index)

    def sync_table_outputs(self, force_detail=False):
        names = [*self.results.tables, *self.results.aggregation_tables]
        name = self.view.dataset.currentText()
        if (
            force_detail
            and name in self.results.tables
            and name == self.view.table_dataset.currentData()
            and tuple(names) == getattr(self.results, "_table_output_names", None)
        ):
            return
        self.results._table_output_names = tuple(names)
        modules = list(dict.fromkeys([*MODULE_NAMES, *(name.split("/")[1] for name in names)]))
        available = {
            module: any(name.split("/")[1] == module for name in names) for module in modules
        }
        current = self.view.table_module_tabs.tabData(self.view.table_module_tabs.currentIndex())
        name = self.view.dataset.currentText()
        if force_detail and name in self.results.tables:
            current = name.split("/")[1]
            self.results._table_choices[current] = name
        if not available.get(current):
            current = next((module for module in modules if available[module]), modules[0])
        previous = self.view.table_module_tabs.blockSignals(True)
        if modules != [
            self.view.table_module_tabs.tabData(i)
            for i in range(self.view.table_module_tabs.count())
        ]:
            while self.view.table_module_tabs.count():
                self.view.table_module_tabs.removeTab(0)
            for module in modules:
                index = self.view.table_module_tabs.addTab(
                    MODULE_NAMES.get(module, module.replace("_", " ").title())
                )
                self.view.table_module_tabs.setTabData(index, module)
        for index, module in enumerate(modules):
            self.view.table_module_tabs.setTabEnabled(index, available[module])
            self.view.table_module_tabs.setTabTextColor(index, QColor(module_color(module)))
        index = modules.index(current)
        self.view.table_module_tabs.setCurrentIndex(index)
        self.view.table_module_tabs.blockSignals(previous)
        self.table_module_changed(index)

    def table_module_changed(self, index):
        if index < 0:
            return
        module = self.view.table_module_tabs.tabData(index)
        tables = {**self.results.tables, **self.results.aggregation_tables}
        names = [name for name in tables if name.split("/")[1] == module]
        preferred = self.results._table_choices.get(module)
        if preferred not in names:
            preferred = next(
                (
                    name
                    for name in names
                    if name.startswith("quantifications/") and len(tables[name])
                ),
                names[0] if names else None,
            )
        previous = self.view.table_dataset.blockSignals(True)
        self.view.table_dataset.clear()
        for name in names:
            self.view.table_dataset.addItem(output_label(name).partition(" · ")[2], name)
        if preferred in names:
            self.view.table_dataset.setCurrentIndex(self.view.table_dataset.findData(preferred))
        self.view.table_dataset.blockSignals(previous)
        self.select_output_table()

    def select_output_table(self, *_):
        name = self.view.table_dataset.currentData()
        module = self.view.table_module_tabs.tabData(self.view.table_module_tabs.currentIndex())
        self.results._table_choices[module] = name
        if name in self.results.aggregation_tables:
            self.view.aggregation_table.setModel(FrameModel(self.results.aggregation_tables[name]))
            self.view.table_stack.setCurrentIndex(1)
            self.view.selection_note.setText("Full-run aggregates")
        else:
            self.view.table_stack.setCurrentIndex(0)
            if name in self.results.tables and name != self.view.dataset.currentText():
                self.view.dataset.setCurrentText(name)
            elif name not in self.results.tables or self.results.active_frame is None:
                self.view.result_table.setModel(None)
                self.view.selection_note.setText("No tables available")
            else:
                self.update_detail_note()
        self.results_tab_changed(self.view.result_tabs.currentIndex())

    def table_timing_changed(self, _checked):
        row = self.view.result_table.currentIndex().row()
        self.refresh_detail_table()
        if (
            row >= 0
            and self.results.active_frame is not None
            and row < len(self.results.active_frame)
        ):
            self.view.result_table.setCurrentIndex(self.view.result_table.model().index(row, 0))
            self.view.result_table.selectRow(row)
        self.callbacks.highlight_result_row()

    def selected_export_table(self):
        if self.view.result_tabs.currentIndex() == 2:
            name = self.view.table_dataset.currentData()
            if name in self.results.aggregation_tables:
                return name, self.results.aggregation_tables[name]
            if name not in self.results.tables:
                return name, None
        return self.view.dataset.currentText(), getattr(self.results, "display_frame", None)

    def build_result_overview(self, prepared_views=None):
        (
            self.results.overview_values,
            self.results.overview_module_cards,
            self.results.overview_gait_charts,
        ) = self.overview.render(
            self.results.results,
            self.results.provenance,
            self.results.display_clock,
            prepared_views,
        )

    def populate_result_series(self):
        self.results._series_items = self.series.populate(
            self.results._plot_tables, self.results._plot_labels, self.results.tables
        )

    def selected_result_series(self):
        chosen = []
        for index in range(self.view.result_series.topLevelItemCount()):
            module = self.view.result_series.topLevelItem(index)
            for row in range(module.childCount()):
                item = module.child(row)
                if item.checkState(0) == Qt.Checked:
                    chosen.append(item.data(0, Qt.UserRole))
        return chosen

    def select_plot_series(self, item, previous=None):
        key = item.data(0, Qt.UserRole) if item is not None else None
        if key is None or key[0] not in self.results.tables:
            return
        name, metric = key
        self.view.dataset.setCurrentText(name)
        self.view.y_column.blockSignals(True)
        self.view.y_column.setCurrentIndex(self.view.y_column.findData(metric))
        self.view.y_column.blockSignals(False)

    def select_dataset(self, name):
        frame = self.results.tables.get(name)
        self.callbacks.hide_sensor_context()
        self.view.context_button.setEnabled(False)
        self.view.context_button.setToolTip(
            "Select a result row or click a graph point"
            if self.results.result_source_frame is not None
            else "Original sensor data unavailable"
        )
        self.view.y_column.blockSignals(True)
        self.view.y_column.clear()
        if frame is not None:
            plot_frame = self.results._plot_tables[name]
            for column in plot_metrics(name, plot_frame):
                self.view.y_column.addItem(str(column), column)
            preferred = next(
                (metric for dataset, metric in self.selected_result_series() if dataset == name),
                preferred_metric(name, plot_frame),
            )
            if preferred is not None:
                self.view.y_column.setCurrentIndex(self.view.y_column.findData(preferred))
        self.view.y_column.blockSignals(False)
        self.activate_dataset_rows()
        self.sync_table_outputs(force_detail=True)
        if self.view.result_tabs.currentIndex() != 1 and not any(
            dataset == name for dataset, metric in self.selected_result_series()
        ):
            item = self.results._series_items.get((name, self.view.y_column.currentData()))
            if item is not None:
                item.setCheckState(0, Qt.Checked)

    def activate_dataset_rows(self, *_):
        # All official output rows are available; zooming changes only the plot.
        if not self.results._detail_selections:
            self.results._detail_selections = {
                key: (self.results.tables.get(key, frame), np.arange(len(frame)))
                for key, frame in self.results._plot_tables.items()
            }
        self.results.active_frame, self.results.active_positions = (
            self.results._detail_selections.get(
                self.view.dataset.currentText(), (None, np.array([], dtype=int))
            )
        )
        self.results.active_selection = {}
        self.refresh_detail_table()
        self.callbacks.plot()

    def refresh_detail_table(self):
        self.view.context_button.setEnabled(False)
        self.view.context_button.setToolTip(
            "Select a result row or click a graph point"
            if self.results.result_source_frame is not None
            else "Original sensor data unavailable"
        )
        frame = self.results.active_frame
        if frame is None:
            self.results.display_frame = None
            self.view.result_table.setModel(None)
            self.view.selection_note.setText("No detailed outputs returned.")
            return
        name = self.view.dataset.currentText()
        key = name, self.view.timing_toggle.isChecked()
        view = self.results._table_views.get(key)
        if view is None:
            timing = (
                self.results._timings[name].iloc[self.results.active_positions] if key[1] else None
            )
            view = detail_table_view(
                frame, name, timing, self.results._display_offsets, self.results.display_clock
            )
        self.results._table_views[key] = view
        self.results._table_views.move_to_end(key)
        while len(self.results._table_views) > 4:
            self.results._table_views.popitem(last=False)
        self.results.display_frame = view
        self.view.result_table.setModel(FrameModel(view))
        self.view.result_table.selectionModel().currentRowChanged.connect(
            self.callbacks.result_row_changed
        )
        self.update_detail_note()

    def update_detail_note(self):
        name, frame = self.view.dataset.currentText(), self.results.active_frame
        if frame is None:
            return
        clock_note = (
            f"Recording time ({self.results.display_clock.get('timezone') or 'timezone unspecified'})"
            if self.results.display_clock
            else "Elapsed time · Set a time origin in Analyze to display dates"
        )
        if (
            self.results.display_clock is None
            and len(self.results.provenance.get("sources", {})) > 1
        ):
            clock_note = "File-order timeline · Recording clocks unavailable"
        estimated = name.startswith("quantifications/gait/") and "time" not in frame
        self.view.selection_note.setText(
            f"{len(frame):,} / {len(self.results.tables[name]):,} rows · {clock_note}"
            + (" · Gait positions estimated within segments" if estimated else "")
        )
        if not self.view.timing_toggle.isChecked():
            self.view.selection_note.setText(
                f"{len(frame):,} / {len(self.results.tables[name]):,} rows"
            )
        if self.view.table_dataset.currentData() in self.results.aggregation_tables:
            self.view.selection_note.setText("Full-run aggregates")

    def update_metric(self, *_):
        key = self.view.dataset.currentText(), self.view.y_column.currentData()
        item = self.results._series_items.get(key)
        if item is not None:
            self.view.result_series.blockSignals(True)
            # Changing the active metric replaces its prior default series.
            for previous, candidate in self.results._series_items.items():
                if previous[0] == key[0]:
                    candidate.setCheckState(0, Qt.Checked if previous == key else Qt.Unchecked)
            self.view.result_series.blockSignals(False)
        self.callbacks.plot()
