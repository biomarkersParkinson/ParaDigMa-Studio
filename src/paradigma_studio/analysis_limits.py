"""Conservative process limits without importing the scientific stack at startup."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from .contracts import AnalysisSettings, SensorInput

if TYPE_CHECKING:
    import pandas as pd

GIB = 1024**3


def parallel_worker_count(
    frame: SensorInput, settings: AnalysisSettings, logger: logging.Logger | None = None
) -> int:
    """Use at most two workers, only across original recordings, with RAM headroom."""
    if not isinstance(frame, dict) or len(frame) < 2:
        return _worker_selection(
            logger, 1, "One original recording; its gap sections stay together."
        )
    from .core import validate_recordings

    try:
        validate_recordings(frame)
    except ValueError:
        return _worker_selection(
            logger, 1, "Recording identifiers or tables need sequential validation."
        )
    if any(
        other.startswith(key + "__segment_") for key in frame for other in frame if other != key
    ):
        # Preserve the sequential validator for ambiguous source/section names.
        return _worker_selection(
            logger, 1, "Recording identifiers overlap with section identifiers."
        )
    # Explicit mutable toolbox configurations can carry state between files in
    # the official orchestrator. Preserve that behavior through its single-worker
    # path. The desktop's ordinary scalar parameters remain parallel-compatible.
    if any(
        settings.get(name) is not None
        for name in (
            "imu_config",
            "ppg_config",
            "gait_config",
            "arm_activity_config",
            "tremor_config",
            "pulse_rate_config",
        )
    ):
        return _worker_selection(
            logger, 1, "Custom mutable toolbox configurations require sequential execution."
        )
    if settings.get("run_steps", "all") != "all":
        return _worker_selection(
            logger, 1, "Restricted pipeline steps require sequential execution."
        )
    return _resource_worker_count(frame, logger)


def _resource_worker_count(frames: dict[str, pd.DataFrame], logger: logging.Logger | None) -> int:
    cpus = _available_cpu_count()
    cpu_limit = max(1, cpus - 1)
    available = available_memory()
    if available is None:
        return _worker_selection(
            logger, 1, f"Available CPUs: {cpus}; available RAM could not be determined."
        )
    largest = max(int(recording.memory_usage(deep=True).sum()) for recording in frames.values())
    # Preparation, resampling and windowed features use substantially more RAM
    # than a source frame. Reserve space for Qt, retained inputs and other apps.
    per_worker = max(GIB, largest * 12)
    memory_limit = max(1, (available - GIB) // per_worker)
    workers = min(2, len(frames), cpu_limit, memory_limit)
    details = (
        f"Available CPUs: {cpus}; available RAM: {available / GIB:.2f} GiB; "
        f"largest loaded recording: {largest / GIB:.2f} GiB; "
        f"estimated RAM per worker: {per_worker / GIB:.2f} GiB; "
        "RAM reserve: 1.00 GiB."
    )
    limits = []
    if cpu_limit < 2:
        limits.append("CPU limit (one CPU is reserved for the interface)")
    if memory_limit < 2:
        limits.append(
            f"RAM limit (two workers need at least {(2 * per_worker + GIB) / GIB:.2f} GiB available)"
        )
    reason = (
        "Single-worker fallback: " + "; ".join(limits) if limits else "Two workers are available"
    )
    return _worker_selection(logger, workers, f"{details} {reason}.")


def _worker_selection(logger: logging.Logger | None, workers: int, reason: str) -> int:
    if logger is not None:
        logger.info(
            "Worker selection: %s %s. %s", workers, "worker" if workers == 1 else "workers", reason
        )
    return workers


def _available_cpu_count() -> int:
    cpus = os.cpu_count() or 1
    affinity = getattr(os, "sched_getaffinity", None)
    try:
        if affinity is not None:
            cpus = min(cpus, len(affinity(0)))
        if sys.platform == "linux":
            quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
            if quota != "max":
                cpus = min(cpus, max(1, int(quota) // int(period)))
    except (OSError, ValueError):
        pass
    return max(1, cpus)


def available_memory() -> int | None:
    """Available physical RAM, additionally respecting Linux container limits."""
    if sys.platform == "win32":
        return _windows_memory()
    try:
        available = int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
        root = Path("/sys/fs/cgroup")
        limit = (root / "memory.max").read_text().strip()
        if limit != "max":
            available = min(available, int(limit) - int((root / "memory.current").read_text()))
        return max(0, available)
    except (OSError, ValueError, AttributeError):
        return _physical_memory()


def _physical_memory() -> int | None:
    query = getattr(os, "sysconf", None)
    if query is None:
        return None
    try:
        return int(query("SC_AVPHYS_PAGES") * query("SC_PAGE_SIZE"))
    except (OSError, ValueError, AttributeError):
        return None


def _windows_memory() -> int | None:
    import ctypes
    from ctypes import wintypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.DWORD),
            ("load", wintypes.DWORD),
            *[
                (name, ctypes.c_ulonglong)
                for name in (
                    "total_physical",
                    "available_physical",
                    "total_page",
                    "available_page",
                    "total_virtual",
                    "available_virtual",
                    "extended_virtual",
                )
            ],
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    try:
        # The platform-specific foreign API is dynamically provided by ctypes.
        query = cast(Any, ctypes).windll.kernel32.GlobalMemoryStatusEx
        if query(ctypes.byref(status)):
            return int(status.available_physical)
    except (AttributeError, OSError):
        pass
    return None
