"""Analysis-time software identity, independent of later saves and exports."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from .branding import DISTRIBUTION_NAME
from .contracts import Provenance, RunRecord, SoftwareVersions
from .result_integrity import provenance_for_run


def _build_commit() -> str | None:
    """Use the bundled manifest or this checkout, never the user's working directory."""
    if getattr(sys, "frozen", False):
        manifest = Path(sys.executable).parent / "security" / "build-info.json"
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        commit = value.get("source_commit") if isinstance(value, dict) else None
    else:
        root = Path(__file__).resolve().parents[2]
        if not (root / ".git").exists():
            return None
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
                timeout=2,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    return commit if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit) else None


def software_versions() -> SoftwareVersions:
    identity: SoftwareVersions = {
        "studio_version": version(DISTRIBUTION_NAME),
        "paradigma_version": version("paradigma"),
    }
    commit = _build_commit()
    if commit is not None:
        identity["studio_build_commit"] = commit
    return identity


def recorded_software(record: RunRecord) -> SoftwareVersions:
    identity: SoftwareVersions = {
        "studio_version": record["studio_version"],
        "paradigma_version": record["paradigma_version"],
    }
    if "studio_build_commit" in record:
        identity["studio_build_commit"] = record["studio_build_commit"]
    return identity


def run_provenance(record: RunRecord) -> Provenance:
    return {
        "run_id": record["id"],
        "source": record["source"],
        "settings": record["settings"],
        **recorded_software(record),
        "sources": dict(record.get("sources", {})),
    }


def provenance_for_record(provenance: Provenance, record: RunRecord) -> Provenance:
    """Carry the owning run's software identity without concealing contradictions."""
    owned = provenance_for_run(provenance, record["id"])
    identity = recorded_software(record)
    for key in ("studio_version", "paradigma_version", "studio_build_commit"):
        if key in owned and owned[key] != identity.get(key):
            raise ValueError(f"Result provenance disagrees with its run's {key}.")
    return {**owned, **identity}
