# Changelog

## Unreleased

- Make Analyze's gap/duration step buttons wider with clear scalable chevrons,
  and display acceleration units as m/s² while preserving saved and pipeline
  unit identifiers.

- Correct Detailed pulse-rate estimate bars to use the official 2-second update
  cadence, while keeping PPG quality bars at 1 second. Preserve missing-output
  gaps, recording boundaries and original result values, including saved results.
  Count each returned estimate's 2 seconds when checking Day-view data availability.

- Integrate axis direction into Signal columns with independent accelerometer and
  gyroscope inversion checkboxes; select axis swaps through the source dropdowns.
  Put other Analyze parameters on the left and signal columns on the right,
  stacking in narrow windows. Replace row statuses with inline warning icons and
  preserve the transformations from older saved global axis settings.

- Replace the Analyze column-mapping JSON field with signal dropdowns, exact-name
  recognition, unambiguous auto-match suggestions and validation across every
  loaded recording. Preserve choices across module/recording switches and restore
  saved mappings in their existing format; optional signals and file details can
  be expanded without scanning source samples.

- Replace the Pulse rate overview count with **Pulse-rate estimate availability (%)**,
  based on complete 2-second epochs in the full recording timespan. Show the
  measures directly under Pulse rate and use clearer pulse-rate plot labels;
  original metadata, tables and exports remain unchanged.

- Accept raw PPG-only recordings for pulse-rate analysis without requiring
  accelerometer channels. Preserve time conversion, missing-sample checks and
  official analytical steps; align the input guidance and clock previews.

- Restore source-rate detail when zooming into raw Data graphs and sensor
  context. Replace fixed recording-wide sample skipping with visible-range
  rendering that retains peaks, missing-data breaks and original export samples.

- Speed up initial statistics for multiple long recordings with at most two
  background threads when CPU and available RAM permit. Preserve exact
  statistics, loaded samples and completion before displaying recordings.

- Keep saved-run reopening responsive: prepare result views in the worker,
  isolate large JSON decoding in an owned process, and defer hidden Results
  graphs until Graphs is opened. Preserve saved formats, values and source inputs.

## 0.6.0a3 — 2026-10-18

Third preview of **ParaDigMa Studio**, focused on responsiveness, maintainability
and regression coverage. Scientific processing continues to use the official
ParaDigMa 1.1.2 toolbox; original output values and export formats are preserved.

### Data and results

- Share the Data time format across all loaded recordings. Switching files keeps
  the selected format for graphs and statistics; cached background previews avoid
  scanning every recording when the format changes. Analyze keeps its own settings.
- Defer graph initialization until first use and show the empty Data graph
  immediately. Reuse workspaces on later visits, preserving fast startup and
  keeping plotting and scientific imports out of empty non-graph pages.
- Make Results selection and horizontal scrolling more responsive by reusing
  surviving plots, bounded original geometry, exact time coordinates and compatible
  layouts. Paint visible graphs and coalesce repeated graph/ruler paints.
- Keep dense gait bars equally visible during and after scrolling. Peaks, signed
  values, gaps and long intervals remain visible; zooming resolves individual
  outputs and figure exports retain the original geometry.
- Draw the selected-time dotted line continuously across Results graphs and gaps.
  Keep axis-limit fields synchronized with zoom and navigation, displaying at most
  three decimal places without rounding the underlying unedited limits.
- Skip hidden sensor-context table updates until Tables is opened. Speed up JSON
  saving by reducing temporary row containers, retaining exact numeric encoding,
  bounded batches, source protection and atomic replacement.

### Maintenance and verification

- Replace window mixins with composed UI and workflow controllers, explicit
  dependencies and frozen views. Keep MainWindow focused on composition and Qt
  wiring, preserving job lifetimes, signal order and cancellation.
- Separate the internal test/probe driver API from production composition and
  remove unused adapters while retaining the shrink-only guard.
- Extend mypy to key controllers, services and the entire UI package. Enforce
  module-size, function complexity, statement and branch limits in CI, plus an
  80% branch-coverage floor for controllers and error boundaries.
- Strengthen scientific, rendering, source-integrity, worker-policy and failure
  regressions; streamline redundant test setup. Expand first-graph and interaction
  benchmarks, with reports kept outside the portable application download.
- Refresh the user/developer documentation and security review, including current
  dependency/static scans and source, workflow and packaged-app verification.

The portable Windows preview remains unsigned. Keep the complete extracted folder
and use the supplied SHA-256 inventory to check its contents. See
[Security](SECURITY.md), [signing](SIGNING.md) and the [user guide](docs/USER_GUIDE.md).

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
