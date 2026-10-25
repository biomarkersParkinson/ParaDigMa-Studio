"""Bind shipped package/source evidence to uv's native, platform-filtered graph."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_packages(root=ROOT, platform=None):
    command = [
        "uv",
        "tree",
        "--locked",
        "--all-groups",
        "--format",
        "json",
        "--python-version",
        (root / ".python-version").read_text().strip(),
    ]
    if platform:
        command.extend(["--python-platform", platform])
    result = subprocess.run(
        command,
        cwd=root,
        check=True,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "UV_PYTHON": sys.executable},
    )
    nodes = json.loads(result.stdout)["resolution"].values()
    packages = [node for node in nodes if node["kind"] == "package"]
    expected = {node["name"]: node for node in packages}
    if not expected or len(expected) != len(packages):
        raise ValueError("uv returned an empty or ambiguous package inventory.")
    return expected


def verify_package_evidence(packages, sources, expected):
    actual = {canonical(name): version for name, version in packages}
    if len(actual) != len(packages) or actual.keys() != expected.keys():
        raise ValueError("Release package inventory differs from uv.lock.")
    for name, package in expected.items():
        if actual[name] != package["version"]:
            raise ValueError(f"Release package version differs from uv.lock: {name}")
        git = package["source"].get("git")
        if git:
            url, _, commit = git.rpartition("#")
            recorded = sources.get(name, {})
            if recorded != {"url": url.split("?", 1)[0], "commit": commit}:
                raise ValueError(f"Release Git source differs from uv.lock: {name}")
