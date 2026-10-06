"""Audit every installed distribution and retain a report for the artifact."""
import json
import subprocess
import sys
import tempfile
from importlib.metadata import distributions
from pathlib import Path


def is_python_arrow_exception(package, vulnerability):
    # CVE-2026-25087 requires a C++ IPC pre-buffering API that is not exposed
    # through Python. The advisory explicitly says Python bindings are unaffected.
    # ParaDigMa <23 pyarrow constraint prevents upgrading to the patched C++ wheel.
    identifiers = {vulnerability["id"], *vulnerability.get("aliases", [])}
    return package.lower() == "pyarrow" and "CVE-2026-25087" in identifiers


def main(report_path):
    report_path = Path(report_path).resolve()
    packages = sorted({
        (d.metadata["Name"], d.version) for d in distributions()
        if d.metadata["Name"].lower().replace("_", "-") != "paradigma-desktop"
    })
    with tempfile.TemporaryDirectory(prefix="paradigma-audit-") as directory:
        requirements = Path(directory) / "requirements.txt"
        fresh_report = Path(directory) / "report.json"
        requirements.write_text("".join(f"{name}=={version}\n" for name, version in packages), encoding="utf-8")
        result = subprocess.run([
            sys.executable, "-m", "pip_audit", "--no-deps", "--disable-pip",
            "-r", str(requirements), "--format=json", "--output", str(fresh_report),
        ], timeout=240)
        if result.returncode not in (0, 1) or not fresh_report.exists():
            raise RuntimeError("Dependency audit did not complete; see pip-audit output.")
        report = json.loads(fresh_report.read_text(encoding="utf-8"))
    dependencies = report.get("dependencies")
    if not dependencies:
        raise RuntimeError("Dependency audit returned no package results.")
    blockers = []
    exceptions = []
    for dependency in dependencies:
        if dependency.get("skip_reason"):
            blockers.append({"package": dependency["name"], "skip_reason": dependency["skip_reason"]})
        for vulnerability in dependency.get("vulns", []):
            finding = {"package": dependency["name"], "version": dependency["version"],
                       "id": vulnerability["id"]}
            if is_python_arrow_exception(dependency["name"], vulnerability):
                exceptions.append({**finding, "reason": "CVE-2026-25087 explicitly excludes Python bindings; see SECURITY.md."})
            else:
                blockers.append(finding)
    report["reviewed_exceptions"] = exceptions
    report["blocking_findings"] = blockers
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if blockers:
        raise RuntimeError(f"Dependency audit has unresolved findings: {blockers}")
    print(f"Audited {len(dependencies)} packages: no blocking findings; {len(exceptions)} advisory entries excluded with documented reasons.")


if __name__ == "__main__":
    main(sys.argv[1])
