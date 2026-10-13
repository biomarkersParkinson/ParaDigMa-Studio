"""Release artifacts retain all runtime files and match the tagged, audited build."""

import json
import zipfile
from pathlib import Path

import pytest

from scripts.prepare_release import (
    prepare_assets,
    release_notes,
    release_version,
    sha256,
    verify_uploaded_release,
)

COMMIT = "a" * 40
VERSION = "0.6.0a1"


def metadata_root(tmp_path, version=VERSION):
    root = tmp_path / "source"
    root.mkdir()
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## {version} — 2026-10-13\n\nPreview notes.\n\n## 0.1.0 — 2025-01-01\n\nOld notes.\n",
        encoding="utf-8",
    )
    return root


def windows_bundle(tmp_path):
    bundle = tmp_path / "bundle"
    libraries = bundle / "_internal" / "sklearn" / ".libs"
    libraries.mkdir(parents=True)
    (bundle / "ParaDigMaStudio.exe").write_bytes(b"MZexecutable")
    (libraries / "vcomp140.dll").write_bytes(b"MZruntime")
    (bundle / "LICENSE-studio.txt").write_text("licence")
    security = bundle / "security"
    security.mkdir()
    (security / "build-info.json").write_text(
        json.dumps(
            {
                "source_commit": COMMIT,
                "platform": "Windows-10",
                "packages": [["paradigma-studio", VERSION]],
            }
        )
    )
    (security / "dependency-audit.json").write_text(
        json.dumps(
            {
                "dependencies": [{"name": "paradigma", "version": "1.1.2", "vulns": []}],
                "blocking_findings": [],
            }
        )
    )
    update_manifest(bundle)
    return bundle


def update_manifest(bundle):
    files = sorted(
        path for path in bundle.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (bundle / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(bundle).as_posix()}\n" for path in files)
    )


@pytest.mark.parametrize(
    "version, preview", [(VERSION, True), ("0.6.0rc1", True), ("0.6.0", False)]
)
def test_version_tag_and_prerelease_status_match_project_metadata(tmp_path, version, preview):
    root = metadata_root(tmp_path, version)
    assert release_version("v" + version, root) == (version, preview)
    assert release_notes(version, root) == "Preview notes.\n"
    with pytest.raises(ValueError, match="match the project version"):
        release_version("v0.9.0", root)


def test_release_zip_contains_complete_bundle_hidden_libraries_and_independent_checksums(tmp_path):
    root = metadata_root(tmp_path)
    bundle = windows_bundle(tmp_path)
    before = {
        path.relative_to(bundle): path.read_bytes() for path in bundle.rglob("*") if path.is_file()
    }
    plan = prepare_assets("v" + VERSION, COMMIT, bundle, tmp_path / "assets", root)
    assert plan["prerelease"] is True and "preview" in plan["title"]
    with zipfile.ZipFile(plan["archive"]) as archive:
        assert {name for name in archive.namelist() if not name.endswith("/")} == {
            "ParaDigMaStudio/" + path.as_posix() for path in before
        }
        for path, contents in before.items():
            assert archive.read("ParaDigMaStudio/" + path.as_posix()) == contents
    checksums = Path(plan["checksums"]).read_text().strip().split("  ")
    assert checksums == [sha256(plan["archive"]), Path(plan["archive"]).name]
    again = prepare_assets("v" + VERSION, COMMIT, bundle, tmp_path / "again", root)
    assert again["archive_sha256"] == plan["archive_sha256"]
    assert before == {
        path.relative_to(bundle): path.read_bytes() for path in bundle.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize(
    "change", ["source", "version", "platform", "audit", "modified", "extra", "missing"]
)
def test_publication_rejects_wrong_or_modified_build_artifacts(tmp_path, change):
    root = metadata_root(tmp_path)
    bundle = windows_bundle(tmp_path)
    if change in ("source", "version", "platform"):
        path = bundle / "security" / "build-info.json"
        info = json.loads(path.read_text())
        if change == "source":
            info["source_commit"] = "b" * 40
        elif change == "version":
            info["packages"][0][1] = "0.5.32"
        else:
            info["platform"] = "Linux"
        path.write_text(json.dumps(info))
        update_manifest(bundle)
    elif change == "audit":
        (bundle / "security" / "dependency-audit.json").write_text(
            '{"dependencies": [], "blocking_findings": []}'
        )
        update_manifest(bundle)
    elif change == "modified":
        (bundle / "LICENSE-studio.txt").write_text("changed")
    elif change == "extra":
        (bundle / "leftover.exe").write_bytes(b"MZunexpected")
    else:
        (bundle / "LICENSE-studio.txt").unlink()
    with pytest.raises(ValueError):
        prepare_assets("v" + VERSION, COMMIT, bundle, tmp_path / "assets", root)


@pytest.mark.parametrize(
    "change", [None, "digest", "size", "source", "preview", "published", "extra"]
)
def test_uploaded_assets_are_verified_before_publishing_or_replacing_a_draft(tmp_path, change):
    plan = prepare_assets(
        "v" + VERSION,
        COMMIT,
        windows_bundle(tmp_path),
        tmp_path / "assets",
        metadata_root(tmp_path),
    )
    response = {
        "tag_name": plan["tag"],
        "target_commitish": COMMIT,
        "draft": True,
        "prerelease": True,
        "assets": [
            {
                "name": asset["name"],
                "size": asset["size"],
                "digest": "sha256:" + asset["sha256"],
                "state": "uploaded",
            }
            for asset in plan["assets"]
        ],
    }
    if change is None:
        verify_uploaded_release(plan, response, "draft")
        verify_uploaded_release(plan, response, "assets")
        response["draft"] = False
        verify_uploaded_release(plan, response, "published")
        return
    if change == "digest":
        response["assets"][0]["digest"] = "sha256:" + "b" * 64
    elif change == "size":
        response["assets"][0]["size"] += 1
    elif change == "source":
        response["target_commitish"] = "b" * 40
    elif change == "preview":
        response["prerelease"] = False
    elif change == "published":
        response["draft"] = False
    else:
        response["assets"].append({"name": "unexpected.exe"})
    with pytest.raises(ValueError):
        verify_uploaded_release(plan, response, "assets")
