"""Conservative process limits without importing the scientific stack at startup."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, cast

from .contracts import AnalysisSettings, SensorInput

GIB = 1024**3


def parallel_worker_count(frame: SensorInput, settings: AnalysisSettings) -> int:
    """Use at most two workers, only across original recordings, with RAM headroom."""
    if not isinstance(frame, dict) or len(frame) < 2:
        return 1
    from .core import validate_recordings

    try:
        validate_recordings(frame)
    except ValueError:
        return 1
    if any(
        other.startswith(key + "__segment_") for key in frame for other in frame if other != key
    ):
        # Preserve the sequential validator for ambiguous source/section names.
        return 1
    # Explicit mutable toolbox configurations can carry state between files in
    # the official orchestrator. Preserve that behavior through its single-worker
    # path. The desktop's ordinary scalar parameters remain parallel-compatible.
    if (
        any(
            settings.get(name) is not None
            for name in (
                "imu_config",
                "ppg_config",
                "gait_config",
                "arm_activity_config",
                "tremor_config",
                "pulse_rate_config",
            )
        )
        or settings.get("run_steps", "all") != "all"
    ):
        return 1
    cpu_limit = max(1, _available_cpu_count() - 1)
    available = available_memory()
    if available is None:
        return 1
    largest = max(int(recording.memory_usage(deep=True).sum()) for recording in frame.values())
    # Preparation, resampling and windowed features use substantially more RAM
    # than a source frame. Reserve space for Qt, retained inputs and other apps.
    per_worker = max(GIB, largest * 12)
    memory_limit = max(1, (available - GIB) // per_worker)
    return min(2, len(frame), cpu_limit, memory_limit)


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
