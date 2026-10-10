"""One inline settings panel for each graph, without Matplotlib's two dialogs."""

import math

from matplotlib import dates
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from .theme import light_palette
from .assets import DATA_DIRECTORY
from .plotting import autoscale_bars
from .channels import mark_graph_time


class GraphToolbar(NavigationToolbar2QT):
    # Subplot spacing and the generic figure editor overlap and inherit the
    # system dialog palette. Constrained layout already handles subplot spacing.
    toolitems = tuple(
        item for item in NavigationToolbar2QT.toolitems if item[0] not in ("Subplots", "Customize")
    )

    def __init__(self, canvas, parent):
        super().__init__(canvas, parent, coordinates=False)
        self.setPalette(light_palette())
        self.select_action = QAction(
            QIcon(str(DATA_DIRECTORY / "select-time.svg")), "Select timepoint", self
        )
        self.select_action.setCheckable(True)
        self.select_action.setChecked(True)
        self.select_action.setToolTip("Select a timepoint by clicking a graph")
        self.select_action.triggered.connect(self.select_timepoint)
        self.insertAction(self._actions["pan"], self.select_action)
        self.settings = GraphSettings(canvas, self)
        self.settings_action = QAction("Axis limits", self)
        self.settings_action.setCheckable(True)
        self.settings_action.setToolTip("Set horizontal and vertical limits for the clicked graph")
        self.settings_action.toggled.connect(self.show_settings)
        self.addSeparator()
        self.addAction(self.settings_action)
        self.active_axes = None
        canvas.mpl_connect("button_press_event", self.select_axes)

    def select_timepoint(self):
        if self._actions["pan"].isChecked():
            self.pan()
        elif self._actions["zoom"].isChecked():
            self.zoom()
        self.select_action.setChecked(True)

    def pan(self, *args):
        super().pan(*args)
        self.select_action.setChecked(not bool(self.mode))

    def zoom(self, *args):
        super().zoom(*args)
        self.select_action.setChecked(not bool(self.mode))

    def select_axes(self, event):
        if event.inaxes in self.canvas.figure.axes:
            self.active_axes = event.inaxes
            if (
                not self.mode
                and event.button == 1
                and event.xdata is not None
                and not hasattr(event.inaxes, "_paradigma_dataset")
                and event.inaxes.has_data()
            ):
                locator = event.inaxes.xaxis.get_major_locator()
                text = (
                    dates.num2date(event.xdata, tz=locator.tz)
                    .strftime("%d %b %Y %H:%M:%S.%f")
                    .rstrip("0")
                    .rstrip(".")
                    if isinstance(locator, dates.DateLocator)
                    else f"{event.xdata:.6g} s"
                )
                mark_graph_time(self.canvas.figure, event.xdata, text)
                self.canvas.draw_idle()
            if self.settings_action.isChecked():
                self.settings.read_axes()

    def show_settings(self, visible):
        if visible:
            self.settings.read_axes()
        self.settings.setVisible(visible)

    def refresh(self):
        # A new metric or recording has new axes and a new navigation history.
        self.update()
        if self.active_axes not in self.canvas.figure.axes:
            self.active_axes = None
        if self.settings_action.isChecked():
            self.settings.read_axes()

    def press_zoom(self, event):
        self._automatic_bar_y = [
            ax
            for ax in self.canvas.figure.axes
            if getattr(ax, "_paradigma_bars", False) and ax.get_autoscaley_on()
        ]
        super().press_zoom(event)

    def release_zoom(self, event):
        super().release_zoom(event)
        self.restore_automatic_bar_y()
        self._automatic_bar_y = []

    def press_pan(self, event):
        self._automatic_bar_y = [
            ax
            for ax in self.canvas.figure.axes
            if getattr(ax, "_paradigma_bars", False) and ax.get_autoscaley_on()
        ]
        super().press_pan(event)
        # Keep the drag transform stable; fit the final Y range once on release.
        if self._pan_info is not None:
            for ax in self._automatic_bar_y:
                ax.set_autoscaley_on(False)
        else:
            self._automatic_bar_y = []

    def release_pan(self, event):
        super().release_pan(event)
        self.restore_automatic_bar_y()
        self._automatic_bar_y = []

    def push_current(self):
        # Save the final automatic range, so Back/Forward also restore that choice.
        if getattr(self, "_automatic_bar_y", []):
            self.restore_automatic_bar_y()
        super().push_current()

    def restore_automatic_bar_y(self):
        for ax in getattr(self, "_automatic_bar_y", []):
            if ax in self.canvas.figure.axes:
                ax.set_autoscaley_on(True)
                autoscale_bars(ax)
        self.canvas.draw_idle()


