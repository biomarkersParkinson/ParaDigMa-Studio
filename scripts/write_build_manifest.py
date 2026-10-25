"""Record provenance and hashes without including credentials or user files."""

import hashlib
import json
import platform
import shutil
import subprocess
import sys
from importlib.metadata import distributions
from pathlib import Path

if __package__:
    from .dependency_lock import verify_audit_environment, verify_environment
else:
    from dependency_lock import verify_audit_environment, verify_environment


def main(bundle, audit_report):
    bundle = Path(bundle).resolve()
    root = Path(__file__).resolve().parents[1]
    environment = verify_environment(root)
    verify_audit_environment(
        json.loads(Path(audit_report).read_text(encoding="utf-8")), environment["packages"]
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    metadata = {
        "source_commit": commit,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": sorted({d.metadata["Name"]: d.version for d in distributions()}.items()),
        # Source builds can keep the same package version as an older PyPI
        # release. Record their commit, without copying URLs or local paths.
        "package_vcs_revisions": {},
        "dependency_lock": {key: value for key, value in environment.items() if key != "packages"},
        "notice": "Hashes detect changes; they are not a digital signature or a security guarantee.",
    }
    for package in distributions():
        direct_url = package.read_text("direct_url.json")
        if direct_url:
            revision = json.loads(direct_url).get("vcs_info", {}).get("commit_id")
            if revision:
                metadata["package_vcs_revisions"][package.metadata["Name"]] = revision
    security = bundle / "security"
    security.mkdir(exist_ok=True)
    shutil.copyfile(audit_report, security / "dependency-audit.json")
    shutil.copyfile(root / environment["lock_file"], security / "dependencies.lock")
    shutil.copyfile(root / "requirements/build.lock", security / "build-dependencies.lock")
    shutil.copyfile(root / "requirements/lock-metadata.json", security / "dependency-lock.json")
    (security / "build-info.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    lines = []
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            lines.append(f"{digest}  {path.relative_to(bundle).as_posix()}\n")
    (bundle / "SHA256SUMS.txt").write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
