"""Run descriptions report phase durations without counting time between phases."""

import pytest
from run_fixtures import make_run

from paradigma_studio.run_controller import RunController


def test_summary_retains_versions_counts_and_independent_phase_durations():
    record = make_run()
    record.update(
        studio_version="2.0",
        paradigma_version="1.2",
        warnings=["warning"],
        errors=[],
        started="2026-11-07T10:02:14+00:00",
        finished="2026-11-07T10:08:12+00:00",
        analysis_started="2026-11-07T10:05:00+00:00",
        loading={"started": "2026-11-07T10:02:14+00:00", "finished": "2026-11-07T10:02:38+00:00"},
    )
    assert RunController.run_summary_text(record) == (
        "Studio 2.0 · ParaDigMa 1.2 · 1 warning, 0 errors · Loading 24 s · Analysis 3 min 12 s"
    )


@pytest.mark.parametrize(
    "start,finish,duration",
    [
        ("2026-11-07T23:59:30+00:00", "2026-11-08T00:01:00+00:00", "1 min 30 s"),
        ("2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00", "1 h"),
        ("2026-11-07T10:00:00+00:00", "2026-11-09T11:02:03+00:00", "2 d 1 h 2 min 3 s"),
        ("2026-11-07T10:00:00+00:00", "2026-11-07T10:00:00+00:00", "0 s"),
    ],
)
def test_legacy_analysis_duration_uses_elapsed_time_across_dates_and_offsets(
    start, finish, duration
):
    record = make_run()
    record.update(started=start, finished=finish)
    summary = RunController.run_summary_text(record)
    assert summary.endswith(f" · Analysis {duration}") and "Loading" not in summary
    assert "2026-" not in summary and "10:" not in summary


@pytest.mark.parametrize("analysis,finished", [(False, True), (True, False), (False, False)])
def test_import_only_or_unfinished_phases_do_not_invent_an_analysis_duration(analysis, finished):
    record = make_run()
    record["loading"] = {"started": "2026-11-07T10:00:00+00:00", "finished": None}
    if finished:
        record["loading"]["finished"] = record["finished"] = "2026-11-07T10:00:24+00:00"
    if analysis:
        record["analysis_started"] = "2026-11-07T10:02:00+00:00"
        record["loading"]["finished"] = "2026-11-07T10:00:24+00:00"
    summary = RunController.run_summary_text(record)
    assert "Analysis" not in summary
    assert ("Loading 24 s" in summary) is (finished or analysis)
