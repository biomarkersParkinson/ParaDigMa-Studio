# Codebase audit and refactoring — 0.5.23

Historical report: validation and measurements describe this refactor only.
For current architecture and checks, see the [repository map](../REPOSITORY.md)
and [test suite guide](../TEST_SUITE.md).

Reviewed on 9 October 2026 against version 0.5.22, commit `1f495f6`. The objective
was internal quality and maintainability while preserving the application UI,
scientific processing, saved outputs and existing workflows.

## Findings and changes

| Area | Finding | Disposition |
| --- | --- | --- |
| Application architecture | `app.py` combined page construction, job signals, sensor rendering, result preparation and graph interactions with window coordination. | Extracted `ui/layout.py`, `ui/result_graphs.py`, `jobs.py`, `channels.py` and `result_data.py`. The main window retains ownership of widgets, workers and selection state. |
| Scientific boundary | Export encoding and file safety lived beside official processing adapters. | Moved encoding into `serialization.py` and shared storage operations into `storage.py`. Existing `core` export aliases remain available; official processing functions are unchanged. |
| Duplication | Exports and history independently implemented temporary writes and recognition of protected TSDF companion files. | Both now use the same atomic-write and file-identity helpers, preserving newline handling, JSON formats, protection of original inputs and existing output destinations on failure. |
| Presentation data | Timing/bar preparation and optional table columns were embedded in Qt handlers. | Moved these computations into Qt-independent functions with an explicit `ResultData` container. Original output frames remain separate from derived views. |
| Preview reliability | Failed calculations were cached as successful `None` values and marked published, preventing retry for the same key. | Failed calculations remain retryable; legitimate `None` results still cache. A regression fails against 0.5.22 and passes after the correction. |
| Result lifecycle | Clearing discarded results left references to graph artists, bar bounds and sensor-context views. | Clear those references and the hidden sensor model/figure while retaining loaded source data for subsequent analyses. Added a regression. |
| Resource paths | Moving page construction could change paths resolved relative to `__file__`. | Added the canonical packaged `assets.DATA_DIRECTORY`; the existing icons and device-axis graphic retain their original locations. |
| Import timing | The Matplotlib font cache must initialize before graph imports; official scientific imports must remain deferred. | Isolated cache initialization in `bootstrap.py` at the original import position. Startup tests and packaged probes continue checking deferred analysis imports. |
| Consistency | Dense formatting and unused imports made accumulated edits difficult to review. | Applied the pinned Ruff formatter, removed unused imports and addressed all selected lint findings. Kept otherwise-unused Qt application references alive under `_app` names. Both Windows workflows enforce these checks. |
| Developer documentation | The repository map described older responsibilities and proposed the extraction now implemented. | Updated the module map, ownership conventions and development commands; retained fixture provenance and licensing files. |

The main-window module decreased from 2,815 to 2,027 lines despite
expanding dense expressions into consistently formatted code. Existing methods
and import aliases remain available where tests or integrations use them.
Moved graph methods have identical parsed function bodies. The only page-builder
logic adjustment is resolving the device-axis graphic through the canonical
resource directory.

## Behavior and scientific validation

- Full local suite: **385 passed, one Windows-only signature check skipped**.
  All **31 independent scientific-equivalence tests** pass. Existing assertions
  for layout, help stability, graph values, epochs, thresholds, time alignment,
  multi-file aggregation, cancellation, deletion and exports remain enabled.
  Parsed-code comparison confirms that existing top-level test assertions have
  not been changed or relaxed.
- Three additional regressions cover preview retry, discarded-result cleanup
  and an interrupted history write preserving the existing record and removing
  the temporary file. Existing export tests cover failed writes and original-file
  protection, including linked files and TSDF binaries.
- Ruff import/error checks and formatting checks pass. Parsed-code comparisons
  also confirm that the official processing functions are unchanged; formatting
  has not introduced numerical edits.
- **20 UI screenshots are pixel-identical** to 0.5.22: Data and Results
  Overview/Graphs/Tables, Analyze with and without help, sensor context and Runs,
  at 960 × 650 and 1450 × 920. These comparisons use fixed synthetic recordings
  and matching temporary history paths.
- The rebuilt Linux executable passed the packaged smoke check from a separate
  temporary directory. This exercises actual gait/tremor/pulse-rate processing,
  classifier assets, recording readers, navigation, graphs, exports and notices.
- Module-level local imports have no dependency cycles after the extraction.

## Dependencies and distribution

`pip check` reports no broken requirements. The installed dependency audit
reviewed **87 packages**, with no blocking findings and two advisory entries
covered by the existing documented Python-binding exception for
`CVE-2026-25087`; see [security](../../SECURITY.md).

Official ParaDigMa remains pinned to **1.1.2**. Runtime dependencies, classifier
assets, licensed recordings, supported file readers, native DLL collection and
signing boundaries are retained. Ruff is a development dependency. Source and
reference fixtures are separate from the generated executable bundle.

## Performance and remaining boundaries

The existing bounded preview/table/epoch caches, deferred imports, incremental
plot reuse, isolated analysis cancellation and streaming exports already address
the main interaction costs. The refactor keeps these mechanisms. It removes
stale retained views and allows retries after transient preview failures; it does
not change algorithms, plotting density, scientific thresholds or export values.

A before/after benchmark uses 250,000 sensor rows, 30,000 rows per output table
and 200 history entries. Each workflow reports the median of three repetitions
with queued Qt painting included. Selected results:

| Workflow | 0.5.22 | 0.5.23 |
| --- | ---: | ---: |
| Analyze option changes, 10 actions | 0.0067 s | 0.0069 s |
| Recording switches, 12 actions | 0.4770 s | 0.4766 s |
| Results load | 0.2394 s | 0.2423 s |
| Show Results graphs | 0.4315 s | 0.3595 s |
| Select three detailed series | 1.2806 s | 1.2596 s |
| Select three epoch series | 0.6889 s | 0.5487 s |
| Graph clicks, 10 actions | 0.2530 s | 0.2300 s |
| JSON export | 0.2803 s | 0.2651 s |

There is no material regression in these measurements; faster timings alone do
not establish a repeatable speedup from a structural refactor. JSON and CSV ZIP
exports have identical byte counts before and after (6,065,028 and 168,997 bytes).
[Raw measurements](performance/performance-review-0.5.23.json) include every workflow and
individual timing. Five fresh-process launches of the packaged app had median
first-paint and launch-to-report times of 1.112 and 1.340 seconds, respectively;
none loaded analysis modules at startup. The Linux bundle is 565,615,703 bytes
(539.4 MiB). These measurements use the Linux Qt offscreen/Fusion backend,
rather than a local Windows session. The Windows workflows repeat source tests,
dependency checks, frozen execution and startup/UI benchmarks on their native runner. Windows
signature verification remains specific to the signed workflow.

`MainWindow` still coordinates shared selections and run state. Page and graph
mixins deliberately use its existing controls and callbacks; this preserves Qt
ownership and signal behavior during this refactor. New computation belongs in
Qt-independent helpers. Future substantial page changes can introduce standalone
controllers where ownership is clear, with the current regressions protecting
the transition. See the [repository map](../REPOSITORY.md) and
[development checks](../DEVELOPMENT.md).
