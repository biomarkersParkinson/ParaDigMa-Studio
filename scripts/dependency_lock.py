"""Read committed dependency locks and verify their installed environment."""

import hashlib
import json
import platform
import re
import sys
import tomllib
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    "requirements/bootstrap.in",
    "requirements/build.in",
    "requirements/tools.in",
    "requirements/scientific-constraints.txt",
)
LOCKS = (
    "requirements/bootstrap.lock",
    "requirements/build.lock",
    "requirements/windows-py312.lock",
    "requirements/linux-py312.lock",
)
COMPILER_VERSION = "0.13.5"
WINDOWS_PYTHON = "3.12.10"
TARGETS = (
    ("windows-py312.lock", "x86_64-pc-windows-msvc"),
    ("linux-py312.lock", "x86_64-manylinux_2_34"),
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def input_digest(root=ROOT):
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = {
        "build-system": project["build-system"],
        "requires-python": project["project"]["requires-python"],
        "dependencies": project["project"]["dependencies"],
        "dev": project["project"]["optional-dependencies"]["dev"],
        "inputs": {
            name: hashlib.sha256((root / name).read_text(encoding="utf-8").encode()).hexdigest()
            for name in INPUTS
        },
        "compiler": COMPILER_VERSION,
        "targets": TARGETS,
        "windows_python": WINDOWS_PYTHON,
    }
    return hashlib.sha256(json.dumps(requirements, sort_keys=True).encode()).hexdigest()


def read_lock(path):
    """Require exact registry versions/hashes or a full immutable Git commit."""
    entries = {}
    joined = Path(path).read_text(encoding="utf-8").replace("\\\n", " ")
    for line in joined.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        registry = re.fullmatch(
            r"([\w.-]+)==([\w.+!_-]+)((?:\s+--hash=sha256:[a-f0-9]{64})+)", line
        )
        vcs = re.fullmatch(r"([\w.-]+) @ git\+(https://[^\s@]+)@([a-f0-9]{40})", line)
        if registry:
            name, version, hashes = registry.groups()
            entry = {"version": version, "hashes": re.findall(r"sha256:([a-f0-9]{64})", hashes)}
        elif vcs:
            name, url, commit = vcs.groups()
            entry = {"url": url, "commit": commit}
        else:
            raise ValueError(f"Unpinned or unhashed requirement in {path}: {line}")
        name = canonical(name)
        if name in entries:
            raise ValueError(f"Duplicate requirement in {path}: {name}")
        entries[name] = entry
    if not entries:
        raise ValueError(f"Empty dependency lock: {path}")
    return entries


def lock_metadata(root=ROOT):
    return {
        "format_version": 1,
        "compiler": f"uv {COMPILER_VERSION}",
        "python": "3.12",
        "windows_python": WINDOWS_PYTHON,
        "targets": dict(TARGETS),
        "inputs_sha256": input_digest(root),
        "locks": {name: digest(root / name) for name in LOCKS},
    }


def verify_locks(root=ROOT):
    actual = json.loads((root / "requirements/lock-metadata.json").read_text())
    if actual != lock_metadata(root):
        raise ValueError(
            "Dependency inputs or locks changed; run python scripts/lock_dependencies.py."
        )
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    declared = {
        canonical(requirement.split(" @ ", 1)[0]): requirement.split(" @ ", 1)[1]
        for requirement in project["dependencies"]
        if " @ git+" in requirement
    }
    for name in LOCKS:
        entries = read_lock(root / name)
        sources = {
            key: f"git+{entry['url']}@{entry['commit']}"
            for key, entry in entries.items()
            if "commit" in entry
        }
        if sources != (declared if "py312" in name else {}):
            raise ValueError(f"Git requirements in {name} differ from the project declarations.")


def environment_lock(root=ROOT):
    if sys.version_info[:2] != (3, 12) or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("Locked environments require 64-bit CPython 3.12 on Windows or Linux.")
    names = {"win32": "windows-py312.lock", "linux": "linux-py312.lock"}
    if sys.platform not in names:
        raise ValueError("A dependency lock is available for Windows and Linux only.")
    return root / "requirements" / names[sys.platform]


def installed_packages():
    return [
        {
            "name": canonical(package.metadata["Name"]),
            "version": package.version,
            "direct_url": json.loads(package.read_text("direct_url.json") or "{}"),
        }
        for package in distributions()
    ]


def compare_packages(expected, installed, project_name, project_version):
    actual = {}
    project_versions = set()
    for package in installed:
        name = canonical(package["name"])
        if name == canonical(project_name):
            project_versions.add(package["version"])
            continue
        if name in actual:
            raise ValueError(f"Duplicate installed distribution: {name}")
        actual[name] = package
    if project_versions != {project_version}:
        raise ValueError(
            "Installed Studio metadata does not match the checkout; reinstall the project."
        )
    if actual.keys() != expected.keys():
        missing, extra = (
            sorted(expected.keys() - actual.keys()),
            sorted(actual.keys() - expected.keys()),
        )
        raise ValueError(
            f"Dependency environment differs from lock: missing={missing}, extra={extra}"
        )
    for name, requirement in expected.items():
        package = actual[name]
        if "version" in requirement:
            if package["version"] != requirement["version"]:
                raise ValueError(
                    f"{name}: expected {requirement['version']}, installed {package['version']}"
                )
        else:
            origin = package["direct_url"]
            if (
                origin.get("url") != requirement["url"]
                or origin.get("vcs_info", {}).get("vcs") != "git"
                or origin.get("vcs_info", {}).get("commit_id") != requirement["commit"]
            ):
                raise ValueError(f"{name}: installed Git source does not match the locked commit.")
    return actual


def verify_environment(root=ROOT):
    verify_locks(root)
    path = environment_lock(root)
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    packages = compare_packages(
        read_lock(path), installed_packages(), project["name"], project["version"]
    )
    return {
        "format_version": 1,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "lock_file": path.relative_to(root).as_posix(),
        "lock_sha256": digest(path),
        "inputs_sha256": input_digest(root),
        "packages": sorted((name, package["version"]) for name, package in packages.items()),
    }


def verify_audit_environment(audit, packages):
    dependencies = audit.get("dependencies", [])
    reported = {canonical(item["name"]): item.get("version") for item in dependencies}
    expected = {canonical(name): version for name, version in packages}
    if (
        not reported
        or len(reported) != len(dependencies)
        or reported != expected
        or audit.get("blocking_findings") != []
    ):
        raise ValueError(
            "Dependency audit does not match the verified environment or has blockers."
        )
