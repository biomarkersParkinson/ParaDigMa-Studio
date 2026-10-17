"""Plot-series selection tree, independent of window and run lifecycle."""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTreeWidgetItem

from ..results_view import (
    MODULE_NAMES,
    gait_model_threshold,
    output_label,
    plot_metrics,
    preferred_metric,
)
from ..theme import module_color, tooltip_text

if TYPE_CHECKING:
    import pandas as pd
    from PySide6.QtWidgets import QTreeWidget


SeriesKey = tuple[str, Hashable]

DEFAULT_SERIES = {
    "gait": (
        ("classifications/gait/detection", "pred_gait_window"),
        ("quantifications/gait/filtered", "range_of_motion"),
    ),
    "tremor": (("classifications/tremor", "pred_tremor_checked"),),
}


def default_series(
    names: Iterable[str], frames: Mapping[str, pd.DataFrame], tables: Mapping[str, pd.DataFrame]
) -> set[SeriesKey]:
    selected: set[SeriesKey] = {
        (name, metric)
        for choices in DEFAULT_SERIES.values()
        for name, metric in choices
        if name in frames and metric in plot_metrics(name, frames[name])
    }
    selected_modules = {name.split("/")[1] for name, _ in selected}
    for name in names:
        frame = frames[name]
        if name.startswith("preparation/"):
            selected.add((name, "available"))
            continue
        module = name.split("/")[1]
        if module in selected_modules or not name.startswith("quantifications/") or not len(frame):
            continue
        if name.endswith("/filtered") and len(tables.get("quantifications/gait/unfiltered", [])):
            continue
        metric = preferred_metric(name, frame)
        if metric is not None:
            selected.add((name, metric))
            selected_modules.add(module)
    return selected


class ResultSeries:
    def __init__(self, tree: QTreeWidget) -> None:
        self.tree = tree

    def populate(
        self,
        plot_tables: Mapping[str, pd.DataFrame],
        plot_labels: Mapping[SeriesKey, str],
        tables: Mapping[str, pd.DataFrame],
    ) -> dict[SeriesKey, QTreeWidgetItem]:
        self.tree.blockSignals(True)
        self.tree.clear()
        items: dict[SeriesKey, QTreeWidgetItem] = {}
        roots = {}
        title_counts: dict[tuple[str, str], int] = {}
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
        defaults = default_series(names, plot_tables, tables)
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
                root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                root.setExpanded(True)
                roots[module] = root
            metrics = plot_metrics(name, frame)
            for metric in metrics:
                title = self._title(module, name, metric, plot_labels, title_counts)
                item = QTreeWidgetItem(roots[module], [title])
                item.setData(0, Qt.ItemDataRole.UserRole, (name, metric))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if (name, metric) in defaults
                    else Qt.CheckState.Unchecked,
                )
                item.setToolTip(0, self._tooltip(module, name, metric))
                items[(name, metric)] = item
        self.tree.blockSignals(False)

        return items

    @staticmethod
    def _title(
        module: str,
        name: str,
        metric: Hashable,
        plot_labels: Mapping[SeriesKey, str],
        title_counts: Mapping[tuple[str, str], int],
    ) -> str:
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
    def _tooltip(module: str, name: str, metric: Hashable) -> str:
        if module == "preparation":
            return "Coverage of the prepared samples supplied to this pipeline."
        if name.startswith("classifications/gait/") and metric in (
            "pred_gait_window",
            "pred_no_other_arm_activity_window",
        ):
            threshold = gait_model_threshold(name.rsplit("/", 1)[-1])
            return tooltip_text(
                f"Present when the window probability is ≥ {threshold:.5g} (bundled model threshold)."
                "\nWindow predictions precede the final merged sample labels."
                "\nFiltered presence is intersected with gait; both epoch percentages use the same observed time."
            )
        return ""
