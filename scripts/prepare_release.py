"""Verify tagged Windows artifacts and prepare immutable GitHub release assets."""

import argparse
import hashlib
import json
import re
import shutil
import tomllib
import zipfile
from pathlib import Path

if __package__:
    from .audit_dependencies import verify_audit_environment
    from .dependency_evidence import locked_packages, verify_package_evidence
else:
    from audit_dependencies import verify_audit_environment
    from dependency_evidence import locked_packages, verify_package_evidence

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = r"\d+\.\d+\.\d+(?:(a|b|rc)\d+)?"


def release_version(tag, root=ROOT):
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    match = re.fullmatch(VERSION_PATTERN, version)
    if match is None or tag != "v" + version:
        raise ValueError("Release tag must match the project version exactly.")
    return version, match.group(1) is not None


def release_notes(version, root=ROOT):
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    sections = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    selected = [section for section in sections if section.split(" — ", 1)[0] == version]
    if len(selected) != 1:
        raise ValueError("Changelog must contain exactly one entry for the release version.")
    return selected[0].split("\n", 1)[1].strip() + "\n"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_bundle(bundle, version, source_commit, root=ROOT):
    bundle = Path(bundle).resolve()
    with (bundle / "ParaDigMaStudio.exe").open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("Release artifact is not a Windows executable.")
    if not (bundle / "_internal").is_dir():
        raise ValueError("Release artifact is missing its runtime folder.")
    info = json.loads((bundle / "security" / "build-info.json").read_text(encoding="utf-8"))
    if info.get("source_commit") != source_commit or not re.fullmatch(
        r"[0-9a-f]{40}", source_commit
    ):
        raise ValueError("Release artifact source commit differs from the tagged commit.")
    packages = {name.lower().replace("_", "-"): value for name, value in info.get("packages", [])}
    if packages.get("paradigma-studio") != version or not info.get("platform", "").startswith(
        "Windows"
    ):
        raise ValueError("Release artifact version or platform differs from the release.")
    audit = json.loads((bundle / "security" / "dependency-audit.json").read_text(encoding="utf-8"))
    if not audit.get("dependencies") or audit.get("blocking_findings") != []:
        raise ValueError("Release artifact lacks a passing dependency audit.")
    verify_dependency_evidence(bundle, info, audit, root)
    return verify_file_inventory(bundle)


def verify_dependency_evidence(bundle, info, audit, root):
    expected = locked_packages(root, "x86_64-pc-windows-msvc")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    evidence = info.get("dependency_lock", {})
    if (
        evidence.get("lock_file") != "uv.lock"
        or evidence.get("lock_sha256") != sha256(root / "uv.lock")
        or "==" + evidence.get("uv_version", "") != project["tool"]["uv"]["required-version"]
        or info.get("python") != (root / ".python-version").read_text().strip()
    ):
        raise ValueError("Release artifact does not match the tagged Windows dependency lock.")
    if sha256(bundle / "security/uv.lock") != sha256(root / "uv.lock"):
        raise ValueError("Release dependency evidence differs from source: uv.lock")
    verify_package_evidence(info["packages"], info.get("package_sources", {}), expected)
    verify_audit_environment(audit, info["packages"])


