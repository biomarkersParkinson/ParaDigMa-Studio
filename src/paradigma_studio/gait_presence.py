"""Display-only gait presence on a common, explicitly observed time domain."""

import numpy as np

from .epochs import availability_epoch_summary
from .exploration import PARTICIPANT_COLUMNS


def union(intervals):
    intervals = np.asarray(intervals, dtype=float).reshape(-1, 2)
    valid = np.isfinite(intervals).all(axis=1) & (intervals[:, 1] > intervals[:, 0])
    intervals = intervals[valid]
    if not len(intervals):
        return intervals
    intervals = intervals[np.argsort(intervals[:, 0], kind="stable")]
    running_end = np.maximum.accumulate(intervals[:, 1])
    groups = np.r_[0, np.flatnonzero(intervals[1:, 0] > running_end[:-1] + 1e-9) + 1]
    return np.column_stack((intervals[groups, 0], np.maximum.reduceat(intervals[:, 1], groups)))


def intersection(left, right):
    output, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        start, end = max(left[i, 0], right[j, 0]), min(left[i, 1], right[j, 1])
        if end > start:
            output.append((start, end))
        if left[i, 1] <= right[j, 1]:
            i += 1
        else:
            j += 1
    return np.asarray(output, dtype=float).reshape(-1, 2)


def gait_presence_intervals(detection, arm_activity):
    """Join finite window states by recording/participant, never across files.

    Each frame contains start/end/state plus optional file_key/participant.
    Non-gait time is known zero for both. Gait-positive time with unknown arm
    filtering is excluded from BOTH percentage denominators, not made absence.
    When filtering is unavailable, gait retains its own observed domain.
    """
    import pandas as pd

    keys = [
        key
        for key in ("file_key", *PARTICIPANT_COLUMNS)
        if key in detection or arm_activity is not None and key in arm_activity
    ]

    def groups(frame):
        if frame is None:
            return {}
        copy = frame.copy()
        for key in keys:
            if key not in copy:
                copy[key] = "<unknown>"
            else:
                copy[key] = copy[key].astype(object).where(copy[key].notna(), "<unknown>")
        return copy.groupby(keys, dropna=False, sort=False) if keys else [((), copy)]

    # GroupBy's non-callable keys attribute is not a mapping interface. Use its
    # pair iterator explicitly, preserving recording/participant group isolation.
    filtered_groups = dict(iter(groups(arm_activity)))
    observed, positive, filtered, domain = [], [], [], []
    for key, frame in groups(detection):
        known = frame.state.isin([0.0, 1.0])
        intervals = frame[["start", "end"]].to_numpy()
        full = union(intervals[known])
        gait = union(intervals[frame.state.eq(1.0)])
        non_gait = union(intervals[frame.state.eq(0.0)])
        domain.extend(full)
        if arm_activity is None:
            observed.extend(full)
            positive.extend(gait)
            continue
        arm = filtered_groups.get(key, pd.DataFrame(columns=["start", "end", "state"]))
        arm_intervals = arm[["start", "end"]].to_numpy(dtype=float)
        arm_known = union(arm_intervals[arm.state.isin([0.0, 1.0])])
        arm_positive = union(arm_intervals[arm.state.eq(1.0)])
        jointly_known_gait = intersection(gait, arm_known)
        observed.extend(non_gait)
        observed.extend(jointly_known_gait)
        positive.extend(jointly_known_gait)
        filtered.extend(intersection(jointly_known_gait, arm_positive))
    return {
        "observed": union(observed),
        "gait": union(positive),
        "filtered": union(filtered),
        "domain": union(domain),
    }


def gait_epoch_summaries(intervals, phase=0.0):
    """Both percentages use the same seconds; filtered positives are a subset."""
    import pandas as pd

    domain = intervals["domain"]
    if not len(domain):
        empty = pd.DataFrame(columns=["start_s", "end_s", "value", "observed_s", "positive_s"])
        return {"gait": empty, "filtered": empty.copy()}
    bounds = domain[:, 0].min(), domain[:, 1].max()

    def coverage(kind):
        pairs = intervals[kind]
        return availability_epoch_summary(pairs[:, 0], pairs[:, 1], phase=phase, bounds=bounds)

    denominator = coverage("observed").covered_s.to_numpy()
    output = {}
    for kind in ("gait", "filtered"):
        frame = coverage(kind)
        positive = frame.covered_s.to_numpy()
        values = np.divide(
            positive * 100, denominator, out=np.full(len(frame), np.nan), where=denominator > 0
        )
        output[kind] = pd.DataFrame(
            {
                "start_s": frame.start_s,
                "end_s": frame.end_s,
                "value": values,
                "observed_s": denominator,
                "positive_s": positive,
            }
        )
    return output
