"""Opening help must not reflow the Analyze labels, options or action buttons."""

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy, QVBoxLayout, QWidget

from paradigma_studio.app import MainWindow
from paradigma_studio.widgets import WrappedForm


def test_growing_wrapped_stack_updates_its_layout_bounds_without_compressing_spacing():
    app = QApplication.instance() or QApplication([])

    class NativeHint(QWidget):
        def __init__(self, minimum, wrapped=False):
            super().__init__()
            self.wrapped = wrapped
            self.setMinimumHeight(minimum)
            policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            policy.setHeightForWidth(True)
            self.setSizePolicy(policy)

        def heightForWidth(self, width):
            # Native controls may have a larger enforced minimum than their
            # preferred hint; help grows independently when its text wraps.
            return (160 if width < 350 else 100) if self.wrapped else 20

    stack = WrappedForm()
    layout = QVBoxLayout(stack)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    parameters, help_box = NativeHint(80), NativeHint(10, wrapped=True)
    layout.addWidget(parameters)
    layout.addWidget(help_box)
    stack.resize(300, 100)
    stack.show()
    try:
        for width in (300, 450, 240):
            stack.resize(width, 100)
            QTest.qWait(20)
            assert layout.geometry() == stack.contentsRect()
            assert parameters.height() >= 80
            assert help_box.height() >= help_box.heightForWidth(width)
            assert help_box.y() - parameters.y() - parameters.height() >= 16
            assert help_box.y() + help_box.height() <= stack.height()
    finally:
        stack.close()
        app.processEvents()


@pytest.mark.parametrize("style", ["Fusion", "Windows"])
@pytest.mark.parametrize("wide_controls", [False, True])
@pytest.mark.parametrize("size", [(1200, 900), (960, 650)])
def test_help_geometry_is_ready_before_painting_resumes(tmp_path, style, wide_controls, size):
    app = QApplication.instance() or QApplication([])
    original_style = app.style().objectName()
    app.setStyle(style)
    window = MainWindow(tmp_path)
    if wide_controls:
        window.setStyleSheet(window.styleSheet() + "\nQWidget { font-size: 18px; }")
        for control in (window.side, window.acc, window.gyro, window.time):
            control.setMinimumWidth(280)
            control.setMinimumHeight(44)
        for label in window.analysis_parameter_fields.findChildren(QLabel):
            label.setMinimumHeight(28)
        window.clock_input.calendar.setMinimumWidth(620)
        window.origin_reset.setMinimumWidth(200)
    window.navigate(1)
    window.resize(*size)
    window.show()
    QTest.qWait(40)
    body = window.analysis_scroll.widget()
    resume_updates = body.setUpdatesEnabled
    snapshots = []

    def observe_first_paint(enabled):
        if enabled and not window.analysis_help_panel.isHidden():
            # Do not process events here: the layout must be safe at the point
            # painting resumes, not only after a queued LayoutRequest fixes it.
            top = window.analysis_help_panel.mapTo(body, QPoint(0, 0)).y()
            bottom = window.settings_panel.mapTo(
                body, QPoint(0, window.settings_panel.height())
            ).y()
            snapshots.append(
                (
                    top - bottom,
                    window.analysis_controls.rect().contains(window.analysis_help_panel.geometry()),
                )
            )
        resume_updates(enabled)
        if enabled and not window.analysis_help_panel.isHidden():
            # Exercise an immediate paint as well, including offscreen help.
            target = QPixmap(window.analysis_help_panel.size())
            window.analysis_help_panel.render(target)

    body.setUpdatesEnabled = observe_first_paint
    try:
        for pause in (True, False):
            for name in (
                "Watch side",
                "Signal columns",
                "Maximum gap",
                "Time origin",
                "Analysis modules",
                "Analysis modules",
                "Signal columns",
                "Signal columns",
            ):
                window.analysis_help[name][0].click()
                if pause:
                    QTest.qWait(20)
        assert snapshots
        assert all(gap >= 16 and contained for gap, contained in snapshots), snapshots
    finally:
        body.setUpdatesEnabled = resume_updates
        window.close()
        app.processEvents()
        app.setStyle(original_style)


