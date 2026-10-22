"""Shared Analyze sizing and visibility checks; no application behavior is mocked."""

from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton


def assert_fully_visible(control):
    visible = control.visibleRegion().boundingRect()
    assert visible.contains(control.rect()), (
        control.accessibleName() or control.objectName(),
        control.rect(),
        visible,
    )


def configure_native_analysis_sizes(window, control_minimum_height, larger_surrounding_controls):
    # Larger native Windows control hints overflowed the previous layout even
    # though the same fields fitted under the headless Linux font metrics.
    for control in (
        window.side,
        window.acc,
        window.gyro,
        window.time,
        window.max_gap,
        window.min_segment,
    ):
        control.setMinimumHeight(control_minimum_height)
    if larger_surrounding_controls:
        # Input controls alone did not reproduce the Windows overflow. Native
        # labels, checkboxes and action buttons also consume vertical space.
        body = window.analysis_scroll.widget()
        for control in body.findChildren(QLabel):
            if control.objectName() != "fieldHelp":
                control.setMinimumHeight(28)
        for control in body.findChildren(QCheckBox):
            control.setMinimumHeight(36)
        for control in body.findChildren(QPushButton):
            if control.objectName() != "helpInfo":
                control.setMinimumHeight(44)
