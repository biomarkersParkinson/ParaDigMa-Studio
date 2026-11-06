# Python API and saved-run formats

Use Studio's Python services to load recordings, run analyses and read/write
results without constructing the desktop window. This reference also describes
the saved-run formats, storage layout and analysis-time provenance.

It describes the current source on `main`. Install the
[reviewed environment](DEPENDENCIES.md) first; implementation signatures and
annotations remain authoritative. The
[architecture guide](ARCHITECTURE.md) explains how the desktop connects these
services.

- [Python service APIs](#python-service-apis)
- [Saved-run contract](#saved-run-contract)
- [Storage and analysis-time identity](#storage-and-analysis-time-identity)

## Python service APIs

### Entry points

All modules below are under `paradigma_studio`. Import functions from their
implementing modules, as shown in the example.

| Entry point | Input and return value |
| --- | --- |
| [`core.load_sensor_file`](../src/paradigma_studio/core.py) | Supported sensor-file path → loaded DataFrame; trusted pickle input requires `allow_pickle=True` |
| [`recordings.find_sensor_files`](../src/paradigma_studio/recordings.py) | Folder → recursively discovered sensor paths, sorted by relative path; raises for an empty or unreadable selection |
| [`recordings.find_recording_files`](../src/paradigma_studio/recordings.py) | Files and folders → unique sensor paths, with recursive folder discovery and deterministic path ordering |
| [`recordings.load_recordings`](../src/paradigma_studio/recordings.py) | Paths → `(sources, frames)`, two dictionaries sharing recording identifiers |
| [`core.analyze`](../src/paradigma_studio/core.py) | DataFrame or recording dictionary, plus `pipelines` and processing options → result dictionary |
| [`serialization.export_results`](../src/paradigma_studio/serialization.py) | Destination, results and provenance → writes structured JSON and returns its SHA-256 string |
| [`serialization.export_table_csv`](../src/paradigma_studio/serialization.py) | Destination and DataFrame, with optional provenance/source protection → writes CSV and returns `None` |
| [`history.load_result_export`](../src/paradigma_studio/history.py) | Standalone result JSON → `(provenance, results)`, restoring tables without loading sensor recordings |
| [`history.load_verified_result_export`](../src/paradigma_studio/history.py) | Result JSON, expected run ID and checksum → the same pair after identity and exact-byte verification |

The `core` aliases for `export_results`, `export_table_csv` and `json_value`
remain available for existing callers. Shared frame, path, pipeline and result
types are defined in [`contracts.py`](../src/paradigma_studio/contracts.py);
processing keywords are defined in
[`preparation_contracts.py`](../src/paradigma_studio/preparation_contracts.py).

Both discovery functions select CSV, Parquet, CWA, Avro, pickle and TSDF
`*_meta.json` paths. They ignore other JSON and linked subfolders, deduplicate
resolved paths and do not decode samples or authorize pickle loading.
`find_recording_files` accepts mixed selections and overlapping folders; empty
folders contribute no files. An entirely empty selection, unavailable path or
discovery error raises without returning a partial list. Pass the returned paths
to `load_recordings`; pickle still requires `allow_pickle=True` after the caller
has established trust.

`load_recordings` accepts an optional `progress(value)` callback on a 0–1000
scale. It reports completed unique files; a batch first reports zero, while a
single-file read first reports completion after its reader returns. The optional
callbacks on `inspection.inspect_recording` and `inspection.inspect_recordings`
report existing statistics milestones on the same scale. Batch inspection
weights row/column counts and can invoke the callback from inspection threads;
callbacks must remain lightweight and GUI changes require queued delivery.
A custom `describe` used with inspection progress must accept the optional
`progress` keyword, as specified by `contracts.RecordingInspector`.

### Example: analyze a recording and export the results

This example expects a CSV with numeric relative seconds in `time` and canonical
`gyroscope_x`, `gyroscope_y`, `gyroscope_z` columns in degrees per second. Adjust
the paths, declared units and wrist side to match the actual recording.

```python
from pathlib import Path

from paradigma_studio.core import analyze, load_sensor_file
from paradigma_studio.history import load_result_export
from paradigma_studio.provenance import software_versions
from paradigma_studio.serialization import export_results

source = Path("recording.csv")
settings = {
    "pipelines": ["tremor"],
    "watch_side": "left",
    "time_input_unit": "relative_s",
    "gyroscope_units": "deg/s",
    "drop_missing_samples": False,
}
identity = software_versions()
frame = load_sensor_file(source)
results = analyze(frame, **settings)
if results.get("errors"):
    raise RuntimeError(results["errors"])

provenance = {"source": str(source), "settings": settings, **identity}
checksum = export_results(
    "results.json", results, provenance, protected_sources=[source]
)
restored_provenance, restored_results = load_result_export("results.json")
```

The returned dictionary can contain successful outputs alongside processing
errors; inspect `results.get("errors")` before accepting the analysis. The
example stops on any reported error. This writes a standalone result file;
Studio history uses the separate [run-record contract](#history-records) below.

For a batch, pass the `frames` returned by `load_recordings` to `analyze` and
include the matching `sources` dictionary in provenance. Use a shared
configuration for the recordings, and pass **all original source paths** through
`protected_sources=sources.values()` when exporting. Destination protection also
accounts for TSDF companion binaries.

For mapping-based batches, insufficient recordings are skipped independently:
fewer than two usable samples, or no continuous sections surviving the selected
minimum duration. Other preparation errors still raise. Skips appear in
`results["errors"]` with `file`, `pipelines`, `stage: "preparation"` and
`skipped: true`; `metadata.desktop_preparation.by_recording` retains their
`skipped_reason`, original sample count and zero analyzed samples/sections.
Source identities remain in `metadata.desktop_recordings`, while
`metadata.desktop_availability` includes only sections passed to ParaDigMa.
An all-skipped batch returns empty official result tables with those diagnostics.
Single-DataFrame preparation failures continue to raise. The same batch policy
applies through the process-isolated execution service below.

### Input conventions and defaults

`pipelines` accepts `"gait"`, `"tremor"`, `"pulse_rate"`, or a sequence of those
names. Gait requires accelerometer and gyroscope axes; tremor requires gyroscope
axes. Pulse rate requires raw green PPG in `green`; a complete accelerometer
triad, when supplied, participates in its input validation.

Time must be numeric. `time_input_unit` accepts `relative_s`, `relative_ms`,
`absolute_s`, `absolute_ms`, `difference_s` and `difference_ms`. Convert datetime
or timedelta columns to a supported numeric representation before analysis.

| Processing option | Python API default |
| --- | --- |
| `time_input_unit` | `"relative_s"` |
| `accelerometer_units` | `"g"`; also accepts `"m/s^2"` |
| `gyroscope_units` | `"deg/s"`; also accepts `"rad/s"` |
| `drop_missing_samples` | `False`; the GUI defaults to `True` |
| `split_by_gaps` | `False`; when enabled, omitted gap/minimum-section durations default to 1.5 seconds |
| `skip_preparation` | `False`; the explicit bypass requires prepared inputs with relative seconds |

Column and axis settings have distinct roles:

- **`column_mapping`** maps source names to canonical names. Without
  `signal_columns`, direct Python calls apply these literal renames.
- **`signal_columns`** maps every canonical signal to its source column or `None`.
  Include `time`, `green`, and all six accelerometer/gyroscope signals; each source
  column can be used once. These explicit selections take precedence for sensor
  and time columns.
- **`axis_inversions`** lists canonical sensor signals whose signs must be
  inverted, such as `["gyroscope_x"]`. Use column selection for axis swaps.
- **`device_orientation`** provides a global signed-axis orientation when
  per-sensor inversions are absent. A non-identity global orientation cannot be
  combined with explicit `axis_inversions`.

Declare the actual `watch_side`; ParaDigMa applies its wrist-side adjustment
during processing. The
[preparation boundary](ARCHITECTURE.md#preparation-and-input-contracts) explains
Studio's explicit preparation and handoff to the official orchestrator, including
its parameter-forwarding limitations.

Pass processing keywords to `analyze`. Display-only settings such as
`plot_time_origin` belong in recorded settings/provenance. Full desktop run
records have additional requirements under [History records](#history-records).

### Execution, progress and cancellation

`core.analyze` runs synchronously in the calling process, including when given
multiple recordings. Its optional `progress` argument accepts
`AnalysisProgress(callback)` from `analysis_progress`. The callback receives
increasing integer work units from 0 to 1000, inline with processing. These units
describe milestones; the [progress lifecycle](ARCHITECTURE.md#analysis-progress)
explains their weighting and GUI delivery.

For cancellable, process-isolated execution, use
[`analysis_process.run_isolated_analysis`](../src/paradigma_studio/analysis_process.py):

```text
run_isolated_analysis(frame, settings, logger, cancel, *, max_workers=None)
```

This is a signature summary. Supply a `logging.Logger` and a `threading.Event` as
`cancel`. The function also blocks its caller; the desktop invokes it through a
QThread worker. Setting the event requests cancellation, which raises
`AnalysisCancelled` after owned-process cleanup.

One original recording uses one spawned process, including all of its gap
sections. A compatible multi-recording batch can use up to two directly owned
processes and official pooled aggregation. `max_workers=1` caps execution at one
worker for profiling; `max_workers=2` still respects the automatic resource
policy. This keyword belongs to `run_isolated_analysis`, separately from
analytical settings. See [worker selection](PERFORMANCE.md#worker-selection)
for fallbacks. Guard scripts that spawn processes with
`if __name__ == "__main__":`.

## Saved-run contract

### Envelopes and versioning

[`saved_format.py`](../src/paradigma_studio/saved_format.py) defines two JSON
envelopes:

| File kind | `format` value and version |
| --- | --- |
| Run history | `"paradigma-studio.run"`, integer `format_version: 2` |
| Result snapshot/export | `"paradigma-studio.results"`, integer `format_version: 2` |

The format version is independent of Studio and official ParaDigMa versions.
Readers reject missing, boolean, non-integer and unsupported versions. They do
not migrate or rewrite files. Bump `FORMAT_VERSION` for incompatible persistence
changes and update this reference alongside the implementation. User-facing
saving/reopening instructions remain in the [user guide](USER_GUIDE.md#save-results).

### History records

`RunRecord` and `RunOutput` in `contracts.py` define required fields, known
status/kind literals, optional export details and transient workspace caches.
History validation is implemented in
[`history.py`](../src/paradigma_studio/history.py).

| Record fields | Contract |
| --- | --- |
| `format`, `format_version`, `id` | Current envelope; a 32-character lowercase hexadecimal ID matching the history filename |
| `started`, `finished`, `status` | Explicit timestamps/status; `finished` may be `None` |
| `source`, `settings`, optional `sources` | Source information; complete Analyze settings once analysis starts, or an empty dictionary for loading-only entries |
| `studio_version`, `paradigma_version`, optional `studio_build_commit` | Recorded operation identity; captured again at analysis start for a loading-created entry |
| `warnings`, `errors`, `log`, `outputs` | Diagnostics and kind-specific output receipts |
| Optional `loading` | Import ID, selections, start/finish timestamps, loader software identity and frozen loading log/warnings/errors |
| Optional `analysis_started` | Time analysis began, separately from import and time spent adjusting settings |

`history.new_run(source, settings)` stamps the envelope, ID, initial lifecycle
fields and software identity. Callers supply the complete current Analyze
settings: pipeline names, units, watch side, explicit `signal_columns`,
`axis_inversions` and `column_mapping`, missing-sample/gap policies and
`plot_time_origin`. Mapping must agree with the selected columns. Saved desktop
runs use normal preparation and identity global axes; the Python-only bypass and
non-identity global orientations are excluded from this contract.

The desktop additionally creates loading-only records through `run_lifecycle`.
Their statuses are `Loading`, `Loaded`, or a loading outcome (`Failed`,
`Cancelled`, `Unfinished`); they require valid loading context, empty settings and
no output receipts. Once `analysis_started` is present, the full existing Analyze
settings contract applies. Loading/Loaded entries cannot contain an analysis
outcome or reopen/save result tables. The first analysis reuses the import ID;
subsequent attempts inherit only the import context and receive new IDs.
Existing analysis records without these optional fields remain supported.

Public extension metadata is retained. Top-level private keys beginning with `_`,
including frame/result caches, are excluded from persisted history and never
restored from JSON. `RunHistory.load()` returns `(records, issues)`, reporting
invalid entries alongside valid records. Interrupted `Loading` and `Running` entries appear
as `Unfinished` in memory.

Run error summaries reconcile repeated diagnostics with structured failures using
their available recording/segment, pipeline, processing step and exception
context. Unmatched log-only failures are retained. `RunHistory.load()` applies
the same reconciliation to older rendered summaries in memory; it does not
rewrite history files or processing logs. This concerns history's `errors`
list; the scientific result payload's `errors` remains as returned by analysis.

Results Overview derives per-module counts from those same contexts, separating
explicit skips and mapping sections to original recordings through stored
recording metadata and provenance. Unknown attribution is omitted. The summary
is presentation data; it is not written into the scientific result payload.

### Result files and output receipts

A result envelope contains an `analysis` provenance dictionary and a `results`
dictionary. Tables are serialized as `columns`/`data` objects and restored as
DataFrames by the reader. Results and metadata can remain partial; a recording
without a calendar origin remains valid.

Every history output receipt includes `kind`, `path`, `saved` and `complete`.
Additional requirements depend on its kind:

- **JSON:** requires a recorded SHA-256 checksum. Reopening an exported JSON as a
  run result requires `complete: true` in its receipt.
- **Local snapshot:** requires complete JSON and remains distinct from adjustable
  user exports. Snapshot completeness is separate from the run's success status.
- **CSV:** uses `complete: false` and remains valid without JSON-specific fields.
  A recorded metadata companion must have the expected CSV companion path.

`load_result_export` validates the result envelope and table structure.
`load_verified_result_export` additionally checks the recorded checksum and owning
run ID, hashing the same bytes it decodes. Runs applies these identity/checksum
checks when reopening results from disk. See the
[security policy](../SECURITY.md#safeguards-and-trust-boundaries) for trust boundaries.

## Storage and analysis-time identity

### Application storage

By default, the Windows app stores user data under
`%LOCALAPPDATA%\ParaDigMaStudio`, with history under `runs` and local result
snapshots under `runs/results`. Other
platforms use Qt's generic data location with the same `ParaDigMaStudio` directory.
The former `ParaDigMaDesktop` directory is not discovered.

### Provenance

Runs capture `studio_version`, `paradigma_version` and an available
`studio_build_commit` at creation. Frozen builds read the commit from
`security/build-info.json`; source runs use the app checkout's Git HEAD.
Reopening and exporting retain the recorded analysis identity.

Programmatic exports receive provenance from the caller. The example captures
`software_versions()` before analysis and passes that identity to the exporter.
The helpers in [`provenance.py`](../src/paradigma_studio/provenance.py) implement
Studio's run-owned provenance and reject contradictory software/run identities.

### CSV metadata companions

When `export_table_csv` receives provenance, it writes a
`<filename>.csv.metadata.json` companion containing that provenance and the CSV's
SHA-256. Calls without provenance write the table alone. Studio's output receipts
track both files for safe deletion. See the
[CSV writer](../src/paradigma_studio/serialization.py) for source protection and
pair-replacement behavior.
