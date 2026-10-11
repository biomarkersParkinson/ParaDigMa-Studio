# Official ParaDigMa test recordings

These fixtures come from the official ParaDigMa repository at commit
[`4735d6d21b2a62b764a0bc7e0f677577e6ce1668`](https://github.com/biomarkersParkinson/paradigma/tree/4735d6d21b2a62b764a0bc7e0f677577e6ce1668/tests).
Its package version is 1.1.2, matching the desktop dependency. They are public
upstream test recordings, not user imports. ParaDigMa contributors retain their
copyright; distribution follows the upstream Apache 2.0 license, reproduced in
[`LICENSE-paradigma.txt`](../../../src/paradigma_studio/data/notices/LICENSE-paradigma.txt).

Changes: original TSDF time/value binaries were decoded with `tsdf` and written
as compressed Parquet without altering channel values or timestamps. The IMU
fixture retains all 72,947 rows from `tests/data/1.prepared_data/imu/`. The PPG
fixture retains the first 18,000 rows from `tests/data/1.prepared_data/ppg/`
(approximately 179 seconds). Metadata identifies a Verily Study Watch recording,
with acceleration in g, angular velocity in deg/s and time in relative seconds.
`manifest.json` records the source revision, selection, source file SHA-256 hashes
and converted file SHA-256 hashes. Tests verify those hashes and row counts.
These fixtures are used only by source tests and are not bundled in the app.

Reproduce the conversion from that upstream checkout using the installed app
dependencies (replace `upstream` with its local path):

```python
from pathlib import Path
import tsdf
from tsdf.constants import ConcatenationType

upstream = Path("/path/to/paradigma")
destination = Path("tests/data/paradigma")
for sensor, limit in [("imu", None), ("ppg", 18000)]:
    source = upstream / "tests/data/1.prepared_data" / sensor
    metadata = tsdf.load_metadata_from_path(source / f"{sensor}_meta.json")
    frame = (
        tsdf.load_dataframe_from_binaries(
            [metadata[f"{sensor}_time.bin"], metadata[f"{sensor}_values.bin"]],
            ConcatenationType.columns,
        )
        .iloc[:limit]
        .copy()
    )
    frame.to_parquet(destination / f"prepared_{sensor}.parquet", index=False, compression="zstd")
```

Parquet file bytes may change with writer versions. Verify decoded values against
the source binaries before intentionally replacing fixtures and their hashes.
See [`SCIENTIFIC_TESTS.md`](../../../docs/SCIENTIFIC_TESTS.md) for numerical
comparison rules and the distinction between default and configured PPG tests.
