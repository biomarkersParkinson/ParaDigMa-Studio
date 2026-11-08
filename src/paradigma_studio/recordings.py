"""Independent recordings sharing one subject and one analysis configuration."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np

from .analysis_progress import ProgressCallback
from .contracts import (
    AnalysisResults,
    AnalysisSettings,
    ClockMetadata,
    FloatArray,
    PathInput,
    RecordingAlignment,
    TimeOffsets,
)
from .core import SUPPORTED, load_sensor_file
from .recording_loading import LoadingBatch, LoadMode, load_parallel, loading_plan, read_recording
from .results_view import analysis_alignment, normalise_clock, recording_clock

if TYPE_CHECKING:
    import pandas as pd

SENSOR_FILE_PATTERNS = tuple(
    "*_meta.json" if suffix == ".json" else f"*{suffix}" for suffix in sorted(SUPPORTED)
)


def find_sensor_files(folder: PathInput, *, logger: logging.Logger | None = None) -> list[Path]:
    """Find recordings recursively without treating saved-result JSON as input."""
    if not Path(folder).is_dir():
        raise ValueError("Select a folder containing sensor recordings.")
    return find_recording_files([folder], logger=logger)


def find_recording_files(
    selections: Iterable[PathInput], *, logger: logging.Logger | None = None
) -> list[Path]:
    """Expand mixed selections once, preserving all-or-nothing discovery failures."""
    discovered: dict[Path, Path] = {}
    visited: set[Path] = set()
    for item in sorted(
        map(Path, selections), key=lambda path: (path.as_posix().casefold(), path.as_posix())
    ):
        if item.is_dir():
            candidates = _scan_sensor_folder(item, visited)
        elif item.is_file() and _sensor_file(item):
            candidates = [item]
        else:
            raise ValueError(f"Recording file or folder unavailable or unsupported: {item}")
        for path in candidates:
            discovered.setdefault(path.resolve(), path)
    paths = sorted(
        discovered.values(), key=lambda path: (path.as_posix().casefold(), path.as_posix())
    )
    if not paths:
        raise ValueError("No supported sensor recordings found in the selected files or folders.")
    if logger is not None:
        logger.info("Found %s sensor recordings in the selected files and folders.", len(paths))
    return paths


def _scan_sensor_folder(root: Path, visited: set[Path]) -> list[Path]:
    if not root.is_dir():
        raise ValueError("Select a folder containing sensor recordings.")
    paths = []
    for directory, subfolders, names in os.walk(root, followlinks=False, onerror=_discovery_error):
        current = Path(directory)
        resolved = current.resolve()
        if resolved in visited:
            subfolders.clear()
            continue
        visited.add(resolved)
        subfolders[:] = sorted(name for name in subfolders if not _linked_folder(current / name))
        for name in sorted(names):
            path = current / name
            if _sensor_file(path) and path.is_file():
                paths.append(path)
    return paths


def _sensor_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    return suffix in SUPPORTED and (suffix != ".json" or path.name.lower().endswith("_meta.json"))


def _linked_folder(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _discovery_error(error: OSError) -> None:
    raise error


def load_recordings(
    paths: Iterable[PathInput],
    *,
    allow_pickle: bool = False,
    logger: logging.Logger | None = None,
    progress: ProgressCallback | None = None,
    mode: LoadMode = "auto",
    max_workers: int = 2,
) -> tuple[dict[str, str], dict[str, pd.DataFrame]]:
    """Stage a complete batch, preserving input order through bounded readers.

    The first file supplies a real decoded-memory/work estimate without an extra
    read. Explicit modes support reproducible benchmarks and troubleshooting.
    """
    # Validate options before opening a source, including empty/single batches.
    loading_plan([], 0, 0.0, mode=mode, max_workers=max_workers)
    selected_paths = list(dict.fromkeys(map(str, paths)))
    if not selected_paths:
        raise ValueError("Select at least one sensor recording.")
    blocked_pickle = next(
        (Path(path) for path in selected_paths if Path(path).suffix.lower() in {".pkl", ".pickle"}),
        None,
    )
    if not allow_pickle and blocked_pickle is not None:
        raise ValueError(
            f"{blocked_pickle.name}: Pickle loading is disabled unless the file is explicitly trusted."
        )
    batch = LoadingBatch(selected_paths, logger, progress)
    try:
        batch.begin(0)
        first, timing = read_recording(load_sensor_file, selected_paths[0], allow_pickle)
        batch.completed(0, first, timing)
        sample_bytes = int(first.memory_usage(deep=True).sum())
        plan = loading_plan(
            selected_paths[1:],
            sample_bytes,
            timing.read_decode_s + timing.conversion_s,
            mode=mode,
            max_workers=max_workers,
            sample_suffix=Path(selected_paths[0]).suffix,
        )
        if logger is not None:
            logger.info(
                "Loading strategy: %s, %s worker(s). %s", plan.mode, plan.workers, plan.reason
            )
        remaining = list(enumerate(selected_paths))[1:]
        if plan.workers == 1:
            for index, path in remaining:
                batch.begin(index)
                batch.completed(index, *read_recording(load_sensor_file, path, allow_pickle))
        else:
            load_parallel(
                remaining,
                plan,
                load_sensor_file,
                allow_pickle,
                batch.completed,
                logger,
                batch.begin,
            )
    finally:
        batch.report()

    sources = {f"recording_{index + 1:03d}": path for index, path in enumerate(selected_paths)}
    frames = {key: batch.frames[index] for index, key in enumerate(sources)}
    return sources, frames


def source_key(file_key: str, results: AnalysisResults) -> str:
    return (
        results.get("metadata", {})
        .get("desktop_recordings", {})
        .get("sections", {})
        .get(file_key, file_key)
    )


def timeline_offsets(name: str, frame: pd.DataFrame, offsets: TimeOffsets) -> float | FloatArray:
    value = offsets.get(name.split("/")[1], 0.0)
    if isinstance(value, dict):
        return (
            frame["file_key"].map(value).fillna(0.0).to_numpy(dtype=float)
            if "file_key" in frame
            else 0.0
        )
    return value


def align_recordings(
    frames: dict[str, pd.DataFrame], settings: AnalysisSettings, results: AnalysisResults
) -> RecordingAlignment:
    """Display offsets only: never shift scientific timestamps or sensor values."""
    module_times: dict[str, dict[str, FloatArray]]
    common, module_times, clocks = {}, {}, {}
    local_offsets: dict[str, dict[str, float]] = {}
    for key, frame in frames.items():
        timeline, modules, offsets = analysis_alignment(frame, settings, results)
        if timeline is None:
            timeline = np.full(len(frame), np.nan)
        # With no saved offsets supplied, alignment constructs scalar offsets.
        common[key], local_offsets[key] = timeline, cast("dict[str, float]", offsets)
        for module, times in modules.items():
            module_times.setdefault(module, {})[key] = times
        clocks[key] = recording_clock(frame, settings, timeline)
    clock, bases = _clock_alignment(clocks)
    if clock is None:
        # Without comparable clocks, use an explicitly labelled file-order
        # display. No absolute dates or between-recording gaps are inferred.
        cursor = 0.0
        for key, times in common.items():
            finite = times[np.isfinite(times)]
            # NumPy's stubs omit the no-axis scalar reduction for floating arrays.
            start, end = (finite.min(), finite.max()) if len(finite) else (0.0, 0.0)  # type: ignore[call-overload]
            steps = np.diff(times)
            steps = steps[np.isfinite(steps) & (steps > 0)]
            bases[key] = cursor - start
            cursor += end - start + (float(np.median(steps)) if len(steps) else 1.0)
    sections = results.get("metadata", {}).get("desktop_recordings", {}).get("sections", {})
    combined_offsets: dict[str, dict[str, float]] = {}
    for file_key, key in sections.items():
        for module in settings.get("pipelines", []):
            combined_offsets.setdefault(module, {})[file_key] = bases.get(
                key, 0.0
            ) + local_offsets.get(key, {}).get(module, 0.0)
    return common, module_times, cast(TimeOffsets, combined_offsets), clock, bases


def preview_recording_clock(
    frames: dict[str, pd.DataFrame], settings: AnalysisSettings
) -> ClockMetadata | None:
    """Derive the batch clock without aligning result groups or file-order timelines."""
    clocks = {key: recording_clock(frame, settings) for key, frame in frames.items()}
    return _clock_alignment(clocks)[0]


def _clock_alignment(
    clocks: dict[str, ClockMetadata | None],
) -> tuple[ClockMetadata | None, dict[str, float]]:
    import pandas as pd

    known = {key: clock for key, clock in clocks.items() if clock is not None}
    available = [pd.Timestamp(clock["origin"]) for clock in known.values()]
    if len(known) != len(clocks) or len({stamp.tz is None for stamp in available}) != 1:
        return None, {}
    origin = min(available)
    earliest = min(known, key=lambda key: pd.Timestamp(known[key]["origin"]))
    try:
        clock = normalise_clock({**known[earliest], "source": "Multiple recording clocks"})
    except (ValueError, KeyError, TypeError):
        # Parquet can restore a fixed-offset tz with a non-IANA type name.
        clock = normalise_clock(
            {
                "origin": origin.isoformat(),
                "timezone": str(origin.tz) if origin.tz else None,
                "source": "Multiple recording clocks",
            }
        )
    bases = {
        key: (pd.Timestamp(value["origin"]) - origin).total_seconds()
        for key, value in known.items()
    }
    return clock, bases
