"""One inline settings panel for each graph, without Matplotlib's two dialogs."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, tzinfo
from typing import TYPE_CHECKING, cast

from matplotlib import dates, rcParams
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from .assets import DATA_DIRECTORY
from .contracts import TimeLimits
from .epoch_profile import format_profile_time, parse_profile_time
from .field_scrolling import PageLineEdit
from .plotting import autoscale_bars
from .theme import light_palette

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.backend_bases import Event, MouseEvent
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.typing import ColorType
    from PySide6.QtWidgets import QWidget


def _calendar_axis(axes: Axes, name: str) -> tuple[bool, str | tzinfo | None]:
    locator = getattr(axes, f"{name}axis").get_major_locator()
    calendar = getattr(locator, "calendar", isinstance(locator, dates.DateLocator))
    timezone = getattr(locator, "timezone", getattr(locator, "tz", None))
    return bool(calendar), timezone


def _format_limit(
    value: float,
    *,
    profile: bool = False,
    calendar: bool = False,
    timezone: str | tzinfo | None = None,
) -> str:
    if profile:
        return format_profile_time(round(value, 3))
    if calendar:
        value = round(value * 86400, 3) / 86400
        return cast(datetime, dates.num2date(value, tz=timezone)).isoformat(timespec="milliseconds")
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


class GraphToolbar(NavigationToolbar2QT):
    canvas: FigureCanvasQTAgg
    # Subplot spacing and the generic figure editor overlap and inherit the
    # system dialog palette. Constrained layout already handles subplot spacing.
    # Matplotlib accepts an immutable sequence; its Qt stub specifies a list.
    toolitems = tuple(  # type: ignore[assignment]
        item for item in NavigationToolbar2QT.toolitems if item[0] not in ("Subplots", "Customize")
    )

    def __init__(
        self, canvas: FigureCanvasQTAgg, parent: QWidget | None, *, time_selection: bool = True
    ) -> None:
        super().__init__(canvas, parent, coordinates=False)
        self.setPalette(light_palette())
        self.select_action: QAction | None = None
        if time_selection:
            self.select_action = QAction(
                QIcon(str(DATA_DIRECTORY / "select-time.svg")), "Select timepoint", self
            )
            self.select_action.setCheckable(True)
            self.select_action.setChecked(True)
            self.select_action.setToolTip("Select a timepoint by clicking a graph")
            self.select_action.triggered.connect(self.select_timepoint)
            self.insertAction(self._actions.get("pan", self._actions["zoom"]), self.select_action)
        self.settings = GraphSettings(canvas, self)
        self.settings_action = QAction("Axis limits", self)
        self.settings_action.setCheckable(True)
        self.settings_action.setToolTip("Set horizontal and vertical limits for the clicked graph")
        self.settings_action.toggled.connect(self.show_settings)
        self.addSeparator()
        self.addAction(self.settings_action)
        self.active_axes: Axes | None = None
        self._highlighted_axes: tuple[Axes, ColorType] | None = None
        self.home_callback: Callable[[], None] | None = None
        canvas.mpl_connect("button_press_event", self.select_axes)

    def add_time_zoom_actions(self, callback: Callable[[float], None]) -> None:
        actions = self.actions()
        following = actions[actions.index(self._actions["zoom"]) + 1]
        for name, text, factor in (("zoom_in", "Zoom in", 0.5), ("zoom_out", "Zoom out", 2.0)):
            action = QAction(
                QIcon(str(DATA_DIRECTORY / f"{name.replace('_', '-')}.svg")), text, self
            )
            action.setToolTip(
                "Halve the visible horizontal range"
                if factor < 1
                else "Double the visible horizontal range"
            )
            action.triggered.connect(lambda checked=False, factor=factor: callback(factor))
            self._actions[name] = action
            self.insertAction(following, action)

    def select_timepoint(self) -> None:
        if self.select_action is None:
            return
        if self.mode.name == "PAN":
            self.pan()
        elif self.mode.name == "ZOOM":
            self.zoom()
        self.select_action.setChecked(True)

    def home(self, *args: object) -> None:
        if self.home_callback is None:
            return super().home(*args)
        self.home_callback()

    def save_figure(self, *args: object) -> str | None:
        # Set export resolution only during Save. Restore this one setting so
        # Matplotlib still remembers the chosen directory for subsequent saves.
        previous_dpi = rcParams["savefig.dpi"]
        rcParams["savefig.dpi"] = 600
        try:
            return cast("str | None", super().save_figure(*args))
        finally:
            rcParams["savefig.dpi"] = previous_dpi

    def pan(self, *args: object) -> None:
        super().pan(*args)
        if self.select_action is not None:
            self.select_action.setChecked(not bool(self.mode))

    def zoom(self, *args: object) -> None:
        super().zoom(*args)
        if self.select_action is not None:
            self.select_action.setChecked(not bool(self.mode))

    def select_axes(self, event: MouseEvent) -> None:
        if event.inaxes in self.canvas.figure.axes:
            self.active_axes = event.inaxes
            if self.settings_action.isChecked():
                self.settings.read_axes()

    def show_settings(self, visible: bool) -> None:
        if visible:
            self.settings.read_axes()
        else:
            self.settings.stop_observing()
            self.highlight_axes(None)
        self.settings.setVisible(visible)

    def highlight_axes(self, axes: Axes | None) -> None:
        """Shade the limits target without changing data or axis geometry."""
        previous = self._highlighted_axes
        if previous is not None and previous[0] is axes:
            return
        if previous is not None:
            previous[0].set_facecolor(previous[1])
        self._highlighted_axes = None
        if axes is not None:
            self._highlighted_axes = axes, axes.get_facecolor()
            axes.set_facecolor("#EAF1F9")
        self.canvas.draw_idle()

    def refresh(self) -> None:
        # A new metric or recording has new axes and a new navigation history.
        if self._pan_info is not None:
            self.release_pan(cast("Event", None))
        self.update()
        if self.active_axes not in self.canvas.figure.axes:
            self.active_axes = None
        if self.settings_action.isChecked():
            self.settings.read_axes()

    def press_zoom(self, event: Event) -> None:
        self._automatic_bar_y = [
            ax
            for ax in self.canvas.figure.axes
            if getattr(ax, "_paradigma_bars", False) and ax.get_autoscaley_on()
        ]
        super().press_zoom(event)

    def release_zoom(self, event: Event | None) -> None:
        # Navigation cleanup also releases a gesture without a mouse event.
        super().release_zoom(cast("Event", event))
        self.restore_automatic_bar_y()
        self._automatic_bar_y = []

    def push_current(self) -> None:
        # Save the final automatic range, so Back/Forward also restore that choice.
        if getattr(self, "_automatic_bar_y", []):
            self.restore_automatic_bar_y()
        super().push_current()

    def restore_automatic_bar_y(self) -> None:
        for ax in getattr(self, "_automatic_bar_y", []):
            if ax in self.canvas.figure.axes:
                ax.set_autoscaley_on(True)
                autoscale_bars(ax)
        self.canvas.draw_idle()

    def autoscale_axis(self, ax: Axes, axis: str) -> None:
        getattr(ax, f"set_autoscale{axis}_on")(True)
        if axis == "y" and getattr(ax, "_paradigma_binary", False):
            ax.set_ylim(0.65, 1.35)
            ax.set_autoscaley_on(True)
        else:
            ax.autoscale_view(scalex=axis == "x", scaley=axis == "y")
            if axis == "y":
                autoscale_bars(ax)


class GraphSettings(QFrame):
    def __init__(self, canvas: FigureCanvasQTAgg, toolbar: GraphToolbar) -> None:
        super().__init__(toolbar.parentWidget())
        self.canvas, self.toolbar = canvas, toolbar
        self.setObjectName("graphSettings")
        self.setPalette(light_palette())
        self.setAutoFillBackground(True)
        layout = QGridLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)
        self.bounds = {}
        self.limits_panel = QFrame()
        limits_layout = QGridLayout(self.limits_panel)
        limits_layout.setContentsMargins(0, 0, 0, 0)
        limits_layout.setHorizontalSpacing(10)
        limits_layout.setVerticalSpacing(6)
        for row, axis in enumerate(("x", "y")):
            automatic = QCheckBox("Automatic")
            lower, upper = PageLineEdit(), PageLineEdit()
            automatic.setChecked(True)
            automatic.toggled.connect(
                lambda checked, lo=lower, hi=upper: (
                    lo.setEnabled(not checked),
                    hi.setEnabled(not checked),
                )
            )
            automatic.clicked.connect(self.apply)
            for edit, name in ((lower, "minimum"), (upper, "maximum")):
                edit.setEnabled(False)
                edit.setMinimumWidth(60)
                edit.setPlaceholderText(name.capitalize())
                edit.setAccessibleName(f"{axis.upper()} axis {name}")
                edit.editingFinished.connect(self.apply)
            limits_layout.addWidget(QLabel(f"{axis.upper()} limits"), row, 0)
            limits_layout.addWidget(automatic, row, 1)
            limits_layout.addWidget(lower, row, 2)
            limits_layout.addWidget(QLabel("to"), row, 3)
            limits_layout.addWidget(upper, row, 4)
            self.bounds[axis] = automatic, lower, upper
        limits_layout.setColumnStretch(2, 1)
        limits_layout.setColumnStretch(4, 1)
        layout.addWidget(self.limits_panel, 2, 0, 1, 5)
        controls = QHBoxLayout()
        controls.setSpacing(12)
        self.graph_hint = QLabel(
            "Click a graph to set its limits. Time limits apply to linked graphs."
        )
        self.graph_hint.setWordWrap(True)
        controls.addWidget(self.graph_hint, 1)
        controls.addStretch()
        self.reset_button = QPushButton("Reset limits")
        self.reset_button.clicked.connect(self.reset)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(lambda: toolbar.settings_action.setChecked(False))
        controls.addWidget(self.reset_button)
        controls.addWidget(self.close_button)
        layout.addLayout(controls, 3, 0, 1, 5)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.setObjectName("graphError")
        layout.addWidget(self.error, 4, 0, 1, 5)
        self.error.hide()
        layout.setColumnStretch(2, 1)
        layout.setColumnStretch(4, 1)
        self.hide()
        self._initialize_synchronization()

    def _initialize_synchronization(self) -> None:
        self._observed_axes: Axes | None = None
        self._axis_callbacks: list[int] = []
        self._axes_snapshot: tuple[TimeLimits, TimeLimits, bool, bool] | None = None
        self._updating = False
        self._displayed_text: dict[PageLineEdit, str] = {}
        self.canvas.mpl_connect("draw_event", self.synchronize)

    def axes(self) -> Axes | None:
        if self.toolbar.active_axes in self.canvas.figure.axes:
            return self.toolbar.active_axes
        return self.canvas.figure.axes[0] if self.canvas.figure.axes else None

    def read_axes(self) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            ax = self.axes()
            self._watch_axes(ax if self.toolbar.settings_action.isChecked() else None)
            self.toolbar.highlight_axes(ax if self.toolbar.settings_action.isChecked() else None)
            self.setEnabled(ax is not None)
            if ax is not None:
                self._read_bounds(ax)
                self._axes_snapshot = self._axis_state(ax)
                self.error.hide()
        finally:
            self._updating = False

    @staticmethod
    def _axis_state(ax: Axes) -> tuple[TimeLimits, TimeLimits, bool, bool]:
        return ax.get_xlim(), ax.get_ylim(), ax.get_autoscalex_on(), ax.get_autoscaley_on()

    def _watch_axes(self, ax: Axes | None) -> None:
        if ax is self._observed_axes:
            return
        for connection in self._axis_callbacks:
            cast("Axes", self._observed_axes).callbacks.disconnect(connection)
        self._observed_axes, self._axis_callbacks = ax, []
        self._axes_snapshot = None
        if ax is not None:
            self._axis_callbacks = [
                ax.callbacks.connect(name, self.synchronize)
                for name in ("xlim_changed", "ylim_changed")
            ]

    def stop_observing(self) -> None:
        self._watch_axes(None)

    def synchronize(self, *_: object) -> None:
        if self._updating or not self.toolbar.settings_action.isChecked():
            return
        ax = self.axes()
        if (
            ax is not self._observed_axes
            or ax is not None
            and self._axis_state(ax) != self._axes_snapshot
        ):
            self.read_axes()

    def _read_bounds(self, ax: Axes) -> None:
        self.graph_hint.setText(
            "Click a graph to set its limits. Time limits apply to linked graphs."
        )
        for axis, (automatic, lower, upper) in self.bounds.items():
            automatic.setChecked(getattr(ax, f"get_autoscale{axis}_on")())
            is_date, timezone = _calendar_axis(ax, axis)
            profile = axis == "x" and getattr(ax, "_paradigma_profile", False)
            lower.setToolTip(
                "Time of day as HH:MM[:SS] or seconds since midnight"
                if profile
                else "ISO date/time, including time zone"
                if is_date
                else "Finite number"
            )
            placeholder = "HH:MM" if profile else "YYYY-MM-DD HH:MM:SS" if is_date else None
            lower.setPlaceholderText(placeholder or "Minimum")
            upper.setPlaceholderText(placeholder or "Maximum")
            upper.setToolTip(lower.toolTip())
            values = getattr(ax, f"get_{axis}lim")()
            for edit, value in zip((lower, upper), values, strict=False):
                text = _format_limit(value, profile=profile, calendar=is_date, timezone=timezone)
                edit.setText(text)
                self._displayed_text[edit] = text

    def _edited_bounds(
        self,
        ax: Axes,
        axis: str,
        lower: PageLineEdit,
        upper: PageLineEdit,
        parse: Callable[[str], float],
    ) -> TimeLimits:
        # Rounded display text must never quantize an untouched limit. Still
        # honor an explicit user edit, even when it matches the displayed text.
        current = getattr(ax, f"get_{axis}lim")()
        # Exactly two bounds are zipped with the two limit editors.
        return cast(
            TimeLimits,
            tuple(
                value
                if not edit.isModified() and edit.text().strip() == self._displayed_text.get(edit)
                else float(parse(edit.text().strip()))
                for edit, value in zip((lower, upper), current, strict=True)
            ),
        )

    def apply(self) -> None:
        if self._updating:
            return
        ax = self.axes()
        if ax is None:
            return
        # Validate every field before changing the view. Never modify plot data.
        limits: dict[str, TimeLimits | None] = {}
        try:
            for axis, (automatic, lower, upper) in self.bounds.items():
                if automatic.isChecked():
                    limits[axis] = None
                    continue
                is_date, _ = _calendar_axis(ax, axis)
                parse = (
                    parse_profile_time
                    if axis == "x" and getattr(ax, "_paradigma_profile", False)
                    else dates.datestr2num
                    if is_date
                    else float
                )
                values = self._edited_bounds(ax, axis, lower, upper, parse)
                if not all(math.isfinite(value) for value in values) or values[0] >= values[1]:
                    raise ValueError
                limits[axis] = values
        except (ValueError, OverflowError, TypeError):
            self.error.setText("Enter valid limits with minimum less than maximum.")
            self.error.show()
            return
        self._updating = True
        try:
            self._apply_limits(ax, limits)
        finally:
            self._updating = False
        self.read_axes()
        self.canvas.draw_idle()

    def _apply_limits(self, ax: Axes, limits: dict[str, TimeLimits | None]) -> None:
        self.toolbar.push_current()
        for axis, bounds in limits.items():
            if bounds is None:
                self.toolbar.autoscale_axis(ax, axis)
            else:
                getattr(ax, f"set_{axis}lim")(*bounds)
        self.toolbar.push_current()

    def reset(self) -> None:
        ax = self.axes()
        if ax is None:
            return
        if self.toolbar.home_callback is not None:
            # Sensor context loads only the visible samples. Autoscaling those
            # samples would keep the panned window instead of restoring context.
            self.toolbar.home_callback()
            self.read_axes()
            return
        for automatic, _, _ in self.bounds.values():
            automatic.setChecked(True)
        self.apply()
