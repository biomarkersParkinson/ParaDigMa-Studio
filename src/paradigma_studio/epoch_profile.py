"""A display-only 24-hour profile of existing half-hour summaries."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np

from .daily import DAY_SECONDS
from .epochs import EPOCH_SECONDS
from .results_view import clock_times

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pandas as pd


def mean_epoch_profile(summary: pd.DataFrame, clock: Mapping[str, Any] | None) -> pd.DataFrame:
    """Mean valid epoch values by local clock slot, with one contribution per day.

    Existing medians, percentages and presence gates have already been applied.
    Repeated half-hours on a DST fallback day are averaged within that day first;
    missing half-hours, including spring-forward slots, never become zero.
    """
    import pandas as pd

    starts = summary.start_s.to_numpy(dtype=float, na_value=np.nan)
    values = summary.value.to_numpy(dtype=float, na_value=np.nan)
    valid = np.isfinite(starts) & np.isfinite(values)
    starts, values = starts[valid], values[valid]
    if clock is None:
        days = np.floor(starts / DAY_SECONDS).astype(np.int64)
        slots = np.floor(starts % DAY_SECONDS / EPOCH_SECONDS).astype(np.int64)
    else:
        stamps = clock_times(starts, clock)
        days = stamps.tz_localize(None).normalize().asi8
        slots = (stamps.hour * 60 + stamps.minute) // 30
    per_day = (
        pd.DataFrame({"day": days, "slot": slots, "value": values})
        .groupby(["day", "slot"], sort=False)
        .value.mean()
    )
    profile = (
        per_day.groupby("slot")
        .agg(value="mean", n_days="count")
        .reindex(range(int(DAY_SECONDS / EPOCH_SECONDS)))
    )
    starts = np.arange(len(profile)) * EPOCH_SECONDS
    return pd.DataFrame(
        {
            "start_s": starts,
            "end_s": starts + EPOCH_SECONDS,
            "value": profile.value.to_numpy(),
            "n_days": profile.n_days.fillna(0).to_numpy(dtype=int),
        }
    )


def format_profile_time(value: float) -> str:
    """Clock-style labels for a numeric profile axis, including its 24:00 end."""
    sign = "-" if value < 0 else ""
    seconds = round(abs(value), 6)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    text = f"{sign}{int(hours):02d}:{int(minutes):02d}"
    if not math.isclose(seconds, 0, abs_tol=1e-6):
        text += f":{seconds:09.6f}".rstrip("0").rstrip(".")
    return text


def parse_profile_time(text: str) -> float:
    """Accept HH:MM[:SS] or seconds in the profile's horizontal-limit fields."""
    parts = text.strip().split(":")
    if len(parts) == 1:
        return float(text)
    if len(parts) not in (2, 3):
        raise ValueError("Use HH:MM[:SS] or seconds.")
    hours, minutes = abs(int(parts[0])), int(parts[1])
    seconds = float(parts[2]) if len(parts) == 3 else 0.0
    if not 0 <= minutes < 60 or not 0 <= seconds < 60:
        raise ValueError("Minutes and seconds must be between 0 and 60.")
    value = hours * 3600 + minutes * 60 + seconds
    return -value if parts[0].startswith("-") else value
