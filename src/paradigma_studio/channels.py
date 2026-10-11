"""Shared channel selection and original-value signal rendering."""

import re

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem
from matplotlib import colormaps, dates
from matplotlib.lines import Line2D
from .inspection import TIME_NAMES
from .plotting import (
    GRAPH_COLORS,
    binary_indicator,
    plot_signal,
    plot_states,
    time_selection_line,
    time_selection_triangle,
)
from .theme import style_axes
from .time_axis import RecordingTimeFormatter, RecordingDateLocator
from .results_view import clock_times


def mark_sensor_time(figure, seconds, clock):
    """Mark the selected result time while leaving original sensor values intact."""
    if not np.isfinite(seconds) or not figure.axes:
        return
    if clock is None:
        x, text = seconds, f"{seconds:.6g} s"
    else:
        stamp = clock_times([seconds], clock)[0]
        x = float(dates.date2num(stamp.to_pydatetime(warn=False)))
        text = stamp.strftime("%d %b %Y %H:%M:%S.%f").rstrip("0").rstrip(".")
    mark_graph_time(figure, x, text)


def mark_graph_time(figure, x, text):
    """Use the shared selection overlay without affecting data or axis limits."""
    for ax in figure.axes:
        for artist in [*ax.lines, *ax.texts]:
            if artist.get_gid() in (
                "selected-result-time",
                "selected-result-triangle",
                "selected-result-label",
            ):
                artist.remove()
        time_selection_line(ax, x)
    ax = figure.axes[-1]
    triangle = Line2D(
        [x],
        [0],
        marker=time_selection_triangle(),
        markersize=6,
        color="#465B73",
        linestyle="none",
        transform=ax.get_xaxis_transform(),
        zorder=8,
    )
    ax.add_artist(triangle)
    triangle.set_gid("selected-result-triangle")
    annotation = ax.text(
        1,
        1.02,
        text,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8.5,
        color="#465B73",
    )
    annotation.set_gid("selected-result-label")


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
    import pandas as pd

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


_SENSOR_MODALITIES = {
    "Accelerometer": ("accelerometer", "acceleration", "accel", "acc"),
    "Gyroscope": ("gyroscope", "angular_velocity", "gyro", "gyr"),
    "Magnetometer": ("magnetometer", "magnetic_field", "magnet", "mag"),
    "PPG": ("ppg", "photoplethysmography", "green", "red", "infrared", "ir"),
}


def channel_modality(channel):
    """Identify named sensor families; keep unidentified scalar streams separate."""
    text = str(channel)
    # Readers use canonical names; recognize common CSV axis aliases too.
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", text)
    name = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    for title, prefixes in _SENSOR_MODALITIES.items():
        if any(
            name == prefix
            or name.startswith(prefix + "_")
            or name in {prefix + axis for axis in "xyz"}
            for prefix in prefixes
        ):
            return ("modality", title), title
    vector = re.fullmatch(r"(.+)_[xyz]", name)
    if vector is not None:
        family = vector[1]
        return ("vector", family), family.replace("_", " ")
    return ("channel", channel), text


def plot_channel_signals(
    figure,
    frame,
    channels,
    colors,
    xs,
    time_label,
    *,
    column_mapping=None,
    calendar=False,
    timezone=None,
    empty_text="No original samples in this context",
    allow_empty=False,
    empty_schema=None,
):
    figure.clear()
    if frame is None or (frame.empty and not allow_empty) or not channels:
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
        groups, flags = _sensor_plot_groups(frame, channels, column_mapping, empty_schema)
        first_axes = None
        grid = figure.add_gridspec(
            len(groups), 1, height_ratios=[0.55 if group[0] in flags else 1 for _, group in groups]
        )
        for index, (modality, group) in enumerate(groups):
            ax = style_axes(figure, position=(grid[index],), sharex=first_axes)
            if first_axes is None:
                first_axes = ax
            for channel in group:
                _plot_sensor_channel(ax, frame, channel, group, modality, flags, colors, xs)
            _style_sensor_group(ax, group, time_label, calendar, timezone, index == len(groups) - 1)


def _sensor_plot_groups(frame, channels, column_mapping, empty_schema):
    mapping = column_mapping or {}
    families = {channel: channel_modality(mapping.get(channel, channel)) for channel in channels}
    # Named physical sensor streams remain continuous even when a short
    # selection happens to contain only zeros and ones.
    flags = [
        c
        for c in channels
        if families[c][0][0] != "modality"
        and binary_indicator(
            (empty_schema if frame.empty and empty_schema is not None else frame)[c],
            mapping.get(c, c),
        )
    ]
    signals = [c for c in channels if c not in flags]
    modalities = {}
    for channel in signals:
        key, title = families[channel]
        if key not in modalities:
            modalities[key] = (title, [])
        modalities[key][1].append(channel)
    groups = list(modalities.values()) + [(str(flag), [flag]) for flag in flags]
    return groups, flags


def _plot_sensor_channel(ax, frame, channel, group, modality, flags, colors, xs):
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
            str(group[0]) if len(group) == 1 else f"{modality}\n(file units)",
            rotation=0,
            ha="right",
            va="center",
            fontsize=9,
            labelpad=10,
        )


def _style_sensor_group(ax, group, time_label, calendar, timezone, last):
    if len(group) > 1:
        ax.legend(
            loc="upper right",
            ncols=min(2, len(group)),
            frameon=True,
            facecolor="white",
            edgecolor="#E0E7EF",
            framealpha=0.95,
            fontsize=8,
        )
    if calendar:
        locator = RecordingDateLocator(tz=timezone)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(RecordingTimeFormatter(timezone))
    ax.set_xlabel(time_label)
    ax.tick_params(axis="x", labelbottom=last)
    ax.xaxis.label.set_visible(last)
    ax.xaxis.offsetText.set_visible(last)
