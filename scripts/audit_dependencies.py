"""Audit every installed distribution and retain a report for the artifact."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def is_python_arrow_exception(package, vulnerability):
    # CVE-2026-25087 requires a C++ IPC pre-buffering API that is not exposed
    # through Python. The advisory explicitly says Python bindings are unaffected.
    # ParaDigMa <23 pyarrow constraint prevents upgrading to the patched C++ wheel.
    identifiers = {vulnerability["id"], *vulnerability.get("aliases", [])}
    return package.lower() == "pyarrow" and "CVE-2026-25087" in identifiers


def classify_findings(report):
    """Retain raw pip-audit results and scope the one reviewed exception."""
    dependencies = report.get("dependencies")
    if not dependencies:
        raise RuntimeError("Dependency audit returned no package results.")
    blockers = []
    exceptions = []
    for dependency in dependencies:
        # The first-party app is verified against its tagged source, not PyPI.
        if dependency["name"].lower().replace("_", "-") == "paradigma-studio":
            continue
        if dependency.get("skip_reason"):
            blockers.append(
                {"package": dependency["name"], "skip_reason": dependency["skip_reason"]}
            )
        for vulnerability in dependency.get("vulns", []):
            finding = {
                "package": dependency["name"],
                "version": dependency["version"],
                "id": vulnerability["id"],
            }
            if is_python_arrow_exception(dependency["name"], vulnerability):
                exceptions.append(
                    {
                        **finding,
                        "reason": "CVE-2026-25087 explicitly excludes Python bindings; see SECURITY.md.",
                    }
                )
            else:
                blockers.append(finding)
    return {"reviewed_exceptions": exceptions, "blocking_findings": blockers}


def verify_audit_environment(report, packages):
    findings = classify_findings(report)
    dependencies = [item for item in report["dependencies"] if item["name"] != "paradigma-studio"]
    reported = {item["name"]: item.get("version") for item in dependencies}
    expected = {name: version for name, version in packages if name != "paradigma-studio"}
    if (
        not reported
        or len(reported) != len(dependencies)
        or reported != expected
        or findings["blocking_findings"]
        or any(report.get(key) != value for key, value in findings.items())
    ):
        raise ValueError("Dependency audit does not match the build environment or has blockers.")


def main(report_path):
    report_path = Path(report_path).resolve()
    with tempfile.TemporaryDirectory(prefix="paradigma-audit-") as directory:
        fresh_report = Path(directory) / "report.json"
        result = subprocess.run(
            [sys.executable, "-m", "pip_audit", "--format=json", "--output", str(fresh_report)],
            timeout=240,
        )
        if result.returncode not in (0, 1) or not fresh_report.exists():
            raise RuntimeError("Dependency audit did not complete; see pip-audit output.")
        report = json.loads(fresh_report.read_text(encoding="utf-8"))
    report.update(classify_findings(report))
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    blockers, exceptions = report["blocking_findings"], report["reviewed_exceptions"]
    if blockers:
        raise RuntimeError(f"Dependency audit has unresolved findings: {blockers}")
    print(
        f"No blocking findings; {len(exceptions)} advisory entries excluded with documented reasons."
    )


if __name__ == "__main__":
    main(sys.argv[1])
