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
    assert data["quantified_rows"] > 0
    assert len(data["models_loaded"]) == 4
    assert data["qt_plot_rendered"]
    assert data["export_verified"]
    assert data["cwa_samples"] == 36400
    assert data["cwa_gait_rows"] > 0
    assert data["cwa_plot_rendered"]
