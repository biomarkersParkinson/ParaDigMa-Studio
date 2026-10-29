# Python APIs and saved-run reference

This reference describes the current source. Install the
[reviewed environment](DEPENDENCIES.md) before calling these services. API
implementations and annotations are authoritative; the guide explains the public
entry points and persistence requirements.

## Python service APIs

Use these entry points for integrations without constructing the desktop window:

| Entry point | Input and return value |
| --- | --- |
| `core.load_sensor_file` | A supported file path → one original DataFrame; pickle requires `allow_pickle=True` |
| `recordings.load_recordings` | Paths → `(sources, frames)`, dictionaries sharing recording identifiers |
| `core.analyze` | One DataFrame or a dictionary of recordings plus `pipelines` → the result dictionary |
| `serialization.export_results` | Destination, results and provenance → a structured JSON export of the supplied outputs |
| `history.load_result_export` | Result JSON path → `(provenance, results)`, without loading sensor recordings |

`pipelines` accepts `gait`, `tremor`, `pulse_rate` or a sequence of those names.
`analyze` runs synchronously; GUI cancellation uses `analysis_process.run_isolated_analysis`
through the worker. Its multiple-recording path owns up to two spawned processes
directly and merges their outputs with official pooled aggregation functions.
One original recording uses the original single-process path even when its
preparation creates several gap sections. `max_workers=1` forces sequential
execution for profiling; it is an execution keyword, not an analytical setting.

`core.analyze(progress=AnalysisProgress(callback))` optionally reports integer
work units to synchronous integrations. See the
[progress lifecycle](ARCHITECTURE.md#analysis-progress) for weighting and delivery.

Missing-sample exclusion defaults to **False** in the Python
API and **True** in the GUI. Pass all original recording paths through
`protected_sources` when exporting several recordings programmatically.
The `core` export aliases remain available for existing callers.

The [preparation boundary](ARCHITECTURE.md#preparation-and-input-contracts)
explains why Studio prepares data explicitly before the official orchestrator.

## Saved-run contract

The source of truth is [`saved_format.py`](../src/paradigma_studio/saved_format.py).
Its format number is independent of the Studio and official ParaDigMa versions.
Change this reference with any incompatible persistence change; user-facing
saving/reopening guidance lives in the [user guide](USER_GUIDE.md#save-results).

Shared contracts type frames, paths, pipeline names, worker callbacks and process
messages. `RunRecord` and `RunOutput` are `TypedDict` schemas with required fields,
known status/format literals and optional export details and workspace caches.
`saved_format.py` defines independent history (`paradigma-studio.run`) and result
(`paradigma-studio.results`) envelopes, both with integer `format_version: 2`.
Readers reject missing, boolean, non-integer and unsupported versions; they never
migrate or rewrite files. Bump `FORMAT_VERSION` for incompatible persistence
changes rather than introducing missing-field migrations. History also requires
its current record fields, explicit Analyze settings and kind-specific output
fields. JSON output receipts require a checksum; export reopening requires
`complete: true`. CSV outputs remain valid
without JSON-specific fields, and local snapshots remain distinct from exports.
`new_run` stamps the format but callers constructing history records must provide
the complete current Analyze settings. Public extension metadata is retained,
while private frame/result caches are never restored from history JSON. The generic
result decoder enforces the result envelope; Runs additionally verifies identity
and the recorded checksum. Unsupported history entries produce issues without
hiding valid entries. The earlier application storage directory is not discovered.
Missing-result/clock handling remains available for partial analyses and recordings
without a calendar origin.

## Storage and analysis-time identity

User data goes to `%LOCALAPPDATA%\ParaDigMaStudio`; earlier `ParaDigMaDesktop`
storage is not discovered. Runs capture `studio_version`, `paradigma_version`
and an available `studio_build_commit` at creation. Frozen builds read the
commit from their `security/build-info.json`; source runs use the app checkout's
Git HEAD. Reopening and exporting use the recorded identity, never the current
environment.

Standalone CSVs have a `<filename>.csv.metadata.json` companion with analysis
provenance and the CSV SHA-256; receipts track both files for safe deletion.
See the [security policy](../SECURITY.md#safeguards-and-trust-boundaries) for
trust boundaries and limitations of these checks.
