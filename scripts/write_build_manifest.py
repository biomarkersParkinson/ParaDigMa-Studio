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
    from .audit_dependencies import verify_audit_environment
    from .dependency_evidence import canonical
else:
    from audit_dependencies import verify_audit_environment
    from dependency_evidence import canonical


def main(bundle, audit_report):
    bundle = Path(bundle).resolve()
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["uv", "sync", "--locked", "--all-groups", "--check"], cwd=root, check=True)
    inventory = json.loads(
        subprocess.check_output(
            ["uv", "pip", "list", "--python", sys.executable, "--format", "json"], encoding="utf-8"
        )
    )
    packages = sorted((package["name"], package["version"]) for package in inventory)
    verify_audit_environment(json.loads(Path(audit_report).read_text(encoding="utf-8")), packages)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    metadata = {
        "source_commit": commit,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
        # Source builds can keep the same package version as an older PyPI
        # release. Record their commit, without copying URLs or local paths.
        "package_sources": {},
        "dependency_lock": {
            "lock_file": "uv.lock",
            "lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
            "uv_version": subprocess.check_output(["uv", "--version"], encoding="utf-8").split()[1],
        },
        "notice": "Hashes detect changes; they are not a digital signature or a security guarantee.",
    }
    for package in distributions():
        direct_url = package.read_text("direct_url.json")
        if direct_url:
            revision = json.loads(direct_url).get("vcs_info", {}).get("commit_id")
            if revision:
                metadata["package_sources"][canonical(package.metadata["Name"])] = {
                    "url": json.loads(direct_url)["url"],
                    "commit": revision,
                }
    security = bundle / "security"
    security.mkdir(exist_ok=True)
    shutil.copyfile(audit_report, security / "dependency-audit.json")
    shutil.copyfile(root / "uv.lock", security / "uv.lock")
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
