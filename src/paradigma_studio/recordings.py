"""Independent recordings sharing one subject and one analysis configuration."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

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
) -> tuple[dict[str, str], dict[str, pd.DataFrame]]:
    sources, frames = {}, {}
    selected_paths = list(dict.fromkeys(map(str, paths)))
    if progress is not None and len(selected_paths) > 1:
        progress(0)
    for index, path in enumerate(selected_paths, start=1):
        key = f"recording_{index:03d}"
        if logger:
            logger.info("Loading %s: %s", key, path)
        try:
            frames[key] = load_sensor_file(path, allow_pickle=allow_pickle)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{Path(path).name}: {exc}") from exc
        sources[key] = path
        if progress is not None:
            progress(1000 * index // len(selected_paths))
    if not frames:
        raise ValueError("Select at least one sensor recording.")
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
    common, module_times, local_offsets, clocks = {}, {}, {}, {}
    for key, frame in frames.items():
        timeline, modules, offsets = analysis_alignment(frame, settings, results)
        if timeline is None:
            timeline = np.full(len(frame), np.nan)
        common[key], local_offsets[key] = timeline, offsets
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
            start, end = (finite.min(), finite.max()) if len(finite) else (0.0, 0.0)
            steps = np.diff(times)
            steps = steps[np.isfinite(steps) & (steps > 0)]
            bases[key] = cursor - start
            cursor += end - start + (float(np.median(steps)) if len(steps) else 1.0)
    sections = results.get("metadata", {}).get("desktop_recordings", {}).get("sections", {})
    offsets = {}
    for file_key, key in sections.items():
        for module in settings.get("pipelines", []):
            offsets.setdefault(module, {})[file_key] = bases.get(key, 0.0) + local_offsets.get(
                key, {}
            ).get(module, 0.0)
    return common, module_times, offsets, clock, bases


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