@pytest.mark.parametrize("size", [(1200, 900), (960, 650)])
def test_help_never_temporarily_clips_lower_fields_or_paints_over_them(tmp_path, size):
    from paradigma_studio.theme import STYLESHEET

    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.setStyleSheet(STYLESHEET)
    window.navigate(1)
    window.resize(*size)
    window.show()
    QTest.qWait(40)
    baseline = window.settings_panel.height()
    events = []

    class LayoutWatch(QObject):
        def eventFilter(self, obj, event):
            if event.type() in (QEvent.Resize, QEvent.Paint):
                if obj is window.settings_panel:
                    events.append(("card", window.settings_panel.height() >= baseline))
                if event.type() == QEvent.Paint and (
                    obj is window.analysis_help_panel
                    or obj in [description for _, description in window.analysis_help.values()]
                ):
                    events.append(
                        (
                            "help",
                            window.analysis_help_panel.y()
                            >= window.settings_panel.y() + window.settings_panel.height(),
                        )
                    )
                if obj is window.mapping and event.type() == QEvent.Paint:
                    child = window.mapping
                    while child is not window.settings_panel:
                        parent = child.parentWidget()
                        events.append(
                            (
                                "mapping",
                                child.y() >= 0 and child.y() + child.height() <= parent.height(),
                            )
                        )
                        child = parent
            return False

    watcher = LayoutWatch(window)
    for widget in (
        window.settings_panel,
        window.analysis_help_panel,
        window.mapping,
        *[description for _, description in window.analysis_help.values()],
    ):
        widget.installEventFilter(watcher)
    try:
        for name in (
            "Watch side",
            "Signal columns",
            "Maximum gap",
            "Time origin",
            "Analysis modules",
        ):
            window.analysis_help[name][0].click()
            QTest.qWait(20)
            assert window.analysis_scroll.widget().updatesEnabled()
        window.analysis_help["Analysis modules"][0].click()
        QTest.qWait(20)
        # Help is below the viewport in a smaller window. Scroll it into view
        # so the test checks an actual paint there too, rather than expecting
        # Qt to paint an offscreen widget.
        window.analysis_help["Signal columns"][0].click()
        QTest.qWait(20)
        window.analysis_scroll.ensureWidgetVisible(window.analysis_help_panel)
        QTest.qWait(20)
        assert events and all(valid for _, valid in events), events
        assert {"card", "mapping", "help"}.issubset({kind for kind, _ in events})
    finally:
        window.close()
        app.processEvents()


def layout_bounds(window, control):
    """Useful Windows diagnostics if a native ancestor still clips a field."""
    ancestors = []
    while control is not window.analysis_scroll:
        ancestors.append(
            (
                type(control).__name__,
                control.geometry().getRect(),
                control.minimumSize().toTuple(),
                control.maximumSize().toTuple(),
                control.visibleRegion().boundingRect().getRect(),
            )
        )
        control = control.parentWidget()
    bar = window.analysis_scroll.verticalScrollBar()
    return {"ancestors": ancestors, "scroll": (bar.value(), bar.maximum())}