def verify_file_inventory(bundle):
    entries = sorted(bundle.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise ValueError("Release artifacts must not contain symlinks.")
    files = {path.relative_to(bundle).as_posix(): path for path in entries if path.is_file()}
    records = {}
    for line in files["SHA256SUMS.txt"].read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or name in records:
            raise ValueError("Release checksum inventory is malformed or duplicated.")
        records[name] = digest
    if set(records) != set(files) - {"SHA256SUMS.txt"}:
        raise ValueError("Release checksum inventory does not match the complete file set.")
    for name, digest in records.items():
        if sha256(files[name]) != digest:
            raise ValueError(f"Release artifact checksum mismatch: {name}")
    return entries


def write_archive(bundle, entries, destination):
    """Include hidden DLL directories with stable paths, timestamps and permissions."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in entries:
            name = "ParaDigMaStudio/" + path.relative_to(bundle).as_posix()
            info = zipfile.ZipInfo(name + "/" if path.is_dir() else name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o40755 << 16) | 0x10 if path.is_dir() else 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            if path.is_dir():
                archive.writestr(info, b"")
            else:
                with path.open("rb") as stream, archive.open(info, "w", force_zip64=True) as output:
                    shutil.copyfileobj(stream, output)


def prepare_assets(tag, source_commit, bundle, output_dir, root=ROOT):
    version, prerelease = release_version(tag, root)
    bundle = Path(bundle).resolve()
    entries = verify_bundle(bundle, version, source_commit, root)
    output_dir = Path(output_dir).resolve()
    if output_dir == bundle or bundle in output_dir.parents:
        raise ValueError("Release assets must be written outside the application bundle.")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"ParaDigMaStudio-{version}-Windows-x64.zip"
    write_archive(bundle, entries, archive)
    digest = sha256(archive)
    checksums = output_dir / f"ParaDigMaStudio-{version}-SHA256SUMS.txt"
    checksums.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    notes = output_dir / "release-notes.md"
    notes.write_text(release_notes(version, root), encoding="utf-8")
    plan = {
        "tag": tag,
        "source_commit": source_commit,
        "version": version,
        "prerelease": prerelease,
        "title": f"ParaDigMa Studio {version}" + (" (preview)" if prerelease else ""),
        "archive": str(archive),
        "archive_sha256": digest,
        "checksums": str(checksums),
        "notes": str(notes),
        "assets": [
            {"name": path.name, "size": path.stat().st_size, "sha256": sha256(path)}
            for path in (archive, checksums)
        ],
    }
    (output_dir / "release-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def verify_uploaded_release(plan, metadata, stage):
    """Verify the owned draft before replacement, then exact assets before/after publication."""
    if (
        metadata.get("tag_name") != plan["tag"]
        or metadata.get("target_commitish") != plan["source_commit"]
    ):
        raise ValueError("Existing release tag or source differs from this release.")
    if metadata.get("draft") != (stage != "published"):
        raise ValueError("Published releases cannot be overwritten; expected a matching draft.")
    if metadata.get("prerelease") != plan["prerelease"]:
        raise ValueError("Release preview status differs from the project version.")
    if stage == "draft":
        return
    assets = {asset["name"]: asset for asset in metadata.get("assets", [])}
    if set(assets) != {asset["name"] for asset in plan["assets"]}:
        raise ValueError("Uploaded release assets differ from the prepared inventory.")
    for expected in plan["assets"]:
        asset = assets[expected["name"]]
        if (asset.get("state"), asset.get("size"), asset.get("digest")) != (
            "uploaded",
            expected["size"],
            "sha256:" + expected["sha256"],
        ):
            raise ValueError(f"Uploaded release asset checksum or size differs: {expected['name']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    version = commands.add_parser("version")
    version.add_argument("--tag", required=True)
    prepare = commands.add_parser("prepare")
    for argument in ("tag", "source-commit", "bundle", "output-dir"):
        prepare.add_argument("--" + argument, required=True)
    prepare.add_argument("--github-output")
    verify = commands.add_parser("verify-upload")
    verify.add_argument("--plan", required=True)
    verify.add_argument("--metadata", required=True)
    verify.add_argument("--stage", choices=("draft", "assets", "published"), required=True)
    args = parser.parse_args()
    if args.command == "version":
        print(release_version(args.tag)[0])
    elif args.command == "verify-upload":
        verify_uploaded_release(
            json.loads(Path(args.plan).read_text(encoding="utf-8")),
            json.loads(Path(args.metadata).read_text(encoding="utf-8")),
            args.stage,
        )
    else:
        plan = prepare_assets(args.tag, args.source_commit, args.bundle, args.output_dir)
        if args.github_output:
            with Path(args.github_output).open("a", encoding="utf-8") as output:
                for key in ("archive", "checksums", "notes", "title", "archive_sha256"):
                    output.write(f"{key}={plan[key]}\n")
                output.write(f"prerelease={str(plan['prerelease']).lower()}\n")
        print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
