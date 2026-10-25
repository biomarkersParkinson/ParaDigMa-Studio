"""Dependency drift, stale audit evidence and mutable source pins fail closed."""

import copy
import json
import shutil
import tomllib
from pathlib import Path

import pytest
import yaml

from scripts.dependency_lock import (
    ROOT,
    WINDOWS_PYTHON,
    compare_packages,
    lock_metadata,
    read_lock,
    verify_audit_environment,
    verify_locks,
)
from scripts.sync_dependencies import sync_packages

HASH = "a" * 64
COMMIT = "b" * 40
URL = "https://github.com/example/reader.git"


@pytest.fixture
def source(tmp_path):
    shutil.copyfile(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copytree(ROOT / "requirements", tmp_path / "requirements")
    return tmp_path


@pytest.mark.parametrize(
    "requirement",
    [
        "numpy>=2",
        "numpy==2.5.4",
        "numpy==2.5.4 --hash=sha256:bad",
        f"reader @ git+{URL}@main",
        "-r another.txt",
        "--extra-index-url https://unreviewed.example/simple",
    ],
)
def test_unpinned_unhashed_and_external_requirements_are_rejected(tmp_path, requirement):
    path = tmp_path / "bad.lock"
    path.write_text(requirement + "\n")
    with pytest.raises(ValueError, match="Unpinned or unhashed"):
        read_lock(path)


def test_conflicting_duplicate_packages_are_rejected(tmp_path):
    path = tmp_path / "duplicate.lock"
    path.write_text(f"numpy==2.5.4 --hash=sha256:{HASH}\nnumpy==2.5.3 --hash=sha256:{HASH}\n")
    with pytest.raises(ValueError, match="Duplicate requirement"):
        read_lock(path)


def test_sync_requires_registry_hashes_and_installs_git_source_without_resolving_dependencies(
    tmp_path, monkeypatch
):
    from scripts import sync_dependencies

    path = tmp_path / "environment.lock"
    path.write_text(f"numpy==2.5.4 --hash=sha256:{HASH}\nreader @ git+{URL}@{COMMIT}\n")
    commands = []

    def capture(command, **kwargs):
        assert kwargs["check"] is True
        assert "--require-build-hashes" in command
        if "sync" in command:
            assert "--require-hashes" in command
            content = next(
                Path(arg).read_text() for arg in command if arg.endswith("registry.lock")
            )
            assert f"numpy==2.5.4 --hash=sha256:{HASH}" in content
            assert "reader" not in content
        else:
            assert "--no-deps" in command
            assert command[-1] == f"reader @ git+{URL}@{COMMIT}"
        commands.append(command)

    monkeypatch.setattr(sync_dependencies.subprocess, "run", capture)
    sync_packages(path)
    assert len(commands) == 2


@pytest.mark.parametrize("change", ["project", "input", "lock"])
def test_stale_inputs_and_modified_locks_cannot_be_used(source, change):
    verify_locks(source)
    if change == "project":
        path = source / "pyproject.toml"
        requirement = tomllib.loads(path.read_text())["project"]["dependencies"][0]
        path.write_text(path.read_text().replace(requirement, "unreviewed-package==1.0"))
    else:
        name = "tools.in" if change == "input" else "windows-py312.lock"
        path = source / "requirements" / name
        path.write_text(path.read_text() + "\n# Changed input\n")
    with pytest.raises(ValueError, match="inputs or locks changed"):
        verify_locks(source)


def test_version_only_release_bump_does_not_require_dependency_resolution(source):
    path = source / "pyproject.toml"
    version = tomllib.loads(path.read_text())["project"]["version"]
    path.write_text(path.read_text().replace(f'version = "{version}"', 'version = "99.0.0"'))
    verify_locks(source)


def test_native_input_line_endings_do_not_change_the_dependency_fingerprint(source):
    path = source / "requirements/tools.in"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    verify_locks(source)


def test_replacing_the_patched_git_reader_with_pypi_is_rejected_even_after_restamping(source):
    path = source / "requirements/windows-py312.lock"
    before = next(
        line for line in path.read_text().splitlines() if line.startswith("openmovement @")
    )
    path.write_text(path.read_text().replace(before, f"openmovement==0.0.1 --hash=sha256:{HASH}"))
    (source / "requirements/lock-metadata.json").write_text(json.dumps(lock_metadata(source)))
    with pytest.raises(ValueError, match="Git requirements"):
        verify_locks(source)


def packages():
    expected = {"numpy": {"version": "2.5.4"}, "reader": {"url": URL, "commit": COMMIT}}
    installed = [
        {"name": "numpy", "version": "2.5.4", "direct_url": {}},
        {
            "name": "reader",
            "version": "1.0",
            "direct_url": {
                "url": URL,
                "vcs_info": {"vcs": "git", "commit_id": COMMIT},
            },
        },
        {"name": "paradigma-studio", "version": "0.6.0a3", "direct_url": {}},
    ]
    return expected, installed


def test_environment_accepts_the_exact_registry_versions_and_reader_commit():
    expected, installed = packages()
    assert set(compare_packages(expected, installed, "paradigma-studio", "0.6.0a3")) == set(
        expected
    )


@pytest.mark.parametrize(
    "change", ["missing", "extra", "duplicate", "version", "commit", "repository", "studio"]
)
def test_environment_rejects_version_source_and_package_inventory_drift(change):
    expected, installed = packages()
    if change == "missing":
        installed.pop(0)
    elif change == "extra":
        installed.append({"name": "unreviewed", "version": "1.0", "direct_url": {}})
    elif change == "duplicate":
        installed.append(copy.deepcopy(installed[0]))
    elif change == "version":
        installed[0]["version"] = "2.5.3"
    elif change == "commit":
        installed[1]["direct_url"]["vcs_info"]["commit_id"] = "c" * 40
    elif change == "repository":
        installed[1]["direct_url"]["url"] = "https://github.com/other/reader.git"
    else:
        installed[2]["version"] = "0.6.0a2"
    with pytest.raises(ValueError):
        compare_packages(expected, installed, "paradigma-studio", "0.6.0a3")


@pytest.mark.parametrize("change", [None, "missing", "extra", "duplicate", "version", "blocker"])
def test_audit_must_cover_the_same_versions_and_all_packages(change):
    audit = {"dependencies": [{"name": "numpy", "version": "2.5.4"}], "blocking_findings": []}
    if change == "missing":
        audit["dependencies"].clear()
    elif change == "extra":
        audit["dependencies"].append({"name": "extra", "version": "1"})
    elif change == "duplicate":
        audit["dependencies"].append(copy.deepcopy(audit["dependencies"][0]))
    elif change == "version":
        audit["dependencies"][0]["version"] = "2.5.3"
    elif change == "blocker":
        audit["blocking_findings"].append({"id": "unreviewed"})
    if change is None:
        verify_audit_environment(audit, [("numpy", "2.5.4")])
    else:
        with pytest.raises(ValueError, match="audit does not match"):
            verify_audit_environment(audit, [("numpy", "2.5.4")])


@pytest.mark.parametrize("workflow", ["windows.yml", "windows-signed.yml"])
def test_windows_builds_verify_locked_environments_before_auditing_testing_and_packaging(workflow):
    steps = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"]["build"][
        "steps"
    ]
    commands = [step.get("run", "") for step in steps]
    indexes = [
        next(index for index, command in enumerate(commands) if value in command)
        for value in [
            "-m venv .venv",
            "scripts/sync_dependencies.py",
            "scripts/audit_dependencies.py",
            "python -m pytest --junitxml",
            "scripts/build_desktop.py",
            "scripts/write_build_manifest.py",
        ]
    ]
    assert indexes == sorted(indexes)
    setup = next(step for step in steps if step.get("uses", "").startswith("actions/setup-python@"))
    assert setup["with"]["python-version"] == WINDOWS_PYTHON
    reports = next(
        step
        for step in steps
        if step.get("with", {}).get("name") == "ParaDigMaStudio-dependency-reports"
    )
    assert reports["if"] == "always()"
    assert {"dependency-environment.json", "dependency-audit.json"} <= set(
        reports["with"]["path"].split()
    )
