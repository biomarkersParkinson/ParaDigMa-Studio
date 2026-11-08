"""Static interface regressions; every ignore must suppress a real diagnostic."""

from io import BytesIO, StringIO
from multiprocessing.queues import Queue
from typing import BinaryIO, TextIO

import pandas as pd

from paradigma_studio.analysis_process import QueueLogHandler
from paradigma_studio.contracts import (
    AnalysisEvent,
    ClockMetadata,
    FloatArray,
    GaitIntervals,
    GaitSummaries,
    PositionArray,
    RecordingEvent,
    RunRecord,
)
from paradigma_studio.epochs import epoch_summary
from paradigma_studio.exploration import SensorContext, select_rows, source_timeline
from paradigma_studio.gait_presence import gait_epoch_summaries, gait_presence_intervals
from paradigma_studio.recordings import load_recordings
from paradigma_studio.run_controller import RunController
from paradigma_studio.sensor_navigation import SensorNavigator, SensorTimeIndex
from paradigma_studio.serialization import _write_export, _write_json
from paradigma_studio.time_navigation import TimeToolbar
from paradigma_studio.workspace_state import ResultState


def interfaces(
    frame: pd.DataFrame,
    times: FloatArray,
    clock: ClockMetadata,
    state: ResultState,
    runs: RunController,
    owner: RunRecord,
    toolbar: TimeToolbar,
    single: Queue[AnalysisEvent],
    batch: Queue[RecordingEvent],
) -> None:
    QueueLogHandler(single)
    QueueLogHandler(batch)
    single.put(("progress", "", 500))
    batch.put(("progress", "recording_001", 500))
    batch.put(("task_completed", 0))
    single.put(("completed",))
    batch.put(("log", 30, "Warning", "Full diagnostic"))

    rows: tuple[pd.DataFrame, PositionArray] = select_rows(frame, column="time", minimum="1")
    state._detail_selections["quantifications/tremor"] = rows
    state.result_timeline = source_timeline(frame, {"time_input_unit": "difference_ms"})
    context = SensorContext(frame, times, times, 0.0, 10.0, 5.0)
    navigator = SensorNavigator(context, clock, index=SensorTimeIndex(times))
    positions: PositionArray = navigator.positions((0.0, 10.0))
    context.frame.iloc[positions]
    intervals: GaitIntervals = gait_presence_intervals(frame, None)
    summaries: GaitSummaries = gait_epoch_summaries(intervals)
    state._gait_epoch_cache = summaries
    epoch_summary(times, times, binary=True)
    runs.capture_error("Could not save", owner=owner)
    toolbar.zoom_time(0.5)
    load_recordings(["data.csv"], mode="threads", max_workers=2)

    def text_writer(stream: TextIO) -> str:
        _write_json(stream, {"original": frame})
        return "digest"

    def binary_writer(stream: BinaryIO) -> int:
        return stream.write(b"contents")

    digest: str = _write_export("results.json", text_writer)
    size: int = _write_export("results.bin", binary_writer, binary=True)
    _write_json(StringIO(), {"digest": digest, "bytes": size})

    single.put(("task_completed", 0))  # type: ignore[arg-type]
    batch.put(("completed",))  # type: ignore[arg-type]
    batch.put(("progress", 500, "recording_001"))  # type: ignore[arg-type]
    batch.put(("failed", 42))  # type: ignore[arg-type]
    batch.put(("task_completed", "0"))  # type: ignore[arg-type]
    select_rows(frame, minimum=1.0)  # type: ignore[arg-type]
    source_timeline(None, {})  # type: ignore[arg-type]
    navigator.positions(("0", "10"))  # type: ignore[arg-type]
    positions = times  # type: ignore[assignment]
    _incomplete: GaitSummaries = {"gait": frame}  # type: ignore[typeddict-item]
    intervals["observed"] = positions  # type: ignore[typeddict-item]
    intervals["unknown"] = times  # type: ignore[typeddict-unknown-key]
    state.result_timeline = "seconds"  # type: ignore[assignment]
    state._detail_selections["tremor"] = (frame, times)  # type: ignore[assignment]
    state._display_offsets["tremor"] = [1.0]  # type: ignore[assignment]
    runs.capture_error("Failure", owner="previous run")  # type: ignore[arg-type]
    load_recordings(["data.csv"], mode="threaded")  # type: ignore[arg-type]
    load_recordings(["data.csv"], max_workers="two")  # type: ignore[arg-type]
    toolbar.zoom_time("in")  # type: ignore[arg-type]
    digest = _write_export("binary.bin", binary_writer, binary=True)  # type: ignore[assignment]
    _write_export("binary.bin", text_writer, binary=True)  # type: ignore[call-overload]
    _write_export("text.json", binary_writer)  # type: ignore[arg-type]
    _write_json(BytesIO(), {})  # type: ignore[arg-type]
