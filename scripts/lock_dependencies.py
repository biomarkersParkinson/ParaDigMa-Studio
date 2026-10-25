"""Regenerate reviewed Python 3.12 locks, retaining existing pins by default."""

import argparse
import json
import subprocess
import sys
from importlib.metadata import version

if __package__:
    from .dependency_lock import COMPILER_VERSION, ROOT, TARGETS, lock_metadata, read_lock
else:
    from dependency_lock import COMPILER_VERSION, ROOT, TARGETS, lock_metadata, read_lock


def compile_lock(inputs, output, *, platform=None, upgrades=(), constraints=(), build=False):
    command = [sys.executable, "-m", "uv", "pip", "compile", *inputs]
    command.extend(
        [
            "--python-version",
            "3.12",
            "--generate-hashes",
            "--no-annotate",
            "--custom-compile-command",
            "python scripts/lock_dependencies.py",
            "--output-file",
            output,
        ]
    )
    if platform:
        command.extend(["--extra", "dev", "--python-platform", platform])
    else:
        command.append("--universal")
    for name in constraints:
        command.extend(["--constraints", name])
    if build:
        command.extend(["--build-constraints", "requirements/build.lock", "--require-build-hashes"])
    for name in upgrades:
        command.extend(["--upgrade-package", name])
    subprocess.run(command, cwd=ROOT, check=True)
    read_lock(ROOT / output)


def main(upgrades=()):
    if version("uv") != COMPILER_VERSION:
        raise ValueError(f"Lock regeneration requires uv {COMPILER_VERSION}.")
    compile_lock(["requirements/bootstrap.in"], "requirements/bootstrap.lock", upgrades=upgrades)
    compile_lock(["requirements/build.in"], "requirements/build.lock", upgrades=upgrades)
    for name, platform in TARGETS:
        compile_lock(
            ["pyproject.toml", "requirements/tools.in"],
            f"requirements/{name}",
            platform=platform,
            upgrades=upgrades,
            constraints=["requirements/scientific-constraints.txt"],
            build=True,
        )
    (ROOT / "requirements/lock-metadata.json").write_text(
        json.dumps(lock_metadata(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upgrade-package", action="append", default=[])
    main(parser.parse_args().upgrade_package)
