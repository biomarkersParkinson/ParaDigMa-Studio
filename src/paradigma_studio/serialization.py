"""Atomic, lossless JSON/CSV exports and spreadsheet-safe text conversion."""

from __future__ import annotations

import csv
import json
import math
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from .contracts import AnalysisResults, JSONValue, PathInput, Provenance
from .result_integrity import DigestTextWriter
from .saved_format import FORMAT_VERSION, RESULT_FORMAT
from .storage import atomic_file, recording_files, same_file

if TYPE_CHECKING:
    import pandas as pd


def json_value(value: Any) -> JSONValue:
    # DataFrame.to_dict produces native scalars. Keep their frequent path free
    # of repeated scientific-type checks and pandas imports during large saves.
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    import pandas as pd

    if isinstance(value, pd.DataFrame):
        return {
            "columns": [json_value(column) for column in value.columns],
            "data": json_value(value.to_dict(orient="records")),
        }
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, np.generic):
        return json_value(value.item())
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _validate_export_destination(path, source=None, protected_sources=()):
    for original in recording_files([source, *protected_sources]):
        if same_file(path, original):
            raise ValueError(
                "An export cannot overwrite the loaded sensor file or its companion binaries. Choose another filename."
            )


def _write_export(path, writer, *, source=None, protected_sources=(), binary=False):
    target = Path(path)
    _validate_export_destination(target, source, protected_sources)
    with atomic_file(target, binary=binary, newline="") as stream:
        return writer(stream)


def _json_records(frame: pd.DataFrame) -> JSONValue:
    """Normalize a table batch, reusing its freshly created string-keyed rows."""
    records = frame.to_dict(orient="records")
    if any(type(column) is not str for column in frame.columns):
        # Preserve key conversion, collisions and ordering for other labels.
        return json_value(records)
    for record in records:
        for key, child in record.items():
            if type(child) is float:
                if not math.isfinite(child):
                    record[key] = None
            elif child is not None and type(child) not in (str, int, bool):
                # Nested values still need copies to protect the source objects.
                record[key] = json_value(child)
    # Keys are native strings and each remaining value is normalized above.
    return cast(JSONValue, records)


def _write_json(stream, value):
    """Lossless standard JSON, bounding temporary row objects to one table batch."""
    import pandas as pd

    def encode(child):
        return json.dumps(child, allow_nan=False, separators=(",", ":"))

    if isinstance(value, pd.DataFrame):
        stream.write('{"columns":' + encode(json_value(list(value.columns))) + ',"data":[')
        for start in range(0, len(value), 1000):
            if start:
                stream.write(",")
            records = _json_records(value.iloc[start : start + 1000])
            stream.write(encode(records)[1:-1])
            del records
            # Short native encoding blocks and an explicit yield keep Qt's busy
            # indicator and navigation responsive during large background saves.
            time.sleep(0)
        stream.write("]}")
    elif isinstance(value, dict):
        stream.write("{")
        for index, (key, child) in enumerate(
            {str(key): child for key, child in value.items()}.items()
        ):
            if index:
                stream.write(",")
            stream.write(encode(str(key)) + ":")
            _write_json(stream, child)
        stream.write("}")
    else:
        stream.write(encode(json_value(value)))


def export_results(
    path: PathInput,
    results: AnalysisResults,
    provenance: Provenance,
    *,
    protected_sources: Iterable[PathInput] = (),
) -> str:
    def write(stream):
        writer = DigestTextWriter(stream)
        _write_json(
            writer,
            {
                "format": RESULT_FORMAT,
                "format_version": FORMAT_VERSION,
                "analysis": provenance,
                "results": results,
            },
        )
        return writer.hexdigest()

    return _write_export(
        path,
        write,
        source=provenance.get("source"),
        protected_sources=protected_sources,
    )


def _spreadsheet_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def csv_metadata_path(path: PathInput) -> Path:
    """Keep table and companion names unambiguous even with unusual extensions."""
    return Path(str(path) + ".metadata.json")


def export_table_csv(
    path: PathInput,
    frame: pd.DataFrame,
    *,
    source: PathInput | None = None,
    protected_sources: Iterable[PathInput] = (),
    provenance: Provenance | None = None,
) -> None:
    """Write a spreadsheet-safe table and, for app exports, its analysis metadata."""
    safe = frame.map(_spreadsheet_text)
    safe.columns = [_spreadsheet_text(str(column)) for column in frame.columns]
    protected = tuple(protected_sources)
    if provenance is None:
        _write_export(
            path,
            lambda stream: safe.to_csv(stream, index=False, quoting=csv.QUOTE_ALL),
            source=source,
            protected_sources=protected,
        )
        return
    source = source or provenance.get("source")
    protected = (*protected, *provenance.get("sources", {}).values())
    metadata = csv_metadata_path(path)
    # Validate both destinations before staging either file. Both writes must
    # finish before replacement; the checksum also detects a mismatched pair
    # if a filesystem failure interrupts the two separate replacements.
    _validate_export_destination(path, source, protected)
    _validate_export_destination(metadata, source, protected)
    with atomic_file(metadata, newline="") as meta_stream, atomic_file(path, newline="") as stream:
        writer = DigestTextWriter(stream)
        safe.to_csv(writer, index=False, quoting=csv.QUOTE_ALL)
        _write_json(
            meta_stream,
            {
                "analysis": provenance,
                "csv": {"file": Path(path).name, "sha256": writer.hexdigest()},
            },
        )
