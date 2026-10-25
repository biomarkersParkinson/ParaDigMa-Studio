"""Release artifacts retain all runtime files and match the tagged, audited build."""

import json
import shutil
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


@pytest.fixture(autouse=True)
def native_graph(monkeypatch):
    # Artifact tests isolate release policy; uv's real graph is exercised by
    # dependency-evidence integration checks and the build workflow.
    def expected(root, platform):
        import tomllib

        version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
        return {
            "paradigma-studio": {"version": version, "source": {"editable": "."}},
            "paradigma": {"version": "1.1.2", "source": {"registry": "PyPI"}},
        }

    monkeypatch.setattr("scripts.prepare_release.locked_packages", expected)


def metadata_root(tmp_path, version=VERSION):
    root = tmp_path / "source"
    root.mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text(
        f'[build-system]\nrequires = ["setuptools>=77"]\nbuild-backend = "setuptools.build_meta"\n'
        f'[project]\nname = "paradigma-studio"\nversion = "{version}"\n'
        'requires-python = ">=3.11,<3.14"\ndependencies = ["paradigma==1.1.2"]\n'
        "[dependency-groups]\ndev = []\n"
        '[tool.uv]\nrequired-version = "==0.13.5"\n'
    )
    (root / "uv.lock").write_text("version = 1\n# Native lock evidence\n")
    (root / ".python-version").write_text("3.12.10\n")
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## {version} — 2026-10-13\n\nPreview notes.\n\n## 0.1.0 — 2025-01-01\n\nOld notes.\n",
        encoding="utf-8",
    )
    return root


def windows_bundle(tmp_path):
    root = metadata_root(tmp_path)
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
                "python": "3.12.10",
                "packages": [["paradigma-studio", VERSION], ["paradigma", "1.1.2"]],
                "dependency_lock": {
                    "lock_file": "uv.lock",
                    "lock_sha256": sha256(root / "uv.lock"),
                    "uv_version": "0.13.5",
                },
            }
        )
    )
    shutil.copyfile(root / "uv.lock", security / "uv.lock")
    (security / "dependency-audit.json").write_text(
        json.dumps(
            {
                "dependencies": [{"name": "paradigma", "version": "1.1.2", "vulns": []}],
                "blocking_findings": [],
                "reviewed_exceptions": [],
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
    "change",
    [
        "source",
        "version",
        "platform",
        "audit",
        "modified",
        "extra",
        "missing",
        "lock",
        "package-version",
        "audit-environment",
    ],
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
    elif change == "lock":
        (bundle / "security/uv.lock").write_text("changed")
        update_manifest(bundle)
    elif change == "package-version":
        path = bundle / "security/build-info.json"
        values = json.loads(path.read_text())
        values["packages"][1][1] = "1.1.3"
        path.write_text(json.dumps(values))
        update_manifest(bundle)
    elif change == "audit-environment":
        path = bundle / "security/dependency-audit.json"
        values = json.loads(path.read_text())
        values["dependencies"][0]["version"] = "1.1.3"
        path.write_text(json.dumps(values))
        update_manifest(bundle)
    elif change == "modified":
        (bundle / "LICENSE-studio.txt").write_text("changed")
    elif change == "extra":
        (bundle / "leftover.exe").write_bytes(b"MZunexpected")
    else:
        (bundle / "LICENSE-studio.txt").unlink()
    with pytest.raises(ValueError):
        prepare_assets("v" + VERSION, COMMIT, bundle, tmp_path / "assets", root)


@pytest.mark.parametrize("field", ["lock_sha256", "uv_version"])
def test_publication_rejects_wrong_lock_or_installer_identity(tmp_path, field):
    root = metadata_root(tmp_path)
    bundle = windows_bundle(tmp_path)
    path = bundle / "security/build-info.json"
    values = json.loads(path.read_text())
    values["dependency_lock"][field] = "0" * 64
    path.write_text(json.dumps(values))
    update_manifest(bundle)
    with pytest.raises(ValueError, match="dependency lock"):
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
