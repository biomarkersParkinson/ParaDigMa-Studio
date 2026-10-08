"""Display-only half-hour summaries; official outputs are never modified."""
import numpy as np
import pandas as pd

from .results_view import clock_origin


EPOCH_SECONDS = 1800.


def epoch_phase(clock):
    """Shared elapsed offset for local :00/:30 boundaries, including DST."""
    if clock is None:
        return 0.
    origin = clock_origin(clock)
    within_hour = origin.minute * 60 + origin.second + origin.microsecond / 1e6 + origin.nanosecond / 1e9
    return -(within_hour % EPOCH_SECONDS)


def epoch_summary(times, values, *, binary=False, phase=0.):
    """Median, or positive percentage of finite observations, by timestamp.

    Missing outcomes do not become absence; empty epochs stay blank. Estimated
    gait timestamps follow the same presentation-only timing as Detailed view.
    """
    times, values = np.asarray(times, dtype=float), np.asarray(values, dtype=float)
    finite_time = np.isfinite(times)
    values = values[finite_time].copy()
    values[~np.isfinite(values)] = np.nan
    if binary:
        values[~np.isin(values, [0., 1.])] = np.nan
    bins = np.floor((times[finite_time] - phase) / EPOCH_SECONDS)
    frame = pd.DataFrame({'epoch': bins, 'value': values})
    grouped = frame.groupby('epoch', sort=True).agg(
        value=('value', 'mean' if binary else 'median'), n_observations=('value', 'count'))
    starts = grouped.index.to_numpy(dtype=float) * EPOCH_SECONDS + phase
    return pd.DataFrame({'start_s': starts, 'end_s': starts + EPOCH_SECONDS,
                         'value': grouped.value.to_numpy() * (100 if binary else 1),
                         'n_observations': grouped.n_observations.to_numpy()})


def availability_epoch_summary(starts, ends, *, phase=0., bounds=None):
    """Covered time per epoch; union overlaps and retain real recording gaps.

    First/last epochs use the recording's partial timespan as their denominator.
    Source bounds also retain excluded leading/trailing input where available.
    """
    starts, ends = np.asarray(starts, dtype=float), np.asarray(ends, dtype=float)
    valid = np.isfinite(starts) & np.isfinite(ends) & (ends > starts)
    starts, ends = starts[valid], ends[valid]
    if bounds is None:
        if not len(starts):
            return pd.DataFrame(columns=['start_s', 'end_s', 'value', 'covered_s', 'observed_s'])
        bounds = float(starts.min()), float(ends.max())
    low, high = bounds
    if not np.isfinite([low, high]).all() or high <= low:
        return pd.DataFrame(columns=['start_s', 'end_s', 'value', 'covered_s', 'observed_s'])
    first = int(np.floor((low - phase) / EPOCH_SECONDS))
    last = int(np.ceil((high - phase) / EPOCH_SECONDS))
    epoch_starts = np.arange(first, last, dtype=float) * EPOCH_SECONDS + phase
    epoch_ends = epoch_starts + EPOCH_SECONDS
    merged = []
    for start, end in sorted(zip(np.maximum(starts, low), np.minimum(ends, high))):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    covered = np.zeros(len(epoch_starts))
    if merged:
        start, end = np.asarray(merged).T
        left = np.floor((start - phase) / EPOCH_SECONDS).astype(int) - first
        right = np.ceil((end - phase) / EPOCH_SECONDS).astype(int) - first - 1
        same = left == right
        np.add.at(covered, left[same], end[same] - start[same])
        cross = ~same
        np.add.at(covered, left[cross], epoch_ends[left[cross]] - start[cross])
        np.add.at(covered, right[cross], end[cross] - epoch_starts[right[cross]])
        difference = np.zeros(len(epoch_starts) + 1)
        np.add.at(difference, left[cross] + 1, EPOCH_SECONDS)
        np.add.at(difference, right[cross], -EPOCH_SECONDS)
        covered += np.cumsum(difference[:-1])
    observed = np.minimum(epoch_ends, high) - np.maximum(epoch_starts, low)
    return pd.DataFrame({'start_s': epoch_starts, 'end_s': epoch_ends,
                         'value': np.clip(100 * covered / observed, 0, 100),
                         'covered_s': covered, 'observed_s': observed})
