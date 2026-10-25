"""Native uv gates and the application-owned release/audit policy."""

import copy
import shutil
import subprocess
import sys
import tomllib

import pytest
import yaml

from scripts.audit_dependencies import classify_findings, verify_audit_environment
from scripts.dependency_evidence import ROOT, locked_packages, verify_package_evidence


@pytest.mark.parametrize("platform", ["x86_64-pc-windows-msvc", "x86_64-manylinux_2_34"])
def test_native_graph_retains_declared_scientific_and_git_policy(platform):
    expected = locked_packages(ROOT, platform)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    for pin in project["tool"]["uv"]["constraint-dependencies"]:
        name, version = pin.split("==")
        assert expected[name]["version"] == version
    reader = next(
        dep for dep in project["project"]["dependencies"] if dep.startswith("openmovement @")
    )
    url, commit = reader.split(" @ git+", 1)[1].rsplit("@", 1)
    assert expected["openmovement"]["source"]["git"] == f"{url}?rev={commit}#{commit}"


@pytest.mark.parametrize("change", ["dependency", "git-source"])
def test_native_freshness_gate_rejects_unreviewed_changes_without_rewriting_lock(tmp_path, change):
    for name in ("pyproject.toml", "uv.lock", ".python-version"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    command = ["uv", "lock", "--check", "--offline", "--python", sys.executable]
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True, encoding="utf-8")
    project = tmp_path / "pyproject.toml"
    text = project.read_text()
    if change == "dependency":
        text = text.replace('"paradigma==1.1.2"', '"paradigma==99.0.0"')
    else:
        reader = next(line for line in text.splitlines() if "openmovement @" in line)
        text = text.replace(reader, '    "openmovement==0.0.1",')
    project.write_text(text)
    before = (tmp_path / "uv.lock").read_bytes()
    result = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode != 0
    assert (tmp_path / "uv.lock").read_bytes() == before


@pytest.mark.parametrize(
    "change", [None, "missing", "extra", "duplicate", "version", "commit", "url"]
)
def test_release_evidence_must_match_native_versions_and_sources(change):
    commit, url = "b" * 40, "https://github.com/example/reader.git"
    expected = {
        "numpy": {"version": "2.5.4", "source": {"registry": "PyPI"}},
        "reader": {"version": "1.0", "source": {"git": f"{url}?rev={commit}#{commit}"}},
    }
    packages = [["numpy", "2.5.4"], ["reader", "1.0"]]
    sources = {"reader": {"url": url, "commit": commit}}
    if change == "missing":
        packages.pop()
    elif change == "extra":
        packages.append(["unexpected", "1.0"])
    elif change == "duplicate":
        packages.append(packages[0].copy())
    elif change == "version":
        packages[0][1] = "2.5.3"
    elif change in ("commit", "url"):
        sources["reader"][change] = "wrong"
    if change is None:
        verify_package_evidence(packages, sources, expected)
    else:
        with pytest.raises(ValueError):
            verify_package_evidence(packages, sources, expected)


@pytest.mark.parametrize(
    "change", [None, "missing", "extra", "duplicate", "version", "skipped", "hidden-finding"]
)
def test_audit_covers_the_build_and_cannot_hide_raw_findings(change):
    report = {
        "dependencies": [
            {"name": "numpy", "version": "2.5.4", "vulns": []},
            {"name": "paradigma-studio", "skip_reason": "First-party checkout"},
        ],
        "blocking_findings": [],
        "reviewed_exceptions": [],
    }
    if change == "missing":
        report["dependencies"].pop(0)
    elif change == "extra":
        report["dependencies"].append({"name": "extra", "version": "1", "vulns": []})
    elif change == "duplicate":
        report["dependencies"].append(copy.deepcopy(report["dependencies"][0]))
    elif change == "version":
        report["dependencies"][0]["version"] = "2.5.3"
    elif change == "skipped":
        report["dependencies"][0] = {"name": "numpy", "skip_reason": "Unknown"}
    elif change == "hidden-finding":
        report["dependencies"][0]["vulns"] = [{"id": "CVE-unreviewed"}]
    if change is None:
        verify_audit_environment(report, [("numpy", "2.5.4"), ("paradigma-studio", "0.6.0a3")])
    else:
        with pytest.raises(ValueError):
            verify_audit_environment(report, [("numpy", "2.5.4")])


def test_reviewed_exception_retains_raw_advisory_and_is_package_specific():
    vulnerability = {"id": "PYSEC-2026-113", "aliases": ["CVE-2026-25087"]}
    report = {"dependencies": [{"name": "pyarrow", "version": "22.0.0", "vulns": [vulnerability]}]}
    findings = classify_findings(report)
    assert not findings["blocking_findings"] and findings["reviewed_exceptions"]
    assert report["dependencies"][0]["vulns"] == [vulnerability]
    report["dependencies"][0]["name"] = "other-package"
    assert classify_findings(report)["blocking_findings"]


@pytest.mark.parametrize("workflow", ["windows.yml", "windows-signed.yml"])
def test_ci_uses_native_uv_gates_before_audit_and_packaging(workflow):
    steps = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"]["build"][
        "steps"
    ]
    commands = [step.get("run", "") for step in steps]
    gates = [
        "uv lock --check",
        "uv sync --locked --all-groups --check",
        "scripts/audit_dependencies.py",
        "python -m pytest --junitxml",
        "scripts/write_build_manifest.py",
    ]
    indexes = [next(i for i, command in enumerate(commands) if gate in command) for gate in gates]
    assert indexes == sorted(indexes)
    assert not any("sync_dependencies.py" in command for command in commands)
    setup = next(step for step in steps if step.get("uses", "").startswith("astral-sh/setup-uv@"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "==" + setup["with"]["version"] == project["tool"]["uv"]["required-version"]
