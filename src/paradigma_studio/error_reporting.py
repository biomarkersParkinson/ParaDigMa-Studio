"""Reconcile diagnostic messages with structured failures without changing logs."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .contracts import AnalysisError

_PIPELINES = frozenset({"gait", "tremor", "pulse_rate"})
_STEPS = frozenset({"preprocessing", "classification", "quantification", "aggregation"})
_STAGES = _STEPS | {"preparation", "pipeline_execution", "desktop_execution"}
_CONTEXTS = (
    (r"(?P<pipelines>gait|tremor|pulse_rate) pipeline returned error: ", "pipeline_execution"),
    (
        r"(?P<pipelines>gait|tremor|pulse_rate) pipeline failed on (?P<file>.+?): ",
        "pipeline_execution",
    ),
    (
        r"Failed to run (?P<pipelines>gait|tremor|pulse_rate) pipeline on (?P<file>.+?): ",
        "pipeline_execution",
    ),
    (r"Modules (?P<pipelines>[\w, ]+) failed: ", "desktop_execution"),
    (r"Failed to aggregate (?P<pipelines>gait|tremor|pulse_rate) results: ", "aggregation"),
)
_LOG_PREFIXES = tuple((re.compile(pattern, re.IGNORECASE), stage) for pattern, stage in _CONTEXTS)
_STEP_PREFIX = re.compile(
    r"^(?:Error in (?P<logged>preprocessing|classification|quantification|aggregation) step"
    r"|(?P<returned>Preprocessing|Classification|Quantification|Aggregation) failed):\s*",
    re.IGNORECASE,
)
_EXCEPTION_PREFIX = re.compile(r"^(?:[\w.]*(?:Error|Exception)|InsufficientRecordingData):\s*")
_RECORDING_SUFFIX = re.compile(r"(.+) \[([^\[\]\r\n]+)\]$", re.DOTALL)


@dataclass(frozen=True)
class _Entry:
    text: str
    body: str
    pipelines: frozenset[str] = frozenset()
    stage: str = ""
    file: str = ""
    structured: bool = False
    exception: str = ""

    @property
    def key(self) -> tuple[str, frozenset[str], str, str, str]:
        return self.body, self.pipelines, self.stage, self.file, self.exception


def error_text(error: AnalysisError) -> str:
    if isinstance(error, str):
        return error
    module = error.get("pipeline") or ", ".join(error.get("pipelines", []))
    context = " · ".join(
        str(value) for value in (module, error.get("stage"), error.get("file")) if value
    )
    return f"{context}: {error['error']}" if context else str(error["error"])


def _pipelines(value: str) -> frozenset[str]:
    return frozenset(part.strip().lower() for part in value.split(",") if part.strip())


def _normalise(body: str, stage: str) -> tuple[str, str, str]:
    body = body.strip()
    exception_name = ""
    while True:
        step = _STEP_PREFIX.match(body)
        exception = _EXCEPTION_PREFIX.match(body)
        if step:
            if stage in ("", "pipeline_execution"):
                stage = (step["logged"] or step["returned"]).lower()
            body = body[step.end() :].strip()
        elif exception:
            exception_name = exception_name or exception[0].partition(":")[0]
            body = body[exception.end() :].strip()
        elif body.startswith("Skipped recording: "):
            body = body.removeprefix("Skipped recording: ").strip()
            stage = stage or "preparation"
        else:
            return body, stage, exception_name


def _rendered_context(head: str) -> tuple[frozenset[str], str, str] | None:
    parts = head.split(" · ")
    pipelines = _pipelines(parts[0])
    if pipelines and pipelines <= _PIPELINES:
        parts.pop(0)
    else:
        pipelines = frozenset()
    stage = parts.pop(0) if parts and parts[0] in _STAGES else ""
    if (pipelines or stage) and len(parts) <= 1:
        return pipelines, stage, parts[0] if parts else ""
    return None


def _parse_text(text: str) -> _Entry:
    body, file = text, ""
    suffix = _RECORDING_SUFFIX.fullmatch(body)
    if suffix:
        body, file = suffix[1], suffix[2]
    head, separator, detail = body.partition(": ")
    rendered = _rendered_context(head) if separator else None
    if rendered is not None:
        pipelines, stage, section = rendered
        body, stage, exception = _normalise(detail, stage)
        return _Entry(text, body, pipelines, stage, section or file, True, exception)
    for prefix, stage in _LOG_PREFIXES:
        match = prefix.match(body)
        if match:
            context = match.groupdict()
            body, stage, exception = _normalise(body[match.end() :], stage)
            return _Entry(
                text,
                body,
                _pipelines(context["pipelines"]),
                stage,
                context.get("file") or file,
                exception=exception,
            )
    body, stage, exception = _normalise(body, "")
    return _Entry(text, body, stage=stage, file=file, exception=exception)


def _parse(error: AnalysisError) -> _Entry:
    if isinstance(error, str):
        return _parse_text(error)
    body, stage, exception = _normalise(str(error["error"]), str(error.get("stage") or ""))
    pipelines = error.get("pipeline") or ", ".join(error.get("pipelines", []))
    return _Entry(
        error_text(error),
        body,
        _pipelines(pipelines),
        stage,
        str(error.get("file") or ""),
        True,
        exception,
    )


def _covered(candidate: _Entry, detailed: _Entry) -> bool:
    if not candidate.body or candidate.body != detailed.body:
        return False
    if candidate.pipelines and candidate.pipelines != detailed.pipelines:
        return False
    if candidate.exception and candidate.exception != detailed.exception:
        return False
    if (
        candidate.file
        and candidate.file != detailed.file
        and not detailed.file.startswith(candidate.file + "__segment_")
    ):
        return False
    if candidate.stage and candidate.stage != detailed.stage:
        return candidate.stage == "pipeline_execution" and detailed.stage in _STEPS
    return True


def _append(entries: list[_Entry], candidate: _Entry) -> None:
    for index, existing in enumerate(entries):
        if candidate.text == existing.text or _covered(candidate, existing):
            return
        if not existing.structured and _covered(existing, candidate):
            entries[index] = candidate
            return
    entries.append(candidate)


def append_error(existing: Sequence[str], message: str) -> list[str]:
    """Reconcile one live error in linear time; keep its full text in the log."""
    entries = [_parse_text(text) for text in existing]
    _append(entries, _parse_text(message))
    return [entry.text for entry in entries]


def merge_errors(existing: Iterable[str], errors: Sequence[AnalysisError]) -> list[str]:
    """Prefer structured errors; suppress only diagnostics their context covers."""
    parsed = [_parse(error) for error in errors] + [_parse_text(text) for text in existing]
    # Rendered history entries carry the same context as newly returned dictionaries.
    preferred: dict[tuple[str, frozenset[str], str, str, str], _Entry] = {}
    for entry in parsed:
        if entry.structured:
            preferred.setdefault(entry.key, entry)
    entries = list(preferred.values())
    for entry in parsed:
        if not entry.structured:
            _append(entries, entry)
    return [entry.text for entry in entries]