@pytest.mark.parametrize("calendar_width", [382, 620])
@pytest.mark.parametrize("reset_width", [0, 200])
def test_time_origin_fits_viewport_with_larger_native_editor_widths(
    tmp_path, calendar_width, reset_width
):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.setStyleSheet(window.styleSheet() + "\nQWidget { font-size: 18px; }")
    for control in (window.side, window.acc, window.gyro, window.time):
        control.setMinimumWidth(280)
        control.setMinimumHeight(44)
    for label in window.analysis_parameter_fields.findChildren(QLabel):
        label.setMinimumHeight(28)
    # The unused numeric editor's large native hint must not widen a calendar
    # field. A genuinely wide calendar must remain readable by wrapping its row.
    window.clock_input.seconds.setMinimumWidth(620)
    window.clock_input.calendar.setMinimumWidth(calendar_width)
    # Native action-button hints can exceed the Linux hints independently of
    # the date editor. Both must stay reachable without widening the viewport.
    window.origin_reset.setMinimumWidth(reset_width)
    window.navigate(1)
    window.show()
    try:
        for size in ((960, 650), (1450, 920), (960, 650)):
            window.resize(*size)
            QTest.qWait(40)
            body = window.analysis_scroll.widget()
            assert body.width() <= window.analysis_scroll.viewport().width()
            for control in (
                window.mapping,
                window.clock_input,
                window.clock_input.calendar,
                window.origin_reset,
            ):
                center = control.mapTo(body, control.rect().center())
                window.analysis_scroll.ensureVisible(
                    center.x(), center.y(), 0, control.height() // 2 + 8
                )
                app.processEvents()
                assert control.visibleRegion().boundingRect().contains(control.rect()), (
                    layout_bounds(window, control)
                )
            assert window.clock_input.editors.currentWidget() is window.clock_input.calendar
            assert window.clock_input.calendar.width() >= calendar_width
            fields = window.analysis_parameter_fields
            labels = fields.findChildren(QLabel)
            widgets = (window.mapping, window.clock_input, window.origin_reset, *labels)

            def positions(body=body, widgets=widgets):
                app.processEvents()
                return [
                    widget.mapTo(body, QPoint(0, 0)).toTuple() + widget.size().toTuple()
                    for widget in widgets
                ]

            baseline = positions()
            for title in ("Time origin", "Signal columns", "Watch side"):
                window.analysis_help[title][0].click()
                QTest.qWait(20)
                assert positions() == baseline
            window.analysis_help["Watch side"][0].click()
            assert positions() == baseline
    finally:
        window.close()
        app.processEvents()


@pytest.mark.parametrize("size", [(1450, 920), (960, 650)])
@pytest.mark.parametrize(
    "native_height, native_width, font_size",
    [(0, 0, 13), (44, 0, 13), (30, 280, 13), (44, 280, 13), (44, 280, 18)],
)
def test_all_analysis_labels_and_fields_stay_fixed_when_any_help_opens(
    tmp_path, size, native_height, native_width, font_size
):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    window.resize(*size)
    fields = _configure_native_analysis_fields(window, native_height, native_width, font_size)
    window.navigate(1)
    window.show()
    app.processEvents()
    body = window.analysis_scroll.widget()
    labels = [
        widget
        for widget in body.findChildren(QLabel)
        if not window.analysis_help_panel.isAncestorOf(widget)
    ]
    widgets = [*fields, *labels, *[info for info, _ in window.analysis_help.values()]]

    def positions():
        app.processEvents()
        return [
            (
                widget.mapTo(body, QPoint(0, 0)).x(),
                widget.mapTo(body, QPoint(0, 0)).y(),
                widget.width(),
                widget.height(),
            )
            for widget in widgets
        ]

    baseline = positions()
    assert window.analysis_controls.layout().spacing() == 16
    # Wrapped native fields still fit completely inside their form, including
    # the final rows; scrolling cannot reveal a clipped child of the form.
    for widget in fields:
        if window.analysis_parameter_fields.isAncestorOf(widget):
            bottom = widget.mapTo(window.analysis_parameter_fields, QPoint(0, widget.height())).y()
            assert bottom <= window.analysis_parameter_fields.height()
    center = window.mapping.mapTo(body, window.mapping.rect().center())
    window.analysis_scroll.ensureVisible(
        center.x(), center.y(), 0, window.mapping.height() // 2 + 8
    )
    app.processEvents()
    assert window.mapping.visibleRegion().boundingRect().contains(window.mapping.rect()), (
        layout_bounds(window, window.mapping)
    )
    actions = [window.run_button.pos(), window.stop_button.pos()]

    def module_bounds():
        return [
            (button.mapTo(window, QPoint(0, 0)), button.size())
            for button in window.module_buttons.values()
        ]

    modules = module_bounds()
    try:
        for title, (info, description) in window.analysis_help.items():
            info.click()
            QTest.qWait(20)
            assert positions() == baseline, title
            assert module_bounds() == modules, title
            assert [window.run_button.pos(), window.stop_button.pos()] == actions
            assert description.isVisible()
            assert sum(button.isChecked() for button, _ in window.analysis_help.values()) == 1
            assert not window.settings_panel.isAncestorOf(description)
            gap = window.analysis_help_panel.mapTo(body, QPoint(0, 0)).y() - (
                window.settings_panel.mapTo(body, QPoint(0, window.settings_panel.height())).y()
            )
            assert gap >= window.analysis_controls.layout().spacing(), (title, gap)
            info.click()
            QTest.qWait(20)
            assert positions() == baseline, title
        for info, _ in window.analysis_help.values():
            info.click()
            assert positions() == baseline
            assert sum(button.isChecked() for button, _ in window.analysis_help.values()) == 1
            assert (
                sum(description.isVisible() for _, description in window.analysis_help.values())
                == 1
            )
        for info, _ in window.analysis_help.values():
            if info.isChecked():
                info.click()
            assert positions() == baseline
        assert window.analysis_help_panel.isHidden()
    finally:
        window.close()
        app.processEvents()


