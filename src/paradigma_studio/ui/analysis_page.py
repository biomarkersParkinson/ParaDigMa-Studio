"""Analyze page construction with explicit footer and callback dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..analysis_controller import AnalysisView
from ..analysis_help import (
    DEFAULT_DROP_MISSING_SAMPLES,
    DEFAULT_MAX_GAP_SECONDS,
    DEFAULT_MIN_SECTION_SECONDS,
    DEFAULT_SPLIT_BY_GAPS,
    FIELD_HELP,
    SIGNAL_COLUMNS_HELP_BEFORE_HTML,
    SOURCE,
)
from ..field_scrolling import FieldWheelFilter, PageDoubleSpinBox
from ..theme import LINK_COLOR, light_palette
from ..time_controls import TimeField
from ..widgets import (
    AdaptiveFormColumns,
    ContextComboBox,
    ReadableComboBox,
    WrappedForm,
    button,
    card,
    combo,
    label,
)
from .analysis_figure import signal_columns_help
from .column_mapping import ColumnMappingEditor
from .workspace_callbacks import WorkspaceCallbacks


@dataclass(frozen=True)
class AnalysisFooterView:
    status_row: QWidget
    status_layout: QHBoxLayout
    continue_button: QPushButton


class AnalysisPage:
    """Own Analyze widgets; expose a frozen AnalysisView to its controller."""

    combo = staticmethod(combo)

    def __init__(
        self,
        layout: QVBoxLayout,
        footer: AnalysisFooterView,
        modules: dict[str, str],
        callbacks: WorkspaceCallbacks,
    ) -> None:
        self._layout = layout
        self.status_row, self.status_layout = footer.status_row, footer.status_layout
        self.continue_button = footer.continue_button
        self.modules, self.callbacks = modules, callbacks
        self._syncing_scroll_extent = False
        self._build_analyze()

    def _build_analyze(self):
        layout = self._layout
        layout.setSpacing(12)
        scroll = self.analysis_scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("analysisBody")
        self._scroll_content = content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 4, 0)
        content.setSpacing(16)
        content.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._build_analysis_input(content)
        # The full stack, including wrapped help, must reserve its real height.
        # Otherwise native controls can grow while the parent still allocates
        # a smaller preferred height, consuming the gap below the parameters.
        self.analysis_controls = WrappedForm()
        controls = QVBoxLayout(self.analysis_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(16)
        # WrappedForm already reserves exactly the stack's required height.
        # AlignTop would cap the layout rectangle at its preferred size hint,
        # compressing spacing when help is taller at the current width.
        self.analysis_help = {}
        self.analysis_help_sections = {}
        self.file_badges: dict[str, QLabel] = {}
        self.file_default_buttons: dict[str, QPushButton] = {}
        self._build_analysis_modules(controls)
        self._build_analysis_parameters()
        self._build_analysis_help()
        controls.addWidget(self.settings_panel)
        controls.addWidget(self.analysis_help_panel)
        content.addWidget(self.analysis_controls)
        content.addStretch()
        self._build_analysis_actions()
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        bar = scroll.verticalScrollBar()
        bar.rangeChanged.connect(
            lambda low, high: bar.setStyleSheet(
                "QScrollBar::handle:vertical { background: transparent; }" if high == low else ""
            )
        )
        bar.setStyleSheet("QScrollBar::handle:vertical { background: transparent; }")
        scroll.setWidget(body)
        self.analysis_controls.height_changed.connect(self._sync_scroll_extent)
        for field in body.findChildren(ReadableComboBox):
            field.wheel_scroll_target = scroll
        self._button_wheels = [
            FieldWheelFilter(field, scroll)
            for field in body.findChildren(QAbstractButton)
            if field.window() is body.window()
        ]
        layout.addWidget(scroll, 1)

    def _sync_scroll_extent(self):
        if self._syncing_scroll_extent:
            return
        self._syncing_scroll_extent = True
        try:
            self._scroll_content.activate()
            # The content minimum may shrink without resizing its widget.
            # Deliver that change now so the scrollbar cannot keep its old range.
            QCoreApplication.sendEvent(self.analysis_scroll, QEvent(QEvent.Type.LayoutRequest))
        finally:
            self._syncing_scroll_extent = False

    def _build_analysis_input(self, content):
        panel, input_layout = card()
        input_layout.setContentsMargins(18, 14, 18, 14)
        input_row = QHBoxLayout()
        input_row.addWidget(label("Selected input", "muted"))
        self.analysis_input = label("No recording loaded", "sectionTitle")
        input_row.addWidget(self.analysis_input, 1)
        self.analysis_input_detail = label("", "muted")
        input_row.addWidget(self.analysis_input_detail)
        input_row.addWidget(button("Inspect input", lambda: self.callbacks.navigate(0)))
        input_layout.addLayout(input_row)
        content.addWidget(panel)

    def _build_analysis_modules(self, controls):
        modules = QHBoxLayout()
        module_heading = self.analysis_field(
            "Analysis modules", label("Analysis modules", "sectionTitle"), inline=True
        )
        modules.addWidget(module_heading)
        self.module_requirements = label("", "muted")
        self.module_requirements.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.module_buttons = {}
        for name in ("Gait", "Tremor", "Pulse rate"):
            item = button(name)
            item.setObjectName("module")
            item.setProperty("analysisModule", self.modules[name])
            item.setCheckable(True)
            self.module_buttons[name] = item
            modules.addWidget(item, 1)
        self.module_buttons["Gait"].setChecked(True)
        controls.addLayout(modules)

    def _build_analysis_parameters(self):
        self.settings_panel, parameter_card = card()
        parameter_card.setContentsMargins(18, 16, 18, 16)
        parameter_card.setSpacing(14)
        parameter_card.setAlignment(Qt.AlignmentFlag.AlignTop)
        # Reserve the form's actual minimum before help changes the outer
        # layout. Otherwise Qt briefly clips the bottom rows while settling.
        parameter_card.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.analysis_parameter_fields = WrappedForm()
        self.analysis_parameter_fields.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        parameters = QVBoxLayout(self.analysis_parameter_fields)
        parameters.setContentsMargins(0, 0, 0, 0)
        parameters.setSpacing(14)
        # WrappedForm reserves the exact height. AlignTop would cap nested
        # layouts at their unwrapped hints and consume row spacing when origin wraps.
        parameter_card.addWidget(
            self.analysis_parameter_fields, alignment=Qt.AlignmentFlag.AlignTop
        )
        parameter_header = QHBoxLayout()
        parameter_header.addWidget(label("Analysis parameters", "sectionTitle"))
        parameter_header.addWidget(self.module_requirements, 1)
        parameters.addLayout(parameter_header)
        self.metadata_notice = label("", "muted")
        self.metadata_notice.setWordWrap(True)
        self.metadata_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.metadata_notice.setAccessibleName("Input metadata differences")
        self.metadata_notice.hide()
        parameters.addWidget(self.metadata_notice)
        left, right = QVBoxLayout(), QVBoxLayout()
        columns = AdaptiveFormColumns(left, right)
        for column in (left, right):
            column.setSpacing(12)
        units = QFormLayout()
        units.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        units.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        units.setHorizontalSpacing(10)
        units.setVerticalSpacing(12)
        units.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self._build_analysis_units(units)
        right.addLayout(units)
        self._build_analysis_origin(right)
        self._build_analysis_segmentation(right)
        self.mapping = ColumnMappingEditor()
        left.addWidget(self.analysis_field("Signal columns", self.mapping))
        left.addStretch()
        right.addStretch()
        parameters.addLayout(columns)

    def _build_analysis_units(self, form):
        self.side = self.combo(["left", "right"], combo_type=ContextComboBox)
        self.acc = self.combo(["g", "m/s²"])
        for index, unit in enumerate(("g", "m/s^2")):
            self.acc.setItemData(index, unit)
        self.gyro = self.combo(["deg/s", "rad/s"])
        self.time = self.combo(
            [
                "relative_s",
                "relative_ms",
                "absolute_s",
                "absolute_ms",
                "difference_s",
                "difference_ms",
            ]
        )
        for widget in (self.side, self.acc, self.gyro, self.time):
            widget.setMinimumWidth(160)
        for title, widget in (
            ("Watch side", self.side),
            ("Acceleration units", self.acc),
            ("Gyroscope units", self.gyro),
            ("Time units", self.time),
        ):
            control: QWidget = widget
            if title != "Watch side":
                control = WrappedForm()
                selector, action = QHBoxLayout(), QHBoxLayout()
                selector.addWidget(widget)
                reset = button("Default")
                reset.setAccessibleName(f"Restore {title.lower()} from file")
                reset.hide()
                self.file_default_buttons[title] = reset
                action.addWidget(reset, alignment=Qt.AlignmentFlag.AlignRight)
                # Keep the full action reachable when native label widths leave
                # too little room beside the selector, as for Time origin.
                row = AdaptiveFormColumns(selector, action, right_stretch=0)
                row.setSpacing(6)
                control.setLayout(row)
            self.analysis_field(title, control, form=form)
            widget.setAccessibleName(title)

    def _build_analysis_segmentation(self, parameters):
        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self.gaps = QCheckBox("Split recordings at time gaps")
        self.gaps.setChecked(DEFAULT_SPLIT_BY_GAPS)
        self.drop_missing = QCheckBox("Exclude missing sensor samples")
        self.drop_missing.setChecked(DEFAULT_DROP_MISSING_SAMPLES)
        for checkbox in (self.gaps, self.drop_missing):
            checkbox.setPalette(light_palette())
        form.addRow(
            self.analysis_field("Exclude missing sensor samples", self.drop_missing, inline=True)
        )
        self.segmentation_controls = WrappedForm()
        sections = QGridLayout(self.segmentation_controls)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setColumnStretch(1, 1)
        sections.setHorizontalSpacing(10)
        sections.setVerticalSpacing(12)
        sections.setAlignment(Qt.AlignmentFlag.AlignTop)
        sections.addWidget(
            self.analysis_field("Split recordings at time gaps", self.gaps, inline=True), 0, 0, 1, 2
        )
        self.max_gap, self.min_segment = PageDoubleSpinBox(), PageDoubleSpinBox()
        self.section_reset_buttons = {}
        for title, widget, default in (
            ("Maximum gap", self.max_gap, DEFAULT_MAX_GAP_SECONDS),
            ("Minimum section duration", self.min_segment, DEFAULT_MIN_SECTION_SECONDS),
        ):
            # Native preferred widths can exceed minimumSizeHint. Allow that
            # space to be shared before stacking the two parameter columns.
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            widget.setRange(0.01, 86400)
            widget.setValue(default)
            widget.setSuffix(" s")
            widget.setDecimals(2)
            widget.setAccessibleName(title)
            reset = button(
                "Default", lambda checked=False, spin=widget, value=default: spin.setValue(value)
            )
            reset.setAccessibleName(f"Reset {title.lower()} to the official default")
            self.section_reset_buttons[title] = reset
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(widget, 1)
            row_layout.addWidget(reset)
            self.analysis_field(title, row, form=sections)
        form.addRow(self.segmentation_controls)
        parameters.addLayout(form)

    def _build_analysis_origin(self, parameters):
        self.clock_input = TimeField("Time origin", origin=True)
        self.clock_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.origin_reset = button("Default", self.callbacks.reset_origin)
        origin_row = WrappedForm()
        clock_group, reset_group = QHBoxLayout(), QHBoxLayout()
        clock_group.addWidget(self.clock_input)
        reset_group.addWidget(self.origin_reset, alignment=Qt.AlignmentFlag.AlignRight)
        origin_layout = AdaptiveFormColumns(clock_group, reset_group, right_stretch=0)
        origin_layout.setSpacing(12)
        origin_row.setLayout(origin_layout)
        origin_form = QFormLayout()
        origin_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        origin_form.setHorizontalSpacing(10)
        origin_form.setVerticalSpacing(12)
        origin_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self.analysis_field("Time origin", origin_row, form=origin_form)
        parameters.addLayout(origin_form)

    def _build_analysis_help(self):
        # Help belongs below the complete parameter card. Expanding a field's row changes
        # QFormLayout alignment and column widths, shifting unrelated labels.
        self.analysis_help_panel, help_layout = card()
        help_layout.setSpacing(12)
        for title, (info, description) in self.analysis_help.items():
            section = QWidget()
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(4)
            section_layout.addWidget(label(title, "sectionTitle"))
            if title == "Signal columns":
                section_layout.addWidget(signal_columns_help(description, FIELD_HELP[title][1]))
            else:
                section_layout.addWidget(description)
            section.hide()
            self.analysis_help_sections[title] = section
            info.toggled.connect(
                lambda checked, title=title: self.callbacks.toggle_analysis_help(title, checked)
            )
            help_layout.addWidget(section)
        self.analysis_help_panel.hide()

    def _build_analysis_actions(self):
        self.run_button = button("Run Analysis", self.callbacks.run_analysis, primary=True)
        self.run_button.setShortcut("Ctrl+Return")
        self.run_button.setEnabled(False)
        self.run_button.setMinimumWidth(170)
        self.stop_button = button("Stop Analysis", self.callbacks.stop_analysis)
        self.stop_button.setEnabled(False)
        self.status_layout.addWidget(self.stop_button)
        self.status_layout.addWidget(self.run_button)
        # Keep the footer height stable when navigation hides its actions.
        # Otherwise Results can resize/repaint after its first row selection.
        self.status_row.setMinimumHeight(
            max(
                control.sizeHint().height()
                for control in (self.continue_button, self.stop_button, self.run_button)
            )
        )

    def analysis_field(self, title, control, *, form=None, inline=False):
        """Accessible help toggles; explanations are kept outside the form rows."""
        text, reference = FIELD_HELP[title]
        info = button("i")
        info.setObjectName("helpInfo")
        info.setFixedSize(22, 22)
        info.setCheckable(True)
        info.setAccessibleName(f"Information: {title}")
        url = reference if reference.startswith("https://") else SOURCE + reference
        if title == "Signal columns":
            help_html = SIGNAL_COLUMNS_HELP_BEFORE_HTML
        else:
            help_html = (
                f'{escape(text)}<br><a style="color: {LINK_COLOR}; text-decoration: underline;" '
                f'href="{url}">ParaDigMa documentation</a>'
            )
        description = QLabel(help_html)
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        description.setTextFormat(Qt.TextFormat.RichText)
        description.setOpenExternalLinks(True)
        description.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        description.setAccessibleName(f"Help: {title}")
        description.setObjectName("fieldHelp")
        description.hide()
        self.analysis_help[title] = (info, description)
        control.setAccessibleName(title)
        heading = self._analysis_heading(title, control, info, inline=inline)
        body = QWidget()
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)
        content.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        if form is not None:
            content.setAlignment(Qt.AlignmentFlag.AlignTop)
            content.addWidget(control, alignment=Qt.AlignmentFlag.AlignTop)
            if isinstance(form, QGridLayout):
                index = form.rowCount()
                form.addWidget(heading, index, 0, Qt.AlignmentFlag.AlignTop)
                form.addWidget(body, index, 1, Qt.AlignmentFlag.AlignTop)
            else:
                form.addRow(heading, body)
        else:
            content.addWidget(heading)
            if not inline:
                content.addWidget(control)
        return body

    def _analysis_heading(self, title, control, info, *, inline):
        heading = QWidget()
        heading_layout = QVBoxLayout(heading)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(6)
        title_label = control if inline else label(title, "muted")
        if not inline:
            title_label.setBuddy(control)
        row.addWidget(title_label)
        row.addWidget(info, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addStretch()
        heading_layout.addLayout(row)
        if title in {"Acceleration units", "Gyroscope units", "Time units", "Time origin"}:
            badge = label("From file", "muted")
            badge.setObjectName("fileDefaultBadge")
            badge.setAccessibleName(f"{title}: from file")
            badge.setWordWrap(False)
            badge.hide()
            self.file_badges[title] = badge
            heading_layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)
        return heading

    def view(self, parent: QWidget, status: QLabel, log: QPlainTextEdit) -> AnalysisView:
        return AnalysisView(
            parent=parent,
            acc=self.acc,
            analysis_controls=self.analysis_controls,
            analysis_help=self.analysis_help,
            analysis_help_panel=self.analysis_help_panel,
            analysis_help_sections=self.analysis_help_sections,
            analysis_scroll=self.analysis_scroll,
            clock_input=self.clock_input,
            drop_missing=self.drop_missing,
            file_badges=self.file_badges,
            file_default_buttons=self.file_default_buttons,
            gaps=self.gaps,
            gyro=self.gyro,
            log=log,
            mapping=self.mapping,
            metadata_notice=self.metadata_notice,
            max_gap=self.max_gap,
            min_segment=self.min_segment,
            module_buttons=self.module_buttons,
            module_requirements=self.module_requirements,
            run_button=self.run_button,
            side=self.side,
            status=status,
            stop_button=self.stop_button,
            time=self.time,
        )
