# Changelog

## Unreleased

- Clarify the contributing workflow with structured bug reports, pull-request
  steps, change-specific validation links and documentation ownership, asset
  maintenance and check guidance.
- Group the test suite map by workflow with direct links to every test module,
  separate setup, shared helpers and assertion conventions, and bring the
  coverage-scope and report guidance into line with current configuration.
- Organize the scientific test guide around running checks, coverage, independent
  references, tolerances and presentation, distinguishing direct official
  comparisons from sequential/parallel consistency checks and clarifying fixtures
  and maintenance limits.
- Group the repository map by workflow and component ownership, add direct
  source/script links and current navigation/help/provenance modules, and
  separate change conventions from generated outputs and CI guidance.
- Structure the release guide around preparation, tag-triggered publication,
  artifact verification and recovery, clarifying prereleases, Git receipts and
  the separate signed-build workflow.
- Clarify the Python API and saved-run reference with an integration example,
  explicit processing defaults, separate execution/verification contracts and
  structured format, storage and provenance guidance.
- Organize the performance guide by workflow, cache/worker budgets and benchmark
  task, with reproducible commands, current hand-navigation coverage and clearer
  guidance for comparing startup, first-use and repeated-action timings.
- Organize the dependency guide by environment, pinning policy, installation,
  updates, auditing and release evidence, with clearer verification commands
  and links to development, security and attribution references.
- Embed rendered architecture diagrams for GitHub Mobile and other Markdown
  viewers, matching component labels to the ownership table and retaining
  editable Mermaid sources beside the images. Group the analysis sequence into
  start, processing and completion phases, showing live updates alongside
  processing and final results afterward.
- Explain the architecture through ownership and execution diagrams, data-flow
  boundaries, worker lifecycles and result persistence, with links to the code.
- Organize the development guide around setup, testing and packaging, with
  consistent locked uv commands, clearer quality/typing policies and troubleshooting.
- Separate release-matched and current-source guides, streamline documentation
  ownership, archive dated verification evidence, and add contribution/security
  reporting guidance and standard Markdown/local-link checks.

- Strengthen checks for clock alignment and Analyze help, consolidate overlapping
  UI tests, and clarify cases involving missing metadata or refreshed column lists.
- Add a hand tool to drag time horizontally in raw sensor graphs and all Results
  graph views, preserving the visible duration, linked axes, automatic/manual Y
  scales, selected timepoint and navigation history within the source bounds.
- Make the existing thin blue analysis bar fill as processing milestones finish,
  including sequential and parallel batches, without adding percentage or stage
  labels. Preserve cancellation, current status text and the busy indicator for
  other background operations.
- Remove the duplicate vertical scrollbar in compact Results graph views. Scroll
  the plots in one viewport while keeping the toolbar, time axis and footer fixed.
- Give Data and Results sensor-context graphs the same time-interval selection,
  zoom buttons and horizontal scrollbar as Results graphs. Automatically fit Y
  limits to visible original samples while preserving manual limits, channel-change
  zoom and the original sensor-context Home view.
- Show the same translucent blue interval-selection band across raw-data graphs
  and their gaps as in Results graphs.
- Keep raw sensor graph zoom when channels are added or removed, including manual
  vertical limits for sensor groups that remain visible. Keep Home and view history usable.
- Open Analyze field explanations in separate, scrollable help windows with
  Close/Escape support. Keep the parameter layout fixed, preserve current-value
  source details and the input-orientation figure, and show one explanation at a time.
- Display Data graphs with recording dates and times for absolute timestamps, or
  elapsed seconds for relative timestamps and time increments. Reuse the Results
  sensor-graph date formatting, including in axis limits and graph exports, while
  retaining original timestamps in Tables and analysis inputs.
- Restore Alt+1, Alt+2, Alt+3 and Alt+4 navigation after the sidebar changes its
  labels. Shortcuts now remain available at startup and when expanding or
  collapsing the sidebar, including while a page control has keyboard focus.

