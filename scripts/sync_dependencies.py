"""Install the reviewed lock into an explicit, isolated build/development venv."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__:
    from .dependency_lock import ROOT, environment_lock, read_lock, verify_environment, verify_locks
else:
    from dependency_lock import ROOT, environment_lock, read_lock, verify_environment, verify_locks


def sync_packages(path):
    entries = read_lock(path)
    command = [sys.executable, "-m", "uv", "pip"]
    build = ["--build-constraints", str(ROOT / "requirements/build.lock"), "--require-build-hashes"]
    with tempfile.TemporaryDirectory(prefix="studio-dependencies-") as directory:
        registry = Path(directory) / "registry.lock"
        registry.write_text(
            "".join(
                f"{name}=={entry['version']} "
                + " ".join(f"--hash=sha256:{value}" for value in entry["hashes"])
                + "\n"
                for name, entry in entries.items()
                if "version" in entry
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [
                *command,
                "sync",
                "--python",
                sys.executable,
                "--require-hashes",
                *build,
                str(registry),
                "--strict",
            ],
            cwd=ROOT,
            check=True,
        )
    for name, entry in entries.items():
        if "commit" in entry:
            # Git content is bound to its full immutable commit, not a wheel hash.
            subprocess.run(
                [
                    *command,
                    "install",
                    "--python",
                    sys.executable,
                    "--no-deps",
                    *build,
                    f"{name} @ git+{entry['url']}@{entry['commit']}",
                ],
                cwd=ROOT,
                check=True,
            )


def main(*, check=False, report=None):
    verify_locks()
    path = environment_lock()
    if not check:
        if sys.prefix == sys.base_prefix:
            raise ValueError("Create a virtual environment before syncing dependencies.")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--only-binary=:all:",
                "--require-hashes",
                "--no-deps",
                "-r",
                str(ROOT / "requirements/bootstrap.lock"),
            ],
            check=True,
        )
        sync_packages(path)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--no-deps",
                "--no-build-isolation",
                "-e",
                str(ROOT),
            ],
            check=True,
        )
    verified = verify_environment()
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    if report:
        report.write_text(json.dumps(verified, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(verified['packages'])} locked packages: {verified['lock_file']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Verify without installing or removing packages."
    )
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    main(check=arguments.check, report=arguments.report)
