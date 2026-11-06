"""Loading-created history entries and immutable import context for later attempts."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from typing import Any

from .contracts import AnalysisSettings, LoadingInfo, RunRecord
from .provenance import recorded_software, software_versions


def new_loading_run(selections: list[str]) -> RunRecord:
    from .history import new_run

    record = new_run(selections[0], {})
    record["status"] = "Loading"
    record["loading"] = {
        "id": record["id"],
        "started": record["started"],
        "finished": None,
        "selections": list(selections),
        "software": recorded_software(record),
        "log": "",
        "warnings": [],
        "errors": [],
    }
    record["log"] = "Loading recordings\n" + "\n".join(selections) + "\n"
    return record


def close_loading(record: RunRecord, finished: str) -> None:
    loading = record["loading"]
    loading["finished"] = finished
    loading["log"] = record["log"]
    loading["warnings"] = list(record["warnings"])
    loading["errors"] = list(record["errors"])


def analysis_record(
    pending: RunRecord | None,
    source: str,
    settings: AnalysisSettings,
    loading: LoadingInfo | None,
) -> RunRecord:
    from .history import new_run, now

    if pending is not None and pending["status"] == "Loaded":
        record = pending
        record.pop("studio_build_commit", None)
        record.update(software_versions())
    else:
        record = new_run(source, settings)
        if loading is not None:
            record["loading"] = deepcopy(loading)
            record["log"] = loading["log"]
            record["warnings"] = list(loading["warnings"])
            record["errors"] = list(loading["errors"])
    record["source"], record["settings"] = source, settings
    record["status"], record["finished"] = "Running", None
    record["analysis_started"] = now()
    if "loading" in record:
        record["log"] += "\nAnalysis\n"
    return record


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Invalid loading or analysis timestamp.")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Loading and analysis timestamps require a timezone.")
    return stamp


def validate_lifecycle(record: dict[str, Any]) -> bool:
    """Return whether settings are pending; completed analyses retain strict validation."""
    loading = record.get("loading")
    analysis_started = record.get("analysis_started")
    if "analysis_started" in record:
        _timestamp(analysis_started)
    if loading is None:
        if "loading" in record:
            raise ValueError("Invalid loading context.")
        if record["status"] in ("Loading", "Loaded"):
            raise ValueError("Loading history requires import context.")
        return False
    _validate_loading(loading)
    if analysis_started is not None:
        if loading["finished"] is None or _timestamp(analysis_started) < _timestamp(
            loading["finished"]
        ):
            raise ValueError("Analysis cannot precede loading completion.")
        if record["status"] in ("Loading", "Loaded"):
            raise ValueError("Analysis has started in a loading-only entry.")
        return False
    _validate_pending(record, loading)
    return True


def _validate_pending(record: dict[str, Any], loading: dict[str, Any]) -> None:
    if record["status"] not in ("Loading", "Loaded", "Failed", "Cancelled", "Unfinished"):
        raise ValueError("A loading-only entry cannot contain an analysis outcome.")
    if record["settings"] or record["outputs"]:
        raise ValueError("Loading-only entries cannot contain analysis settings or outputs.")
    if record["status"] == "Loading" and (
        loading["finished"] is not None or record["finished"] is not None
    ):
        raise ValueError("An active load cannot be finished.")
    if record["status"] == "Loaded" and (
        loading["finished"] is None or record["finished"] is not None
    ):
        raise ValueError("A loaded entry requires import completion without an analysis outcome.")
    if record["status"] in ("Failed", "Cancelled") and (
        loading["finished"] is None or record["finished"] is None
    ):
        raise ValueError("A terminal loading entry requires completion times.")


def _validate_loading(loading: object) -> None:
    if (
        not isinstance(loading, dict)
        or not isinstance(loading.get("id"), str)
        or not re.fullmatch(r"[0-9a-f]{32}", loading["id"])
    ):
        raise ValueError("Invalid loading context.")
    started = _timestamp(loading.get("started"))
    if "finished" not in loading:
        raise ValueError("Missing loading completion time.")
    if loading["finished"] is not None and _timestamp(loading["finished"]) < started:
        raise ValueError("Loading completion precedes its start.")
    selections = loading.get("selections")
    if (
        not isinstance(selections, list)
        or not selections
        or not all(isinstance(path, str) and path for path in selections)
    ):
        raise ValueError("Invalid loading selections.")
    if not isinstance(loading.get("log"), str) or not all(
        isinstance(loading.get(name), list)
        and all(isinstance(value, str) for value in loading[name])
        for name in ("warnings", "errors")
    ):
        raise ValueError("Invalid loading diagnostics.")
    software = loading.get("software")
    if not isinstance(software, dict) or not all(
        isinstance(software.get(name), str) and software[name]
        for name in ("studio_version", "paradigma_version")
    ):
        raise ValueError("Invalid loading software identity.")
    if "studio_build_commit" in software and (
        not isinstance(software["studio_build_commit"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", software["studio_build_commit"])
    ):
        raise ValueError("Invalid loading build commit.")
