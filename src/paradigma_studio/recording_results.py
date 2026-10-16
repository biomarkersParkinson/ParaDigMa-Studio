"""Combine independently processed recordings using official pooled aggregates."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from .contracts import AnalysisResults, AnalysisSettings, Pipeline

if TYPE_CHECKING:
    import pandas as pd


def merge_recording_results(
    outputs: Sequence[AnalysisResults], settings: AnalysisSettings, logger: logging.Logger
) -> AnalysisResults:
    """Preserve input order, identities and the sequential module-group semantics."""
    pipelines = settings["pipelines"]
    pipelines = [pipelines] if isinstance(pipelines, str) else list(pipelines)
    grouped = "pulse_rate" in pipelines and len(pipelines) > 1
    groups = (
        [[name for name in pipelines if name != "pulse_rate"], ["pulse_rate"]]
        if grouped
        else [pipelines]
    )
    combined: AnalysisResults = {
        name: {} for name in ("quantifications", "classifications", "aggregations", "metadata")
    }
    combined["errors"] = []
    preparation = {}
    for group in groups:
        failure = _group_failure(outputs, group)
        if failure is not None:
            combined["errors"].append(failure)
            combined["aggregations"].update({pipeline: {} for pipeline in group})
            continue
        for pipeline in group:
            _merge_pipeline(combined, outputs, pipeline)
        for output in outputs:
            for error in output.get("errors", []):
                if error.get("pipeline") in group and error not in combined["errors"]:
                    combined["errors"].append(deepcopy(error))
        details = _merge_preparation(outputs, group[0], grouped)
        if grouped:
            preparation.update({pipeline: deepcopy(details) for pipeline in group})
        else:
            combined["metadata"]["desktop_preparation"] = details
        _merge_recording_metadata(combined, outputs, group)
        _aggregate_pipelines(combined, group, settings, logger)
    if grouped:
        combined["metadata"]["desktop_preparation"] = {
            "analysis_groups": groups,
            "by_module": preparation,
        }
    return combined


def _group_failure(outputs, group):
    # The sequential adapter validates every recording before running a group.
    # One preparation failure therefore invalidates that entire group, while
    # another independent module group can still succeed.
    return next(
        (
            deepcopy(error)
            for output in outputs
            for error in output.get("errors", [])
            if error.get("stage") == "desktop_execution" and error.get("pipelines") == group
        ),
        None,
    )


def _concatenate(frames: Sequence[pd.DataFrame], *, gait: bool = False) -> pd.DataFrame:
    import pandas as pd

    populated = [frame for frame in frames if not frame.empty]
    if populated:
        return pd.concat(populated, ignore_index=True)
    # The official orchestrator emits a canonical empty gait frame, and a
    # column-less empty frame for other modules. Local file attribution must
    # not introduce an extra column when the complete batch has no outcomes.
    if gait and frames:
        return frames[0].drop(columns="file_key", errors="ignore").iloc[:0].copy()
    return pd.DataFrame()


def _merge_pipeline(combined, outputs, pipeline):
    if pipeline == "gait":
        _merge_gait(combined, outputs)
    else:
        frames = [output["quantifications"][pipeline] for output in outputs]
        combined["quantifications"][pipeline] = _concatenate(frames)
        combined["metadata"][pipeline] = {}
        combined["aggregations"][pipeline] = {}
    classifications = [
        output.get("classifications", {}).get(pipeline)
        for output in outputs
        if pipeline in output.get("classifications", {})
    ]
    if classifications:
        if pipeline == "gait":
            names = dict.fromkeys(name for stages in classifications for name in stages)
            combined["classifications"][pipeline] = {
                name: _concatenate([stages[name] for stages in classifications if name in stages])
                for name in names
            }
        else:
            combined["classifications"][pipeline] = _concatenate(classifications)


def _merge_gait(combined, outputs):
    combined["quantifications"]["gait"] = {}
    combined["metadata"]["gait"] = {}
    combined["aggregations"]["gait"] = {"filtered": {}, "unfiltered": {}}
    for branch in ("filtered", "unfiltered"):
        offset, frames, segments = 0, [], {}
        for output in outputs:
            frame = output["quantifications"]["gait"][branch].copy()
            local = output["metadata"]["gait"][branch].get("per_segment", {})
            if "gait_segment_nr" in frame:
                frame["gait_segment_nr"] += offset
            frames.append(frame)
            segments.update(
                {int(number) + offset: deepcopy(value) for number, value in local.items()}
            )
            # Metadata-only segments consume IDs too, as in the orchestrator.
            maximum = int(frame.gait_segment_nr.max()) if not frame.empty else offset
            offset = max(offset, maximum, max(segments, default=offset))
        combined["quantifications"]["gait"][branch] = _concatenate(frames, gait=True)
        combined["metadata"]["gait"][branch] = {"per_segment": segments}


def _merge_preparation(outputs, pipeline, grouped):
    by_recording, sections = {}, 0
    for output in outputs:
        details = output["metadata"]["desktop_preparation"]
        if grouped:
            details = details["by_module"][pipeline]
        by_recording.update(deepcopy(details["by_recording"]))
        sections += details["continuous_sections"]
    return {
        "by_recording": by_recording,
        "input_samples": sum(item["input_samples"] for item in by_recording.values()),
        "excluded_samples": sum(item.get("excluded_samples", 0) for item in by_recording.values()),
        "analyzed_samples": sum(item["analyzed_samples"] for item in by_recording.values()),
        "continuous_sections": sections,
    }


def _merge_recording_metadata(combined, outputs, group):
    metadata = combined["metadata"]
    recording = metadata.setdefault("desktop_recordings", {"recordings": [], "sections": {}})
    coverage = metadata.setdefault("desktop_availability", {})
    for output in outputs:
        source = output["metadata"]["desktop_recordings"]
        for key in source["recordings"]:
            if key not in recording["recordings"]:
                recording["recordings"].append(key)
        for section, key in source["sections"].items():
            if section in recording["sections"] and recording["sections"][section] != key:
                raise ValueError(
                    "Recording identifiers overlap with generated section identifiers."
                )
            recording["sections"][section] = key
        for pipeline in group:
            coverage.setdefault(pipeline, {}).update(
                deepcopy(output["metadata"]["desktop_availability"][pipeline])
            )


def _aggregate_pipelines(combined, pipelines, settings, logger):
    for pipeline in pipelines:
        logger.info("Aggregating %s results across all recordings", pipeline)
        try:
            _aggregate_pipeline(combined, pipeline, settings)
        except Exception as exc:
            # One toolbox aggregation failure must not discard other modules.
            logger.exception("Failed to aggregate %s results: %s", pipeline, exc)
            combined["errors"].append(
                {"pipeline": pipeline, "stage": "aggregation", "error": str(exc)}
            )
            combined["aggregations"][pipeline] = (
                {"filtered": {}, "unfiltered": {}} if pipeline == "gait" else {}
            )


def _aggregate_pipeline(
    combined: AnalysisResults, pipeline: Pipeline, settings: AnalysisSettings
) -> None:
    import pandas as pd

    quantified = combined["quantifications"][pipeline]
    if pipeline == "gait":
        _aggregate_gait(combined, settings)
    elif not quantified.empty and pipeline == "tremor":
        from paradigma.config import TremorConfig
        from paradigma.pipelines.tremor_pipeline import aggregate_tremor

        frame = quantified.copy()
        if "time_dt" not in frame and "time" in frame:
            frame["time_dt"] = pd.to_datetime(frame["time"], unit="s")
        result = aggregate_tremor(frame, settings.get("tremor_config") or TremorConfig())
        combined["aggregations"][pipeline] = result["aggregated_tremor_measures"]
        combined["metadata"][pipeline] = result["metadata"]
    elif not quantified.empty and pipeline == "pulse_rate":
        from paradigma.pipelines.pulse_rate_pipeline import aggregate_pulse_rate

        values = quantified["pulse_rate"].dropna().values
        if len(values):
            result = aggregate_pulse_rate(
                values, aggregates=settings.get("aggregates") or ["mode", "99p"]
            )
            combined["aggregations"][pipeline] = result["pr_aggregates"]
            combined["metadata"][pipeline] = result["metadata"]


def _aggregate_gait(combined: AnalysisResults, settings: AnalysisSettings) -> None:
    from paradigma.pipelines.gait_pipeline import aggregate_arm_swing_params

    categories = _gait_categories(settings.get("gait_segment_categories"))
    for branch in ("filtered", "unfiltered"):
        frame = combined["quantifications"]["gait"][branch]
        if not frame.empty:
            combined["aggregations"]["gait"][branch] = aggregate_arm_swing_params(
                frame,
                segment_meta=combined["metadata"]["gait"][branch],
                gait_segment_categories=categories,
                aggregates=settings.get("aggregates") or ["median", "95p", "cov"],
            )


def _gait_categories(categories: Any) -> list[tuple[float, float]]:
    if categories is None:
        return [(0, 20), (20, float("inf"))]
    # Workers have already validated these through the official orchestrator.
    normalized = []
    for value in categories:
        bounds = value.strip("()").split(",") if isinstance(value, str) else value
        normalized.append((float(bounds[0]), float(bounds[1])))
    return normalized