## 1.0.0rc1 — 2026-10-26

First release candidate for **ParaDigMa Studio 1.0**, following the 0.6 alpha
previews. Scientific processing uses **official ParaDigMa 1.1.2**. This candidate
is intended for evaluation and feedback before the stable release.

### Recording configuration

- Put Signal columns on the left of Analyze and source-recording parameters on
  the right, stacking the sections in narrow windows. Keep controls reachable
  under native Windows styles and when help or warnings change the layout.
- Automatically match available signal columns. Mark detected selections and
  supported metadata-derived units with **From file**; **Default** restores
  detected settings. One Default button restores the entire signal table while
  retaining axis inversions. Manual selections alone determine analysis inputs;
  **Not included** leaves a signal unassigned, including optional Green PPG.
- Share the selected time column and format between Data and Analyze. Changes
  update sampling diagnostics, original-signal graphs and time-origin previews.
  Use the selected time column or declared recording-start metadata for origins;
  unrelated date columns no longer supply recording dates.
- Reset Analyze when new files load successfully, including manual edits, and
  prefill settings from the new input. Keep batch settings when switching the
  recording being inspected. Disable sensor-unit fields when that sensor has
  no mapped source columns.
- Prepare selected columns, units and axes automatically, removing the
  **Already prepared** option. Enable missing-sample exclusion and gap splitting
  initially, with restorable gap and section-duration thresholds.
- Support axis swaps through column selections and independent accelerometer and
  gyroscope inversions. Show the reviewed left/right input-orientation figure
  and explain that ParaDigMa applies wrist-side adjustments during processing.
- Keep optional signals and compatibility details expandable, summarize repeated
  batch issues, and explain warnings without warning sounds. Wheel gestures over
  closed fields scroll the surrounding page without changing their values.

### Results and responsiveness

- Accept raw PPG-only recordings for pulse-rate analysis. Optional accelerometer
  channels retain unit conversion and missing-sample checks when supplied.
- Show pulse-rate estimate availability against complete 2-second epochs across
  the full recording timespan. Draw estimates at their official 2-second cadence
  and PPG-quality outputs at 1 second, preserving missing-output gaps.
- Restore original-sample detail when zooming Data and sensor-context graphs;
  wide views retain peaks and missing-data breaks. Keep statistics and saved-run
  reopening responsive through bounded background work and deferred graphs.

### Saved runs and exports

- Capture Studio and official ParaDigMa versions when analysis starts, plus the
  Studio build commit when available. Preserve this identity through saving,
  reopening and JSON/ZIP exports, and show it in Runs.
- Include analysis provenance and the CSV checksum in a `.csv.metadata.json`
  companion for standalone CSV exports. Keep each CSV and its companion together.
- Verify saved-result ownership and exact-byte checksums before reopening.
  Saved history and result JSON require **Studio format version 2**. Earlier
  formats and the former ParaDigMaDesktop history location are unsupported;
  re-analyze original recordings to create current runs.

### Documentation and build verification

- Organize the illustrated user guide around Data, Analyze, Results and Runs,
  with current configuration, time, preparation, saving and export guidance.
- Use one native `uv.lock`, standard uv lock/sync/check commands and pip-audit
  environment collection. Preserve reviewed scientific versions and the pinned
  Open Movement reader. Require matching audit, source and dependency evidence
  before release packaging; retain the documented Python-binding PyArrow exception.
- Extend typing and regression coverage and enforce lint, formatting, module-size,
  facade, full-suite coverage, scientific-equivalence and packaged-app checks.

The portable Windows x64 candidate is **unsigned**. Extract the complete ZIP into
a fresh folder and keep `_internal`, notices and security/checksum files beside
the executable. Use uniformly formatted recordings within each batch and review
source units, time, watch side and axes before running. See
[candidate validation and limitations](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v1.0.0rc1/docs/RELEASE_CANDIDATE.md),
[Security](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v1.0.0rc1/SECURITY.md)
and [signing](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v1.0.0rc1/SIGNING.md).

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