class GraphSettings(QFrame):
    def __init__(self, canvas, toolbar):
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
            lower, upper = QLineEdit(), QLineEdit()
            automatic.setChecked(True)
            automatic.toggled.connect(
                lambda checked, lo=lower, hi=upper: (
                    lo.setEnabled(not checked),
                    hi.setEnabled(not checked),
                )
            )
            for edit, name in ((lower, "minimum"), (upper, "maximum")):
                edit.setEnabled(False)
                edit.setMinimumWidth(60)
                edit.setPlaceholderText(name.capitalize())
                edit.setAccessibleName(f"{axis.upper()} axis {name}")
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
        controls.addStretch()
        self.reset_button = QPushButton("Reset limits")
        self.reset_button.clicked.connect(self.reset)
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply)
        controls.addWidget(self.reset_button)
        controls.addWidget(self.apply_button)
        layout.addLayout(controls, 3, 0, 1, 5)
        self.error = QLabel()
        self.error.setTextFormat(Qt.PlainText)
        self.error.setWordWrap(True)
        self.error.setObjectName("graphError")
        layout.addWidget(self.error, 4, 0, 1, 5)
        self.error.hide()
        self.graph_hint = QLabel()
        self.graph_hint.setWordWrap(True)
        layout.addWidget(self.graph_hint, 5, 0, 1, 5)
        self.graph_hint.hide()
        layout.setColumnStretch(2, 1)
        layout.setColumnStretch(4, 1)
        self.hide()

    def axes(self):
        if self.toolbar.active_axes in self.canvas.figure.axes:
            return self.toolbar.active_axes
        return self.canvas.figure.axes[0] if self.canvas.figure.axes else None

    def read_axes(self):
        ax = self.axes()
        self.setEnabled(ax is not None)
        if ax is None:
            return
        self.graph_hint.setText(
            "Click a graph to set its limits. Time limits apply to linked graphs."
        )
        self.graph_hint.setVisible(len(self.canvas.figure.axes) > 1)
        for axis, (automatic, lower, upper) in self.bounds.items():
            automatic.setChecked(getattr(ax, f"get_autoscale{axis}_on")())
            is_date = isinstance(getattr(ax, f"{axis}axis").get_major_locator(), dates.DateLocator)
            lower.setToolTip("ISO date/time, including time zone" if is_date else "Finite number")
            lower.setPlaceholderText("YYYY-MM-DD HH:MM:SS" if is_date else "Minimum")
            upper.setPlaceholderText("YYYY-MM-DD HH:MM:SS" if is_date else "Maximum")
            upper.setToolTip(lower.toolTip())
            values = getattr(ax, f"get_{axis}lim")()
            for edit, value in zip((lower, upper), values):
                edit.setText(
                    dates.num2date(
                        value, tz=getattr(ax, f"{axis}axis").get_major_locator().tz
                    ).isoformat()
                    if is_date
                    else f"{value:.12g}"
                )
        self.error.hide()

    def apply(self):
        ax = self.axes()
        if ax is None:
            return
        # Validate every field before changing the view. Never modify plot data.
        limits = {}
        try:
            for axis, (automatic, lower, upper) in self.bounds.items():
                if automatic.isChecked():
                    limits[axis] = None
                    continue
                is_date = isinstance(
                    getattr(ax, f"{axis}axis").get_major_locator(), dates.DateLocator
                )
                parse = dates.datestr2num if is_date else float
                values = tuple(float(parse(edit.text().strip())) for edit in (lower, upper))
                if not all(math.isfinite(value) for value in values) or values[0] >= values[1]:
                    raise ValueError
                limits[axis] = values
        except (ValueError, OverflowError, TypeError):
            self.error.setText("Enter valid limits with minimum less than maximum.")
            self.error.show()
            return
        self.toolbar.push_current()
        for axis, bounds in limits.items():
            if bounds is None:
                getattr(ax, f"set_autoscale{axis}_on")(True)
                if axis == "y" and getattr(ax, "_paradigma_binary", False):
                    ax.set_ylim(0.65, 1.35)
                    ax.set_autoscaley_on(True)
                else:
                    ax.autoscale_view(scalex=axis == "x", scaley=axis == "y")
                    if axis == "y":
                        autoscale_bars(ax)
            else:
                getattr(ax, f"set_{axis}lim")(*bounds)
        self.toolbar.push_current()
        self.read_axes()
        self.canvas.draw_idle()

    def reset(self):
        ax = self.axes()
        if ax is None:
            return
        for automatic, _, _ in self.bounds.values():
            automatic.setChecked(True)
        self.apply()


def add_graph_controls(layout, canvas, parent):
    toolbar = GraphToolbar(canvas, parent)
    layout.addWidget(toolbar)
    layout.addWidget(toolbar.settings)
    return toolbar
