"""Static data contracts; each ignore must reject a real incompatible value."""

import pandas as pd

from paradigma_studio.contracts import AnalysisResults, ClockMetadata, FloatArray, TimeOffsets
from paradigma_studio.core import analyze
from paradigma_studio.result_contracts import (
    AvailabilitySection,
    ClassificationTables,
    PreparationMetadata,
    PreparedAvailability,
    ProcessingError,
    RecordingMetadata,
)
from paradigma_studio.result_data import ResultData, prepare_result_data
from paradigma_studio.results_view import clock_times, detail_tables


def data_contracts(frame: pd.DataFrame, times: FloatArray, clock: ClockMetadata) -> None:
    error: ProcessingError = {
        "pipeline": "gait",
        "stage": "preparation",
        "file": "recording_001",
        "error": "Skipped recording: Too few samples",
        "skipped": True,
    }
    preparation: PreparationMetadata = {
        "input_samples": 1000,
        "excluded_samples": 2,
        "by_recording": {"recording_001": {"input_samples": 1000, "analyzed_samples": 998}},
        "by_module": {"gait": {"continuous_sections": 2}},
    }
    recording: RecordingMetadata = {
        "recordings": ["recording_001"],
        "sections": {"segment_1": "recording_001"},
    }
    section: AvailabilitySection = {
        "samples": 998,
        "sample_interval_s": 0.01,
        "intervals": [[0.0, 9.98]],
    }
    availability: PreparedAvailability = {"gait": {"segment_1": section}}
    classifications: ClassificationTables = {"gait": {"detection": frame}, "tremor": frame}
    results: AnalysisResults = {
        "classifications": classifications,
        "quantifications": {"tremor": frame},
        "errors": [error, "Legacy diagnostic"],
        "metadata": {
            "desktop_recordings": recording,
            "desktop_preparation": preparation,
            "desktop_availability": availability,
            "upstream_extension": {"arbitrary": ["values", 123]},
        },
    }
    offsets: TimeOffsets = {"gait": 1.0, "tremor": {"segment_1": 2.0}}
    data: ResultData = prepare_result_data(results, offsets)
    tables: dict[str, pd.DataFrame] = detail_tables(results)
    data.tables.update(tables)
    elapsed: FloatArray = clock_times(times, None)
    calendar: pd.DatetimeIndex = clock_times(elapsed, clock)
    calendar.tz_convert("UTC")
    results = analyze(frame, pipelines="tremor")
    results["errors"] = [error]

    results["errors"] = 2  # type: ignore[typeddict-item]
    results["quantifications"] = frame  # type: ignore[typeddict-item]
    results["quantification"] = {}  # type: ignore[typeddict-unknown-key]
    error["skipped"] = "yes"  # type: ignore[typeddict-item]
    error["error"] = 42  # type: ignore[typeddict-item]
    error["pipeline"] = "balance"  # type: ignore[typeddict-item]
    recording["sections"] = ["segment_1"]  # type: ignore[typeddict-item]
    preparation["input_samples"] = "1000"  # type: ignore[typeddict-item]
    preparation["by_recording"] = {"recording_001": {"analyzed_samples": "998"}}  # type: ignore[typeddict-item]
    section["intervals"] = [["0", "1"]]  # type: ignore[list-item]
    data.tables["quantifications/tremor"] = [1.0]  # type: ignore[assignment]
    data.interval_ends["quantifications/tremor"] = 1.0  # type: ignore[assignment]
    offsets["gait"] = [1.0]  # type: ignore[assignment]
    elapsed = clock_times(times, clock)  # type: ignore[assignment]
    calendar = clock_times(times, None)  # type: ignore[assignment]
