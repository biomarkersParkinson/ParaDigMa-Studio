"""Overview rendering with explicit layout and result inputs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget

from ..module_issues import ModuleIssues, module_issue_summaries
from ..overview import pulse_estimate_availability, recording_summary
from ..results_view import MODULE_NAMES, flat_values, readable_key, tremor_overview_entries
from ..theme import tooltip_text
from ..widgets import button, card, label, precision_tooltip

if TYPE_CHECKING:
    import pandas as pd
    from PySide6.QtWidgets import QLabel, QLayoutItem, QScrollArea, QVBoxLayout

    from ..contracts import AnalysisResults, ClockMetadata, Provenance


# Gait chart metadata contains canvas/axes handles, category pairs and arrays.
OverviewHandles = tuple[
    dict[tuple[str, str, tuple[str, ...]], "QLabel"],
    dict[str, QWidget],
    dict[str, dict[str, Any]],
]


class ResultOverview:
    def __init__(
        self,
        layout: QVBoxLayout,
        scroll_area: QScrollArea,
        *,
        run_errors: Callable[[str], Sequence[str] | None] | None = None,
        open_errors: Callable[[str], None] | None = None,
    ) -> None:
        self.layout = layout
        self.scroll_area = scroll_area
        self.run_errors = run_errors
        self.open_errors = open_errors

    def render(
        self,
        results: AnalysisResults | None,
        provenance: Provenance,
        clock: ClockMetadata | None,
        prepared_views: tuple[dict[str, pd.DataFrame], dict[tuple[str, str], str]] | None = None,
    ) -> OverviewHandles:
        """Replace overview widgets without transforming the scientific outputs."""
        self._clear()
        results = results or {}
        run_id = provenance.get("run_id", "")
        diagnostics = (
            self.run_errors(run_id) if self.run_errors and isinstance(run_id, str) else None
        )
        issues = module_issue_summaries(results, provenance, diagnostics or ())
        self._recording_cards(recording_summary(results, provenance, clock, prepared_views))
        modules = self._modules(results, issues)
        if not modules:
            self.layout.addWidget(label("Run an analysis to see module aggregates.", "muted"))
        for module in modules:
            self._module_card(
                module,
                results,
                provenance,
                issues.get(module),
                run_id if diagnostics is not None else "",
            )
        self.layout.addStretch()
        return self.overview_values, self.overview_module_cards, self.overview_gait_charts

    def _clear(self):
        while self.layout.count():
            # The positive count guarantees takeAt(0) returns a layout item.
            item = cast("QLayoutItem", self.layout.takeAt(0))
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.overview_values: dict[tuple[str, str, tuple[str, ...]], QLabel] = {}
        self.overview_module_cards: dict[str, QWidget] = {}
        self.overview_gait_charts: dict[str, dict[str, Any]] = {}

    def _recording_cards(self, entries):
        if entries:
            panel = QWidget()
            panel.setObjectName("recordingOverviewFields")
            grid = QGridLayout(panel)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(10)
            index = 0
            for title, value in entries:
                box, inside = card()
                inside.setAlignment(Qt.AlignmentFlag.AlignTop)
                heading = label(title, "muted")
                heading.setWordWrap(True)
                inside.addWidget(heading)
                display = label(str(value), "metricValue")
                display.setWordWrap(True)
                inside.addWidget(display)
                if title == "Recording timespan":
                    index = (index + 2) // 3 * 3
                    grid.addWidget(box, index // 3, 0, 1, 3)
                    box.setToolTip("Recording extent includes the final sample interval.")
                    index += 3
                else:
                    grid.addWidget(box, index // 3, index % 3)
                    if title.endswith("Gaps"):
                        box.setToolTip(
                            tooltip_text(
                                "Interruptions between prepared-data intervals.\nLeading and trailing exclusions reduce coverage but are not counted as gaps."
                            )
                        )
                    index += 1
            self.layout.addWidget(panel)

    @staticmethod
    def _modules(results, issues):
        modules = list(
            dict.fromkeys(
                [
                    *results.get("aggregations", {}),
                    *results.get("metadata", {}),
                    *results.get("quantifications", {}),
                    *results.get("classifications", {}),
                    *issues,
                ]
            )
        )
        return [
            name
            for name in modules
            if name in MODULE_NAMES
            or not name.startswith("desktop_")
            and any(
                name in results.get(stage, {})
                for stage in ("classifications", "quantifications", "aggregations")
            )
        ]

    def _module_card(self, module, results, provenance, issues, run_id):
        panel, content = card()
        panel.setProperty("analysisModule", module)
        self.overview_module_cards[module] = panel
        heading = label(MODULE_NAMES.get(module, module.replace("_", " ").title()), "pageTitle")
        heading.setProperty("analysisModule", module)
        content.addWidget(heading)
        if issues is not None:
            self._issue_summary(content, module, issues, run_id)
        if module == "tremor":
            self._tremor_cards(content, results)
        elif module == "pulse_rate":
            self._pulse_cards(content, results, provenance)
        else:
            aggregate_entries = list(flat_values(results.get("aggregations", {}).get(module, {})))
            if module == "gait":
                aggregate_entries = self._gait_charts(content, results, aggregate_entries)
            self._metric_cards(content, module, "Aggregates", aggregate_entries)
            metadata = results.get("metadata", {}).get(module, {})
            self._metric_cards(content, module, "Metadata", list(flat_values(metadata)))
        self.layout.addWidget(panel)

    def _issue_summary(
        self, content: QVBoxLayout, module: str, issues: ModuleIssues, run_id: str
    ) -> None:
        notice = label(f"{issues.title}\n{issues.description}", "notice")
        notice.setWordWrap(True)
        notice.setProperty("severity", issues.severity)
        notice.setAccessibleName(f"{MODULE_NAMES.get(module, module)} processing summary")
        content.addWidget(notice)
        if run_id and self.open_errors is not None:
            callback = self.open_errors
            action = button("View errors in Runs →", lambda: callback(run_id))
            action.setObjectName("overviewRunErrors")
            action.setAccessibleName(f"View {MODULE_NAMES.get(module, module)} errors in Runs")
            content.addWidget(action, alignment=Qt.AlignmentFlag.AlignLeft)

    def _pulse_cards(self, content, results, provenance):
        grid = QGridLayout()
        grid.setSpacing(10)
        grid.addWidget(self._pulse_availability_card(results, provenance), 0, 0)
        entries = [
            (group, path, value)
            for group, category in (("Aggregates", "aggregations"), ("Metadata", "metadata"))
            for path, value in flat_values(results.get(category, {}).get("pulse_rate", {}))
            if group != "Metadata" or path != ("nr_pr_est",)
        ]
        for index, (group, path, value) in enumerate(entries, start=1):
            grid.addWidget(
                self._metric_card("pulse_rate", group, path, value), index // 3, index % 3
            )
        content.addLayout(grid)

    def _pulse_availability_card(self, results, provenance):
        count, epochs, percentage = pulse_estimate_availability(results, provenance)
        box, inside = card()
        inside.addWidget(label("Pulse-rate estimate availability (%)", "muted"))
        display = label(f"{percentage:.2f}" if percentage is not None else "—", "metricValue")
        returned = f"{count:,}" if count is not None else "unavailable"
        possible = f"{epochs:,}" if epochs is not None else "unavailable"
        explanation = (
            "Returned pulse-rate estimates ÷ complete 2-second epochs in the full recording timespan × 100.\n"
            f"Returned estimates: {returned}. Complete 2-second epochs: {possible}.\n"
            "The timespan includes gaps and excluded edges. No deductions for signal quality or pipeline boundaries; "
            "a final partial epoch is not counted. This measures estimate availability, not PPG quality."
        )
        if percentage is None:
            explanation += (
                "\nPercentage unavailable without both counts and at least one complete epoch."
            )
        display.setToolTip(tooltip_text(explanation))
        box.setToolTip(tooltip_text(explanation))
        inside.addWidget(display)
        self.overview_values["pulse_rate", "Metadata", ("estimate_availability",)] = display
        return box

    def _tremor_cards(self, content, results):
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, (group, path, title, value, explanation) in enumerate(
            tremor_overview_entries(results)
        ):
            box, inside = card()
            box.setToolTip(tooltip_text(explanation))
            inside.addWidget(label(title, "muted"))
            try:
                number = float(value)
                text = f"{number:.2f}" if np.isfinite(number) else "—"
            except (TypeError, ValueError, OverflowError):
                text = "—"
            display = label(text, "metricValue")
            display.setToolTip(precision_tooltip(value, text))
            inside.addWidget(display)
            self.overview_values["tremor", group, path] = display
            grid.addWidget(box, index // 3, index % 3)
        content.addLayout(grid)

    def _gait_charts(self, content, results, aggregate_entries):
        from ..gait_overview import build_gait_charts

        charts, self.overview_gait_charts, chart_paths = build_gait_charts(
            results.get("aggregations", {}).get("gait", {}),
            metadata=results.get("metadata", {}).get("gait", {}),
            scroll_area=self.scroll_area,
        )
        for chart in charts:
            content.addWidget(chart)
        return [(path, value) for path, value in aggregate_entries if path not in chart_paths]

    def _metric_cards(self, content, module, heading, entries):
        if not entries:
            if heading == "Aggregates" and not (module == "gait" and self.overview_gait_charts):
                content.addWidget(label("No aggregates returned for this module.", "muted"))
            return
        content.addWidget(label(heading, "sectionTitle"))
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, (path, value) in enumerate(entries):
            grid.addWidget(self._metric_card(module, heading, path, value), index // 3, index % 3)
        content.addLayout(grid)

    def _metric_card(self, module, group, path, value):
        box, inside = card()
        title = " · ".join(readable_key(part) for part in path) or "Value"
        inside.addWidget(label(title, "muted"))
        if value is None or isinstance(value, (float, np.floating)) and not np.isfinite(value):
            text = "—"
        elif isinstance(value, (float, np.floating)):
            text = f"{value:.5g}"
        else:
            text = str(value)
        display = label(text, "metricValue")
        display.setToolTip(precision_tooltip(value, text))
        inside.addWidget(display)
        self.overview_values[(module, group, path)] = display
        return box
