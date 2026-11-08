"""Per-recording read and conversion timings, local to each loading task."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from typing import Literal


@dataclass
class LoadTiming:
    read_decode_s: float = 0.0
    conversion_s: float = 0.0
    total_s: float = 0.0
    recording: str = ""


@dataclass
class _LoadScope:
    timing: LoadTiming
    errors: list[tuple[Callable[[], None], Callable[[], None] | None]]


_current: ContextVar[_LoadScope | None] = ContextVar("recording_load_timing", default=None)


def loading_recording() -> str:
    scope = _current.get()
    return scope.timing.recording if scope is not None else ""


def defer_loading_error(
    succeeded: Callable[[], None], failed: Callable[[], None] | None = None
) -> bool:
    """Resolve a reader's error log when its return/exception is known.

    Successful reads retain independent error reports. A thrown exception is
    the canonical failed-file report; its preceding log remains diagnostic text.
    Callbacks stay inside the task context, never inside serialized timings.
    """
    scope = _current.get()
    if scope is None:
        return False
    scope.errors.append((succeeded, failed))
    return True


@contextmanager
def measure_load(timing: LoadTiming) -> Iterator[None]:
    scope = _LoadScope(timing, [])
    token = _current.set(scope)
    started = perf_counter()
    succeeded = False
    try:
        yield
        succeeded = True
    finally:
        timing.total_s = perf_counter() - started
        _current.reset(token)
        for on_success, on_failure in scope.errors:
            callback = on_success if succeeded else on_failure
            if callback is not None:
                callback()


@contextmanager
def load_phase(name: Literal["read_decode", "conversion"]) -> Iterator[None]:
    scope = _current.get()
    if scope is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        elapsed = perf_counter() - started
        if name == "read_decode":
            scope.timing.read_decode_s += elapsed
        else:
            scope.timing.conversion_s += elapsed
