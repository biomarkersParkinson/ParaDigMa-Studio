"""Cached result summaries and display transforms, independent of Qt views."""

import numpy as np

from ..daily import daily_availability_summary, daily_summary, gait_daily_summaries
from ..epoch_profile import mean_epoch_profile
from ..epochs import availability_epoch_summary, epoch_phase, epoch_summary, require_epoch_presence
from ..exploration import PARTICIPANT_COLUMNS
from ..gait_presence import gait_epoch_summaries, gait_presence_intervals
from ..workspace_state import ResultState

PROFILE_VIEW = 3


def _is_tremor_power(name, metric):
    return name.split("/")[1] == "tremor" and metric == "tremor_power"


class ResultPlotData:
    def __init__(self, results: ResultState) -> None:
        self.results = results

    def gait_plot_presence(self):
        import pandas as pd

        if self.results._gait_presence_cache is None:

            def frame(stage, metric):
                name = "classifications/gait/" + stage
                source = self.results._plot_tables.get(name)
                if source is None or metric not in source:
                    return None
                data = pd.DataFrame(
                    {
                        "start": self.results._timings[name]["Timeline time (s)"].to_numpy(),
                        "end": self.results._interval_ends[name],
                        "state": source[metric].to_numpy(dtype=float, na_value=np.nan),
                    }
                )
                for key in ("file_key", *PARTICIPANT_COLUMNS):
                    if key in source:
                        data[key] = source[key].to_numpy()
                return data

            detection = frame("detection", "pred_gait_window")
            self.results._gait_presence_cache = gait_presence_intervals(
                detection
                if detection is not None
                else pd.DataFrame(columns=["start", "end", "state"]),
                frame("arm_activity", "pred_no_other_arm_activity_window"),
            )
        return self.results._gait_presence_cache

    def epoch_plot_data(self, name, metric, positions, binary, mode):
        if mode == 2:
            return self.daily_plot_data(name, metric, positions, binary)
        key = name, metric, id(positions)
        if key not in self.results._epoch_views:
            times = self.results._timings[name]["Timeline time (s)"].to_numpy()[positions]
            phase = epoch_phase(self.results.display_clock)
            if name.startswith("classifications/gait/") and metric in (
                "pred_gait_window",
                "pred_no_other_arm_activity_window",
            ):
                if self.results._gait_epoch_cache is None:
                    self.results._gait_epoch_cache = gait_epoch_summaries(
                        self.gait_plot_presence(), phase
                    )
                frame = self.results._gait_epoch_cache[
                    "gait" if metric == "pred_gait_window" else "filtered"
                ]
            elif name.startswith("preparation/"):
                extent = self.results.provenance.get("recording_extent", {})
                try:
                    bounds = float(extent["start_s"]), float(extent["end_s"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    bounds = None
                frame = availability_epoch_summary(
                    times, self.results._interval_ends[name][positions], phase=phase, bounds=bounds
                )
            else:
                values = self._result_plot_values(name, metric, positions)
                frame = epoch_summary(times, values, binary=binary, phase=phase)
                if (
                    name.startswith("quantifications/gait/")
                    and any(part in str(metric) for part in ("range_of_motion", "peak_velocity"))
                    or name.startswith("quantifications/tremor")
                    and "tremor_power" in str(metric)
                ):
                    frame = require_epoch_presence(frame, self.epoch_metric_presence(name))
            self.results._epoch_views[key] = frame
        summary = self.results._epoch_views[key]
        if mode == PROFILE_VIEW:
            profile_key = "profile", *key
            if profile_key not in self.results._epoch_views:
                self.results._epoch_views[profile_key] = mean_epoch_profile(
                    summary, self.results.display_clock
                )
            return self.results._epoch_views[profile_key]
        return summary

    def daily_plot_data(self, name, metric, positions, binary):
        key = "day", name, metric, id(positions)
        if key not in self.results._epoch_views:
            if name.startswith("classifications/gait/") and metric in (
                "pred_gait_window",
                "pred_no_other_arm_activity_window",
            ):
                gait_key = "day", "gait_presence"
                if gait_key not in self.results._epoch_views:
                    self.results._epoch_views[gait_key] = gait_daily_summaries(
                        self.gait_plot_presence(), self.results.display_clock
                    )
                frame = self.results._epoch_views[gait_key][
                    "gait" if metric == "pred_gait_window" else "filtered"
                ]
            elif name.startswith("preparation/"):
                frame = daily_availability_summary(
                    self.results._timings[name]["Timeline time (s)"].to_numpy()[positions],
                    self.results._interval_ends[name][positions],
                    self.results.display_clock,
                )
            else:
                starts, ends = self.results._bar_bounds[name]
                frame = daily_summary(
                    self.results._timings[name]["Timeline time (s)"].to_numpy()[positions],
                    self._result_plot_values(name, metric, positions),
                    starts[positions],
                    ends[positions],
                    self.results.display_clock,
                    binary=binary,
                )
            self.results._epoch_views[key] = frame
        return self.results._epoch_views[key]

    def epoch_metric_presence(self, name):
        if name not in self.results._epoch_presence_views:
            pairs = np.empty((0, 2))
            if name.startswith("quantifications/gait/"):
                filtered = name.endswith("/filtered")
                stage = "classifications/gait/" + ("arm_activity" if filtered else "detection")
                indicator = "pred_no_other_arm_activity_window" if filtered else "pred_gait_window"
                if (
                    stage in self.results._plot_tables
                    and indicator in self.results._plot_tables[stage]
                ):
                    if filtered:
                        pairs = self.gait_plot_presence()["filtered"]
                    else:
                        # Unfiltered gait does not require an arm-filter label.
                        source = self.results._plot_tables[stage]
                        positive = source.pred_gait_window.eq(1).fillna(False).to_numpy(dtype=bool)
                        pairs = np.column_stack(
                            (
                                self.results._timings[stage]["Timeline time (s)"].to_numpy()[
                                    positive
                                ],
                                self.results._interval_ends[stage][positive],
                            )
                        )
                elif "gait_segment_nr" in self.results._plot_tables[name]:
                    # Older saved runs may only contain quantified segments.
                    # Their known full bounds, not swing counts, establish time.
                    timing = self.results._timings[name]
                    offset = timing["Timeline time (s)"] - timing["Analysis time (s)"]
                    pairs = np.column_stack(
                        (timing["Segment start (s)"] + offset, timing["Segment end (s)"] + offset)
                    )
            else:
                for candidate in ("classifications/tremor", name):
                    tremor_source = self.results._plot_tables.get(candidate)
                    if tremor_source is not None and "pred_tremor_checked" in tremor_source:
                        positive = (
                            tremor_source.pred_tremor_checked.eq(1)
                            .fillna(False)
                            .to_numpy(dtype=bool)
                        )
                        pairs = np.column_stack(
                            (
                                self.results._timings[candidate]["Timeline time (s)"].to_numpy()[
                                    positive
                                ],
                                self.results._interval_ends[candidate][positive],
                            )
                        )
                        break
            self.results._epoch_presence_views[name] = availability_epoch_summary(
                pairs[:, 0], pairs[:, 1], phase=epoch_phase(self.results.display_clock)
            )
        return self.results._epoch_presence_views[name]

    def _result_plot_values(self, name, metric, positions):
        values = (
            self.results._plot_tables[name][metric]
            .iloc[positions]
            .to_numpy(dtype=float, na_value=np.nan)
        )
        if _is_tremor_power(name, metric):
            # Match ParaDigMa's aggregation transform, before epoch medians.
            # Create a separate array; scientific tables and exports stay raw.
            with np.errstate(divide="ignore", invalid="ignore"):
                values = np.log10(values + 1)
        return values
