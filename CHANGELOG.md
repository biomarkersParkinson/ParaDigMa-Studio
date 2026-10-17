# Changelog

## Unreleased

- Reuse surviving Results plots when their shared time-axis owner is deselected.
  Paint only visible graphs after selection and horizontal scrolling; vertical
  scrolling reuses the existing bounded image and renders newly exposed graphs.
  Preserve original paths, manual limits, navigation, markers and full exports.

- Strengthen graph-settings tests against restored or renamed controls, avoid
  unrelated navigation fixtures and duplicate setup renders, and consolidate
  first-date checks while retaining partial-day, bounds and timezone coverage.
- Require complete mypy annotations for data and analysis controllers, with typed
  single/batch loading payloads, inspection caches, callbacks and analysis inputs;
  preserve deferred imports, source frames and job/cancellation behavior.
- Split analysis launch, sensor plotting and run-history refresh into named
  workflow helpers, preserving state/signal order and queued cancellation inputs.
- Add gradual mypy body checks for the entire UI package, with typed component
  contracts, explicit optional graphics caches and read-only clock inputs;
  retain deferred imports and the stricter service/controller checks.
- Extract Data page construction and responsive layout from the shared workspace
  builder, retaining widget order, shortcuts, callbacks and deferred graphs.
- Reduce temporary row containers during JSON saving, retaining exact numeric
  encoding, the saved-file format, bounded batches and atomic writes.
- Compose MainWindow widgets and callbacks through their owning components,
  preserving Qt wiring and keeping internal driver ports for tests and automation.
  Document the driver API's scope and unchanged shrink-only guard; add regression
  coverage for workflows with those ports disabled.
- Strengthen UI regression checks after component extraction, isolate worker RAM
  and configuration fallbacks, and verify complete daily calendar boundaries.
- Continue retiring legacy window aliases onto existing state and UI components.
  Startup, smoke checks, benchmarks and tests use their existing owners directly;
  retire each exhausted adapter and lower the compatibility budget.
- Retire 79 unused or low-use legacy window aliases, moving state callers to their
  owning state APIs. Keep widely used UI/callback adapters for later migration;
  integrations using retired aliases need the state/controller or service APIs.
  Add a CI guard for the remaining alias names and compatibility-file line budget.
- Align development/release guidance with the current lint, typing and coverage
  gates; complete the module map and consolidate repeated workspace instructions.
- Enforce Ruff limits of 60 statements and 12 branches per function alongside
  the existing complexity limit of 10. Extract sidebar and Data recording-header
  construction into named helpers, preserving widget creation and signal order.
- Extend mypy checks to job, result, export and shell controllers, shared workspace
  state, result preparation, previews and export/file-writing services. Require
  complete function annotations in these nine additional modules.
- Add branch-coverage reports and an 80% floor for controllers and error
  boundaries in both Windows workflows. Add direct worker-boundary tests for
  terminal signals, traceback forwarding and logger cleanup.
- Enforce a 900-line limit for every Python module under `src/` in both Windows
  workflows. Extract Analyze page construction and result-summary preparation
  from the existing oversized modules, preserving their public view interfaces.
- Defer sensor-context table construction and column sizing while Graphs is
  selected. Opening Tables shows the latest window with every original sample;
  revisiting an unchanged table preserves its model and selection.
- Record a baseline/current performance review of the component extraction,
  including frozen startup, graph interactions, processing and saved runs.
  Add reproducible first-use and processing benchmarks with data checks.
- Replace window layout/graph mixins with composed components and frozen views.
  Move data, analysis, jobs, result workspace, exports and shell behavior into
  explicit controllers; preserve ordered Qt wiring and deferred graph creation.
- Refresh the security review for current worker, diagnostic and release boundaries,
  with new dependency/static scans and security regression evidence.
- Narrow expected file/timezone error handling and preserve full tracebacks at
  job, preview, export and pipeline boundaries, including recording workers.
- Reduce startup work by loading Matplotlib and constructing Data, Results and
  sensor-context graph workspaces on first use. Later visits reuse the same
  canvases and controls. Startup checks also guard this plotting boundary.
- Show the empty Data graph and recording prompt immediately on opening Graphs,
  matching the empty Results graph without loading data or analysis libraries.
- Update workflow benchmarks and selector-layout tests for all four graph views
  and visible table controls. Share duplicate test window fixtures and refresh
  the test coverage guide.

## 0.6.0a2 — 2026-10-15

Second preview of **ParaDigMa Studio**, including the latest processing,
loading and graph improvements since 0.6.0a1. Scientific processing continues
to use the official ParaDigMa 1.1.2 toolbox.

### Results and navigation

- Add **Day** graphs with calendar-day percentages and medians, requiring at
  least 1% valid data per metric (14 minutes 24 seconds). Add a **24-hour profile**
  averaging valid 30-minute summaries at each time of day, with equal daily
  weighting and the recording's original timezone.
- Make days recognizable with grouped time/date labels and continuous midnight
  separators. Detailed and 30-minute graphs share this time-axis layout; date
  labels adapt to the available width and zoom.
