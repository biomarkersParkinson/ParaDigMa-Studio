"""One inline settings panel for each graph, without Matplotlib's two dialogs."""
import math

from matplotlib import dates
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)

from .theme import light_palette


class GraphToolbar(NavigationToolbar2QT):
    # Subplot spacing and the generic figure editor overlap and inherit the
    # system dialog palette. Constrained layout already handles subplot spacing.
    toolitems = tuple(item for item in NavigationToolbar2QT.toolitems
                      if item[0] not in ("Subplots", "Customize"))

    def __init__(self, canvas, parent):
        super().__init__(canvas, parent, coordinates=False)
        self.setPalette(light_palette())
        self.settings = GraphSettings(canvas, self)
        self.settings_action = QAction("Graph settings", self)
        self.settings_action.setCheckable(True)
        self.settings_action.setToolTip("Titles, axis limits, grid and legend")
        self.settings_action.toggled.connect(self.show_settings)
        self.addSeparator()
        self.addAction(self.settings_action)
        self.active_axes = None
        canvas.mpl_connect("button_press_event", self.select_axes)

    def select_axes(self, event):
        if event.inaxes in self.canvas.figure.axes:
            self.active_axes = event.inaxes
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
        if self.settings._defaults is not None and self.settings._defaults[0] is not self.settings.axes():
            self.settings._defaults = None
        self.settings.apply_visibility()
        if self.settings_action.isChecked():
            self.settings.read_axes()


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
        self.title, self.x_label, self.y_label = QLineEdit(), QLineEdit(), QLineEdit()
        layout.addWidget(self.label("Title", self.title), 0, 0)
        layout.addWidget(self.title, 0, 1, 1, 4)
        layout.addWidget(self.label("X label", self.x_label), 1, 0)
        layout.addWidget(self.x_label, 1, 1, 1, 2)
        layout.addWidget(self.label("Y label", self.y_label), 1, 3)
        layout.addWidget(self.y_label, 1, 4)
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
            automatic.toggled.connect(lambda checked, lo=lower, hi=upper:
                                      (lo.setEnabled(not checked), hi.setEnabled(not checked)))
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
        self.limits_panel.hide()
        self.grid, self.legend = QCheckBox("Grid"), QCheckBox("Legend")
        self.grid.setChecked(True)
        self.legend.setChecked(True)
        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(self.grid)
        controls.addWidget(self.legend)
        self.limits_button = QPushButton("Axis limits")
        self.limits_button.setCheckable(True)
        self.limits_button.toggled.connect(self.limits_panel.setVisible)
        controls.addWidget(self.limits_button)
        controls.addStretch()
        self.reset_button = QPushButton("Reset")
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
        self._defaults = None

    @staticmethod
    def label(text, edit):
        label = QLabel(text)
        label.setBuddy(edit)
        edit.setAccessibleName(text)
        return label

    def axes(self):
        if self.toolbar.active_axes in self.canvas.figure.axes:
            return self.toolbar.active_axes
        return self.canvas.figure.axes[0] if self.canvas.figure.axes else None

    def read_axes(self):
        ax = self.axes()
        self.setEnabled(ax is not None)
        if ax is None:
            return
        self.graph_hint.setText("Click a graph to edit its labels and vertical limits.")
        self.graph_hint.setVisible(len(self.canvas.figure.axes) > 1)
        if self._defaults is None or self._defaults[0] is not ax:
            title = ax.get_title() or ax.get_title(loc="left")
            self._defaults = ax, title, ax.get_xlabel(), ax.get_ylabel()
        self.title.setText(ax.get_title() or ax.get_title(loc="left"))
        self.x_label.setText(ax.get_xlabel())
        self.y_label.setText(ax.get_ylabel())
        for axis, (automatic, lower, upper) in self.bounds.items():
            automatic.setChecked(getattr(ax, f"get_autoscale{axis}_on")())
            is_date = isinstance(getattr(ax, f"{axis}axis").get_major_locator(), dates.DateLocator)
            lower.setToolTip("ISO date/time" if is_date else "Finite number")
            upper.setToolTip(lower.toolTip())
            values = getattr(ax, f"get_{axis}lim")()
            for edit, value in zip((lower, upper), values):
                edit.setText(dates.num2date(value).isoformat() if is_date else f"{value:.12g}")
        self.legend.setEnabled(ax.get_legend() is not None)
        self.error.hide()

    def apply_visibility(self):
        for ax in self.canvas.figure.axes:
            ax.grid(self.grid.isChecked())
            if getattr(ax, "_paradigma_binary", False):
                ax.grid(False, axis="y")
            legend = ax.get_legend()
            if legend is not None:
                legend.set_visible(self.legend.isChecked())

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
                is_date = isinstance(getattr(ax, f"{axis}axis").get_major_locator(), dates.DateLocator)
                parse = dates.datestr2num if is_date else float
                values = tuple(float(parse(edit.text().strip())) for edit in (lower, upper))
                if not all(math.isfinite(value) for value in values) or values[0] >= values[1]:
                    raise ValueError
                limits[axis] = values
        except (ValueError, OverflowError, TypeError):
            self.error.setText("Enter valid limits with minimum less than maximum.")
            self.error.show()
            return
        if self._defaults is None or self._defaults[0] is not ax:
            self.read_axes()
        self.toolbar.push_current()
        ax.set_title("", loc="left")
        ax.set_title(self.title.text(), loc="left", fontsize=10)
        ax.set_title("")
        ax.set_xlabel(self.x_label.text())
        ax.set_ylabel(self.y_label.text())
        for axis, bounds in limits.items():
            if bounds is None:
                getattr(ax, f"set_autoscale{axis}_on")(True)
                if axis == "y" and getattr(ax, "_paradigma_binary", False):
                    ax.set_ylim(.65, 1.35)
                    ax.set_autoscaley_on(True)
                else:
                    ax.autoscale_view(scalex=axis == "x", scaley=axis == "y")
            else:
                getattr(ax, f"set_{axis}lim")(*bounds)
        self.apply_visibility()
        self.toolbar.push_current()
        self.read_axes()
        self.canvas.draw_idle()

    def reset(self):
        ax = self.axes()
        if ax is None:
            return
        if self._defaults is None or self._defaults[0] is not ax:
            self.read_axes()
        _, title, x_label, y_label = self._defaults
        self.title.setText(title)
        self.x_label.setText(x_label)
        self.y_label.setText(y_label)
        for automatic, _, _ in self.bounds.values():
            automatic.setChecked(True)
        self.grid.setChecked(True)
        self.legend.setChecked(True)
        self.apply()


def add_graph_controls(layout, canvas, parent):
    toolbar = GraphToolbar(canvas, parent)
    layout.addWidget(toolbar)
    layout.addWidget(toolbar.settings)
    return toolbar
