"""Decode TSDF physical values before displaying or preparing a recording."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from .input_metadata import METADATA_KEY

if TYPE_CHECKING:
    import pandas as pd


def load_tsdf_sensor_file(path: Path) -> tuple[pd.DataFrame, datetime | None]:
    """Use the official reader, then apply each stream's declared scale factors.

    TSDF 0.6.2 and ParaDigMa 1.1.2 return stored binary values unchanged.
    The TSDF pandas tutorial multiplies each channel by its scale factor;
    sensor-unit conversion remains the responsibility of ParaDigMa preparation.
    """
    from paradigma.load import load_tsdf_data

    prefix = path.stem.replace("_meta", "")
    frame, time_metadata, value_metadata = load_tsdf_data(path.parent, prefix)
    if not frame.columns.is_unique:
        raise ValueError("TSDF metadata must contain unique channel names across streams.")
    for metadata in (time_metadata, value_metadata):
        _scale_stream(frame, metadata)
    frame.attrs[METADATA_KEY] = {
        "format": "tsdf",
        "units": {
            channel: unit
            for metadata in (time_metadata, value_metadata)
            for channel, unit in zip(metadata.channels, metadata.units, strict=True)
        },
    }
    start = getattr(time_metadata, "start_iso8601", None)
    return frame, datetime.fromisoformat(start) if start is not None else None


def _scale_stream(frame: pd.DataFrame, metadata: Any) -> None:
    factors = getattr(metadata, "scale_factors", [])
    if not isinstance(factors, list):
        raise ValueError("TSDF scale_factors must be a list of finite numbers, one per channel.")
    # ParaDigMa writes an empty list for already-scaled streams. Missing factors
    # likewise mean the binary values already use the declared units.
    if not factors:
        return
    if len(factors) != len(metadata.channels) or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value)
        for value in factors
    ):
        raise ValueError("TSDF scale_factors must contain one finite number per channel.")
    for channel, factor in zip(metadata.channels, factors, strict=True):
        if factor != 1:
            # Cast within the ufunc before multiplying, preserving double
            # precision and avoiding an additional converted array. The output
            # is new storage; the reader's potentially read-only view is untouched.
            with np.errstate(all="ignore"):
                frame[channel] = np.multiply(frame[channel].to_numpy(), factor, dtype=float)
