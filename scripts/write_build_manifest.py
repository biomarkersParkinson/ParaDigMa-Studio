"""Record provenance and hashes without including credentials or user files."""
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from importlib.metadata import distributions
from pathlib import Path


def main(bundle, audit_report):
    bundle = Path(bundle).resolve()
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                            capture_output=True, text=True, check=True).stdout.strip()
    metadata = {
        "source_commit": commit,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": sorted({d.metadata["Name"]: d.version for d in distributions()}.items()),
        "notice": "Hashes detect changes; they are not a digital signature or a security guarantee.",
    }
    security = bundle / "security"
    security.mkdir(exist_ok=True)
    shutil.copyfile(audit_report, security / "dependency-audit.json")
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
