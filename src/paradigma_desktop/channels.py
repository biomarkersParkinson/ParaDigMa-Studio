"""Shared channel selection and original-value signal rendering."""

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem
from matplotlib import colormaps, dates
from .inspection import TIME_NAMES
from .plotting import GRAPH_COLORS, binary_indicator, plot_signal, plot_states
from .theme import style_axes
from .time_axis import RecordingTimeFormatter


def selected_channels(channel_list):
    return [
        channel_list.item(i).data(Qt.UserRole)
        for i in range(channel_list.count())
        if channel_list.item(i).checkState() == Qt.Checked
    ]


def check_channels(channel_list, channels):
    channels = set(channels)
    blocked = channel_list.blockSignals(True)
    for i in range(channel_list.count()):
        item = channel_list.item(i)
        item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in channels else Qt.Unchecked)
    channel_list.blockSignals(blocked)


def populate_channels(channel_list, frame, *, excluded=(), selection=None):
    numeric = [
        column
        for column, dtype in frame.dtypes.items()
        if pd.api.types.is_numeric_dtype(dtype)
        if str(column).lower() not in TIME_NAMES and not pd.api.types.is_complex_dtype(dtype)
    ]
    colors = (
        GRAPH_COLORS
        if len(numeric) <= len(GRAPH_COLORS)
        else colormaps["tab20"].colors
        if len(numeric) <= 20
        else colormaps["turbo"](np.linspace(0.05, 0.95, len(numeric)))
    )
    channel_colors = {column: colors[i] for i, column in enumerate(numeric)}
    blocked = channel_list.blockSignals(True)
    channel_list.clear()
    for column in numeric:
        if column in excluded:
            continue
        item = QListWidgetItem(str(column), channel_list)
        item.setData(Qt.UserRole, column)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(
            Qt.Checked if selection is not None and column in selection else Qt.Unchecked
        )
    if selection is None and channel_list.count():
        channel_list.item(0).setCheckState(Qt.Checked)
    channel_list.blockSignals(blocked)
    return channel_colors


def plot_channel_signals(
    figure,
    frame,
    channels,
    colors,
    xs,
    time_label,
    *,
    calendar=False,
    timezone=None,
    empty_text="No original samples in this context",
):
    figure.clear()
    if frame is None or frame.empty or not channels:
        ax = style_axes(figure)
        ax.text(
            0.5,
            0.5,
            "Select sensor channels" if frame is not None and not frame.empty else empty_text,
            ha="center",
            transform=ax.transAxes,
            color="#60728A",
        )
    else:
        flags = [c for c in channels if binary_indicator(frame[c], c)]
        signals = [c for c in channels if c not in flags]
        groups = ([signals] if signals else []) + [[flag] for flag in flags]
        first_axes = None
        grid = figure.add_gridspec(
            len(groups), 1, height_ratios=[0.55 if group[0] in flags else 1 for group in groups]
        )
        for index, group in enumerate(groups):
            ax = style_axes(figure, position=(grid[index],), sharex=first_axes)
            if first_axes is None:
                first_axes = ax
            for channel in group:
                if channel in flags:
                    plot_states(
                        ax,
                        xs,
                        frame[channel].to_numpy(dtype=float, na_value=np.nan),
                        colors[channel],
                        label=str(channel),
                    )
                    ax.set_title(
                        str(channel),
                        loc="left",
                        fontsize=10,
                        fontweight="semibold",
                        color="#243C57",
                        pad=12,
                    )
                else:
                    step = max(1, int(np.ceil(len(frame) / 20000)))
                    plot_signal(
                        ax,
                        xs.iloc[::step] if hasattr(xs, "iloc") else xs[::step],
                        frame[channel].iloc[::step],
                        colors[channel],
                        label=str(channel),
                    )
                    ax.set_ylabel(
                        str(group[0]) if len(group) == 1 else "Sensor values (file units)"
                    )
            if len(group) > 1:
                ax.legend(
                    loc="upper right",
                    ncols=min(3, len(group)),
                    frameon=True,
                    facecolor="white",
                    edgecolor="#E0E7EF",
                    framealpha=0.95,
                    fontsize=9,
                )
            if calendar:
                locator = dates.AutoDateLocator(tz=timezone)
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(RecordingTimeFormatter(timezone))
            ax.set_xlabel(time_label)
            ax.tick_params(axis="x", labelbottom=index == len(groups) - 1)
            ax.xaxis.label.set_visible(index == len(groups) - 1)
            ax.xaxis.offsetText.set_visible(index == len(groups) - 1)
