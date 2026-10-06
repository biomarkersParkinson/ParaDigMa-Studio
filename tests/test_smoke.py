"""Exercise the same startup/analysis probe used by the Windows build."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_desktop_smoke_entrypoint(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, str(root / "desktop.py"), "--smoke-test", str(report)],
        cwd=tmp_path, env={**os.environ, "MPLCONFIGDIR": str(tmp_path / "mpl")},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr + (
        report.read_text() if report.exists() else "No smoke report"
    )
    data = json.loads(report.read_text())
    assert data["status"] == "passed"
    assert data["app_icon_rendered"]
    assert data["workspace_navigation_verified"]
    assert data["integrated_page_controls_verified"]
    assert data["dropdown_indicator_rendered"]
    assert data["module_multiselection_verified"]
    assert data["all_module_execution_verified"]
    assert data["inline_analysis_help_verified"]
    assert data["paradigma_acknowledgement_verified"]
    assert data["aggregate_overview_verified"]
    assert data["absolute_recording_clock_verified"]
    assert data["estimated_gait_positions_verified"]
    assert data["linked_result_selection_verified"]
    assert data["gait_sensor_context_verified"]
    assert data["run_history_reopened"]
    assert data["quantified_rows"] > 0
    assert len(data["models_loaded"]) == 4
    assert data["qt_plot_rendered"]
    assert data["export_verified"]
    assert data["cwa_samples"] == 36400
    assert data["cwa_gait_rows"] > 0
    assert data["cwa_plot_rendered"]
    assert data["empatica_samples"] == 115904
    assert data["empatica_inspection_verified"]
    assert data["physilog_excluded_samples"] == 10
    assert data["physilog_continuous_sections"] == 4
    assert data["physilog_gait_rows"] > 0