- Replace Results panning with a horizontal time scrollbar and trackpad scrolling.
  Select a time interval using a continuous shaded band across graphs and gaps;
  Zoom in/out buttons change the visible duration. Zoom stays inside the full
  range, and the scrollbar disappears when all time is visible. Data and
  sensor-context graphs retain their existing pan and zoom controls.
- Open each Results view fully zoomed out and keep Y axes in a fixed column.
  Adding or removing series preserves the current zoom. Percentage graphs use
  automatic Y scaling, with manual limits and Reset limits still available.
- Make interval selection and horizontal scrolling more responsive. Dense plots
  use temporary previews that preserve peaks and gaps; full detail returns when
  movement stops. Tables and exports retain the original values.
- Put filenames in a **Recordings** tab in Runs, followed by Parameters, Warnings,
  Errors, Processing log, Saved run and Exports.

### Processing and loading

- Process multiple recordings with up to two workers, within detected CPU and
  available-RAM limits. Single recordings still use one worker. Official pipeline
  steps and pooled aggregation remain unchanged; the log explains worker selection.
- Reduce raw-input loading overhead while preserving exact samples and statistics.
  Keep pandas, Arrow and the scientific stack deferred during startup and empty views.
- Keep Analyze's **Time origin** editable during clock refreshes. Module changes
  use lighter clock-only previews and reuse equivalent selections; pending previews
  cannot overwrite a user edit. Missing-sample checks avoid copying the full sensor matrix.
- Interpret `difference_s` and `difference_ms` correctly in Data graphs without
  changing the stored input values.

### Important TSDF correction

TSDF metadata `scale_factors` now apply once during import, consistently for
Data plots, sensor context and analysis. ParaDigMa 1.1.2's loader and preparation
do not apply this decoding. **If an earlier build analyzed TSDF recordings with
non-unit scale factors, rerun those analyses.** Existing saved results are not recalculated.

### Download and run

Download **ParaDigMaStudio-0.6.0a2-Windows-x64.zip**, extract the entire ZIP into
a new folder, and open `ParaDigMaStudio/ParaDigMaStudio.exe`. Keep `_internal`
and all accompanying files beside the executable. **Python does not need to be installed.**

The separate **ParaDigMaStudio-0.6.0a2-SHA256SUMS.txt** verifies the ZIP checksum.
The bundle contains per-file checksums, its source commit, package versions and
the dependency-audit report. Performance reports remain separate from the app download.

This Windows x64 preview is **unsigned**, like the first preview. Publisher
signing requires a verified signing identity; keep Windows protections enabled.
This release is for evaluation and feedback. Tests cover representative recordings;
consult the official methodology before research use.

[User guide](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v0.6.0a2/docs/USER_GUIDE.md)
· [Scientific checks](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v0.6.0a2/docs/SCIENTIFIC_TESTS.md)
· [Report an issue](https://github.com/biomarkersParkinson/ParaDigMa-Studio/issues)

## 0.6.0a1 — 2026-10-13

First public preview of **ParaDigMa Studio**, a Windows workspace around the
official ParaDigMa 1.1.2 toolbox, for evaluation and feedback.

### Included

- Data, Analyze, Results and Runs workspaces; inspect sensor channels and recording quality.
- Gait, tremor and pulse-rate analysis, including combinations of all three modules,
  multiple recordings of the same subject, and cancellation.
- Aggregate summaries and linked graphs/tables across recording time. Detailed
  tremor-power graphs use `log10(power + 1)`; 30-minute epochs use the median of
  transformed power. Raw scientific tables and data exports retain original values.
- Sensor-context inspection, local saved runs, configurable JSON/CSV exports,
  figure exports at 600 DPI, and run management.
- Scientific-equivalence tests against official ParaDigMa workflows, Windows
  executable smoke checks, dependency auditing and packaged build provenance.
- Apache 2.0 licensing, ParaDigMa acknowledgements and research citations.

### Download and run

Download **ParaDigMaStudio-0.6.0a1-Windows-x64.zip**, extract the entire ZIP,
and open `ParaDigMaStudio/ParaDigMaStudio.exe`. Keep `_internal` and all accompanying
files beside the executable. **Python does not need to be installed.**

The separate `ParaDigMaStudio-0.6.0a1-SHA256SUMS.txt` verifies the ZIP's checksum.
The bundle also contains per-file checksums, the source commit, package versions
and the dependency-audit report. Checksums are not publisher signatures.

### Preview limitations

- This Windows x64 build is **unsigned**. Smart App Control may block it;
  publisher signing requires a verified signing identity. Keep Windows protections enabled.
- The tests cover representative recordings and workflows; evaluate results with
  your own data and consult the official methodology before research use.
- No analysis methods are newly introduced by Studio. ParaDigMa remains the source
  of the scientific processing; graph transformations and epoch summaries are presentation views.

[Getting started](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v0.6.0a1/README.md)
· [User guide](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v0.6.0a1/docs/USER_GUIDE.md)
· [Scientific checks](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v0.6.0a1/docs/SCIENTIFIC_TESTS.md)
· [Report an issue](https://github.com/biomarkersParkinson/ParaDigMa-Studio/issues)

For research, cite ParaDigMa's [2026 JOSS paper](https://doi.org/10.21105/joss.09502)
and relevant pipeline publications, as listed in About and the bundled acknowledgements.
