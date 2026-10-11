"""Plot-series selection tree, independent of window and run lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTreeWidgetItem
from ..results_view import (
    MODULE_NAMES,
    plot_metrics,
    preferred_metric,
    output_label,
    gait_model_threshold,
)
from ..theme import module_color

if TYPE_CHECKING:
    from PySide6.QtWidgets import QTreeWidget


class ResultSeries:
    def __init__(self, tree: QTreeWidget):
        self.tree = tree

    def populate(self, plot_tables, plot_labels, tables):
        self.tree.blockSignals(True)
        self.tree.clear()
        items = {}
        roots, default_modules = {}, set()
        title_counts = {}
        module_order = {
            module: index for index, module in enumerate((*MODULE_NAMES, "preparation"))
        }
        names = sorted(
            plot_tables,
            key=lambda name: module_order.get(
                "preparation" if name.startswith("preparation/") else name.split("/")[1],
                len(module_order),
            ),
        )
        for name in names:
            frame = plot_tables[name]
            module = "preparation" if name.startswith("preparation/") else name.split("/")[1]
            for metric in plot_metrics(name, frame):
                title = plot_labels.get((name, metric), str(metric).replace("_", " "))
                title_counts[module, title] = title_counts.get((module, title), 0) + 1
        for name in names:
            frame = plot_tables[name]
            module = "preparation" if name.startswith("preparation/") else name.split("/")[1]
            if module not in roots:
                root = QTreeWidgetItem(
                    self.tree,
                    [
                        MODULE_NAMES.get(
                            module, "Data coverage" if module == "preparation" else module.title()
                        )
                    ],
                )
                root.setForeground(0, QColor(module_color(module)))
                root.setFlags(root.flags() & ~Qt.ItemIsUserCheckable)
                root.setExpanded(True)
                roots[module] = root
            metrics = plot_metrics(name, frame)
            default = preferred_metric(name, frame)
            # Favor unfiltered gait and quantified outputs for initial plots.
            choose = (
                len(frame) > 0
                and name.startswith("quantifications/")
                and module not in default_modules
                and (
                    not name.endswith("/filtered")
                    or not len(tables.get("quantifications/gait/unfiltered", []))
                )
            )
            for metric in metrics:
                title = self._title(module, name, metric, plot_labels, title_counts)
                item = QTreeWidgetItem(roots[module], [title])
                item.setData(0, Qt.UserRole, (name, metric))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    0,
                    Qt.Checked
                    if name.startswith("preparation/") or choose and metric == default
                    else Qt.Unchecked,
                )
                item.setToolTip(0, self._tooltip(module, name, metric, title))
                items[(name, metric)] = item
            if choose and default is not None:
                default_modules.add(module)
        self.tree.blockSignals(False)

        return items

    @staticmethod
    def _title(module, name, metric, plot_labels, title_counts):
        title = plot_labels.get((name, metric), str(metric).replace("_", " "))
        if (
            module != "preparation"
            and len(name.split("/")) > 2
            and not (module == "gait" and (name, metric) in plot_labels)
        ):
            title += (
                " ("
                + " / ".join(part.replace("_", " ").title() for part in name.split("/")[2:])
                + ")"
            )
        elif title_counts[module, title] > 1:
            title += " (" + output_label(name).split(" · ", 1)[-1] + ")"
        return title

    @staticmethod
    def _tooltip(module, name, metric, title):
        if module == "preparation":
            return title + "\nCoverage of the prepared samples supplied to these pipelines."
        if name.startswith("classifications/gait/") and metric in (
            "pred_gait_window",
            "pred_no_other_arm_activity_window",
        ):
            threshold = gait_model_threshold(name.rsplit("/", 1)[-1])
            return (
                title
                + f"\nPresent when the window probability is ≥ {threshold:.5g} (bundled model threshold)."
                "\nThese window predictions precede the final merged sample labels."
                "\nFiltered presence is intersected with detected gait. Both epoch percentages use the same observed time."
            )
        return f"{name}\n{metric}"