def _configure_native_analysis_fields(window, native_height, native_width, font_size):
    if font_size != 13:
        # A taller, wrapped explanation must use its height at the available
        # width, rather than the stack's preferred height at a wider width.
        # Larger font metrics reproduce the compressed Windows gap on Linux.
        window.setStyleSheet(window.styleSheet() + f"\nQWidget {{ font-size: {font_size}px; }}")
    fields = [
        window.side,
        window.acc,
        window.gyro,
        window.time,
        window.mapping,
        window.max_gap,
        window.min_segment,
        window.clock_input,
        window.prepared,
        window.gaps,
        window.drop_missing,
        *window.module_buttons.values(),
    ]
    for control in fields[:4]:
        control.setMinimumHeight(native_height)
        if native_width:
            control.setMinimumWidth(native_width)
    if native_width:
        for label in window.analysis_parameter_fields.findChildren(QLabel):
            label.setMinimumHeight(28)
    return fields


@pytest.mark.parametrize("grid_width", [0, 314, 570])
def test_wrapped_grid_reserves_all_nested_control_bounds_and_editor_stays_fully_reachable(
    tmp_path, grid_width
):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    if grid_width == 570:
        # Stress a wide mapping table under larger Windows font metrics.
        # The shorter header now sits above the table rather than beside it.
        window.setStyleSheet(window.styleSheet() + "\nQWidget { font-size: 18px; }")
    for control in (window.side, window.acc, window.gyro, window.time):
        control.setMinimumWidth(280)
        control.setMinimumHeight(30)
    for label in window.analysis_parameter_fields.findChildren(QLabel):
        label.setMinimumHeight(28)
        if label.text() == "Minimum section duration":
            label.setFixedWidth(70)  # A multi-line native heading.
    window.mapping.setMinimumWidth(grid_width)
    window.navigate(1)
    window.resize(960, 650)
    window.show()
    QTest.qWait(40)
    try:
        for size in ((960, 650), (1450, 920), (960, 650)):
            window.resize(*size)
            QTest.qWait(30)
            assert (
                window.analysis_scroll.widget().width() <= window.analysis_scroll.viewport().width()
            )
            if grid_width == 570:
                form = window.analysis_parameter_fields
                first_end = window.prepared.mapTo(form, QPoint(0, window.prepared.height()))
                second_start = window.mapping.mapTo(form, QPoint(0, 0))
                if size[0] == 960:
                    assert second_start.y() >= first_end.y() + 20
                else:
                    assert second_start.x() > first_end.x()
                    assert second_start.y() < first_end.y()
            for help_name in ("Watch side", "Signal columns", "Minimum section duration"):
                _assert_nested_analysis_controls_fit(window)
                center = window.mapping.mapTo(
                    window.analysis_scroll.widget(), window.mapping.rect().center()
                )
                window.analysis_scroll.ensureVisible(
                    center.x(), center.y(), 0, window.mapping.height() // 2 + 8
                )
                app.processEvents()
                assert window.mapping.visibleRegion().boundingRect().contains(window.mapping.rect())
                window.analysis_help[help_name][0].click()
                QTest.qWait(30)
    finally:
        window.close()
        app.processEvents()


def _assert_nested_analysis_controls_fit(window):
    for control in (window.mapping, window.max_gap, window.min_segment):
        # Inspect every ancestor: children must fit horizontally
        # as well as vertically, including after a width change.
        child = control
        while child is not window.analysis_scroll.widget():
            parent = child.parentWidget()
            assert parent.rect().contains(child.geometry()), (
                type(child).__name__,
                child.geometry(),
                type(parent).__name__,
                parent.geometry(),
            )
            child = parent
