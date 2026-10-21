"""Analysis settings, help documentation and display-origin configuration."""

import pandas as pd
import pytest
from conftest import wait_for_previews
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from paradigma_studio.theme import LINK_COLOR


def test_axis_and_mapping_fields_follow_their_columns_with_readable_official_guide(window):
    window.navigate(1)
    window.resize(1450, 920)
    QTest.qWait(30)
    fields = [window.side, window.acc, window.gyro, window.time]
    assert len({field.mapTo(window, field.rect().topLeft()).x() for field in fields}) == 1
    assert window.mapping.mapTo(window, window.mapping.rect().topLeft()).x() > max(
        field.mapTo(window, field.rect().topRight()).x() for field in fields
    )
    assert window.drop_missing.mapTo(window, window.drop_missing.rect().topLeft()).y() > (
        window.time.mapTo(window, window.time.rect().bottomLeft()).y()
    )
    assert window.clock_input.mapTo(window, window.clock_input.rect().topLeft()).x() < (
        window.mapping.mapTo(window, window.mapping.rect().topLeft()).x()
    )
    for _info, description in window.analysis_help.values():
        assert f"color: {LINK_COLOR}" in description.text()
    info, description = window.analysis_help["Signal columns"]
    info.click()
    assert '<img src="' in description.text() and "directions_axes.png" in description.text()
    assert (
        "https://biomarkersparkinson.github.io/paradigma/guides/coordinate_system.html"
        in description.text()
    )


def test_analyze_time_origin_defaults_reset_and_never_changes_pipeline_arguments(
    window, monkeypatch
):
    from paradigma_studio import app as desktop

    original = pd.DataFrame(
        {
            "time": [0.0, 0.01, 0.02],
            "time_dt": pd.date_range("2026-10-07T12:00:00.123456789Z", periods=3, freq="10ms"),
            **{f"gyroscope_{axis}": [1.0, 2.0, 3.0] for axis in "xyz"},
        }
    )
    window.set_modules(["tremor"])
    window.loaded(("sensor.csv", original))
    wait_for_previews(window)
    derived_origin = window.clock_input.text()
    assert pd.Timestamp(derived_origin) == original.time_dt.iloc[0]
    window.clock_input.setText("2020-01-01T08:00:00+02:00")
    window.origin_edited()
    captured = []
    monkeypatch.setattr(
        desktop,
        "run_isolated_analysis",
        lambda frame, settings, logger, cancel: captured.append((frame, settings)),
    )
    monkeypatch.setattr(window, "start_job", lambda function, callback: function(None))
    window.run_analysis()
    assert len(captured) == 1 and "plot_time_origin" not in captured[0][1]
    pd.testing.assert_frame_equal(captured[0][0], original)
    clock = window._run_state.current_run["settings"]["plot_time_origin"]["clock"]
    assert pd.Timestamp(clock["origin"]) == pd.Timestamp("2020-01-01T08:00:00+02:00")
    assert (
        clock["timezone"] == "UTC"
    )  # Preserve the recording zone while accepting an explicit offset.
    window.reset_origin()
    assert window.clock_input.text() == derived_origin
    assert window.origin_setting() == {"mode": "automatic"}


def test_mapping_label_and_editor_stay_together_when_neighboring_help_expands(window):
    window.navigate(1)
    window.resize(1450, 920)
    heading = next(
        label
        for label in window.settings_panel.findChildren(QLabel)
        if label.text() == "Signal columns"
    )

    def positions():
        QTest.qWait(30)
        return heading.mapTo(window, heading.rect().topLeft()).y(), window.mapping.mapTo(
            window, window.mapping.rect().topLeft()
        ).y()

    initial = positions()
    for name in ("Watch side", "Minimum section duration", "Signal columns"):
        window.analysis_help[name][0].click()
        label_y, editor_y = positions()
        assert 0 <= editor_y - label_y - heading.height() <= 8
        assert editor_y - initial[1] == pytest.approx(label_y - initial[0], abs=2)
