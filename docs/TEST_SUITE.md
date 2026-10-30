# Test suite organization

The suite protects scientific values, supported file formats, user workflows,
responsiveness and packaging. Tests are grouped by application responsibility;
a fixed historical bug remains a useful regression when its trigger and expected
behavior still apply.

This guide describes `main`. Use [Development](DEVELOPMENT.md) for setup, static
checks and packaging, and [Scientific tests](SCIENTIFIC_TESTS.md) for independent
ParaDigMa references, fixtures, numerical tolerances and their limits.

- [Run and select tests](#test-setup-and-scientific-checks)
- [Regression coverage map](#regression-coverage-map)
- [Shared fixtures and interactions](#shared-fixtures-and-interactions)
- [Test-writing conventions](#test-writing-conventions)
- [Branch coverage](#branch-coverage)
- [Maintaining the suite](#maintaining-the-suite)

## Test setup and scientific checks

### Run and select tests

Run from the repository root after following the
[environment setup](DEVELOPMENT.md#set-up-the-environment):

```sh
uv sync --locked --all-groups
```

Choose the smallest relevant run while developing. These commands work in
PowerShell and Bash:

| Task | Command |
| --- | --- |
| One feature module | `uv run --locked --all-groups python -m pytest -q tests/test_analysis_settings.py` |
| Tests matching a name | `uv run --locked --all-groups python -m pytest -q tests/test_workspace.py -k page_shortcuts` |
| Marked scientific comparisons | `uv run --locked --all-groups python -m pytest -m scientific -q` |
| Inspect current test collection | `uv run --locked --all-groups python -m pytest --collect-only -q` |

The full suite includes the marked scientific comparisons and related
presentation, validation and lifecycle cases. Before submitting code changes,
use the [complete development checks](DEVELOPMENT.md#run-development-checks),
including the full suite with branch coverage. Documentation-only changes use
the [Markdown and local-link checks](../CONTRIBUTING.md#documentation-checks).

### Headless Qt and native platform checks

[conftest.py](../tests/conftest.py) selects an offscreen 1920×1080 virtual screen
using [qt-offscreen.json](../tests/data/qt-offscreen.json) when no other Qt
platform is selected. Qt's default 800×800 screen is smaller than the app's
minimum width and can clip Windows visibility checks.

For an explicit headless Linux run with a writable Matplotlib cache:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/paradigma-mpl uv run --locked --all-groups python -m pytest -q tests/test_analysis_settings.py
```

Graph-workspace tests use the shipped Fusion style. Native layout cases also
exercise Windows styles and larger control/font hints. The Linux font-fallback
subprocess supplements those cases; native Windows layout, shortcuts and
Authenticode checks remain responsibilities of Windows execution. Linux checks
do not replace them.

### CI and packaged checks

Both [Windows](../.github/workflows/windows.yml) and
[signed Windows](../.github/workflows/windows-signed.yml) workflows verify the
environment and static checks, run the early Analyze-layout and page-shortcut
regressions, then run the full suite with coverage before packaging.

The [packaged executable check](DEVELOPMENT.md#build-and-verify-a-windows-executable)
is a separate step: it loads bundled classifiers, runs real pipelines and spawned
workers, renders graphs, saves results and reopens exports. Source tests,
scientific comparisons and the executable probe check different boundaries.

## Regression coverage map

Use these groups to find the owning tests. Some modules span more than one
boundary. The [scientific guide's coverage map](SCIENTIFIC_TESTS.md#coverage-map)
identifies exactly which groups the `scientific` marker selects.

### Importing and inspecting recordings

| Responsibility | Test modules |
| --- | --- |
| Loading, validation, unit/time preparation and missing-sample exclusion | [test_core.py](../tests/test_core.py), [test_preparation.py](../tests/test_preparation.py), [test_missing_samples.py](../tests/test_missing_samples.py) |
| Real CWA/Avro imports, fractional timestamps, TSDF physical scaling, metadata and source integrity | [test_cwa.py](../tests/test_cwa.py), [test_empatica.py](../tests/test_empatica.py), [test_tsdf_input.py](../tests/test_tsdf_input.py) |
| Exact statistics, nullable/non-sensor columns, bounded batch concurrency, resource fallbacks and background previews | [test_inspection.py](../tests/test_inspection.py), [test_previews.py](../tests/test_previews.py) |
| Multiple recordings, identifiers, original-file inspection, per-file clocks and shared settings | [test_recordings.py](../tests/test_recordings.py) |
| Shared Data/Analyze time choices, sampling diagnostics, selected-channel exclusion and calendar/elapsed graph values | [test_shared_time_configuration.py](../tests/test_shared_time_configuration.py), [test_input_time_plot.py](../tests/test_input_time_plot.py) |
| Selected-column clock authority, precise device start metadata, pending/manual origins and clock-only previews | [test_recording_clock.py](../tests/test_recording_clock.py), [test_origin_preview.py](../tests/test_origin_preview.py) |
| PPG-only preparation, numeric time encodings, official pulse stages and required-value/IMU checks | [test_pulse_input.py](../tests/test_pulse_input.py) |

### Configuring and running Analyze

| Responsibility | Test modules |
| --- | --- |
| Defaults, file-derived units/origins, manual overrides, new-input resets and complete settings preservation across help | [test_analysis_settings.py](../tests/test_analysis_settings.py), [test_input_metadata.py](../tests/test_input_metadata.py), [test_analysis_input_reset.py](../tests/test_analysis_input_reset.py) |
| Column choices, ambiguity, header-only batch validation, explicit absence, per-sensor inversion and saved selections | [test_column_mapping.py](../tests/test_column_mapping.py), [test_signal_selection.py](../tests/test_signal_selection.py), [test_axis_mapping.py](../tests/test_axis_mapping.py) |
| Declared input preparation once, unchanged native-unit samples, gap/duration policies and retired-setting rejection | [test_analysis_preparation.py](../tests/test_analysis_preparation.py) |
| Dependency-specific refreshes and complete settings installed before previews/Data notifications | [test_analysis_refresh.py](../tests/test_analysis_refresh.py) |
| Compact layout, native sizing, fixed fields while help opens and full-control visibility | [test_analysis_layout.py](../tests/test_analysis_layout.py), [test_analysis_help_stability.py](../tests/test_analysis_help_stability.py) |
| Reusable scrollable help windows, current value sources, one explanation at a time and keyboard/mouse closing | [test_analysis_help_dialog.py](../tests/test_analysis_help_dialog.py) |
| Wheel/trackpad page scrolling without changing focused editors or closed dropdowns | [test_analysis_scrolling.py](../tests/test_analysis_scrolling.py) |
| Quiet visual progress, weighted batches/sections, coalesced updates, stale events and cancellation/failure | [test_analysis_progress.py](../tests/test_analysis_progress.py) |
| Official pipeline stages, retained outputs and real spawned-worker equivalence | [test_scientific_equivalence.py](../tests/test_scientific_equivalence.py), [test_parallel_scientific.py](../tests/test_parallel_scientific.py) |
| Process ownership, reuse, CPU/RAM policy, affinity, transfers and cancellation | [test_parallel_execution.py](../tests/test_parallel_execution.py) |

### Raw graphs and shared time controls

| Responsibility | Test modules |
| --- | --- |
| Source-rate detail, isolated peaks/gaps, visible extrema, bounded caches and original exports | [test_raw_signal_detail.py](../tests/test_raw_signal_detail.py) |
| Channel changes preserve time/manual Y limits; Clear/reselection, new-channel scales and clock/recording resets | [test_raw_channel_zoom.py](../tests/test_raw_channel_zoom.py) |
| Interval selection, blue preview, visible-sample Y limits, scrollbar history and full-source Automatic X | [test_raw_navigation.py](../tests/test_raw_navigation.py) |
| Zoom buttons, source bounds, elapsed/calendar coordinates, manual Y scales, Home/history and empty contexts | [test_raw_zoom_buttons.py](../tests/test_raw_zoom_buttons.py) |
| Hand dragging across raw and all four Results views, stable duration/timepoint/Y scale, capture and one-step history | [test_hand_navigation.py](../tests/test_hand_navigation.py) |
| Sensor groups, original values/timing, indexed sensor-context opening and stable channel windows | [test_raw_modalities.py](../tests/test_raw_modalities.py), [test_sensor_context_workspace.py](../tests/test_sensor_context_workspace.py) |

### Results, tables and summaries

| Responsibility | Test modules |
| --- | --- |
| Prepared-input coverage, stable selected outcomes and readable recording extents | [test_availability.py](../tests/test_availability.py), [test_availability_plot_stability.py](../tests/test_availability_plot_stability.py), [test_recording_overview.py](../tests/test_recording_overview.py) |
| Overview, original table selection, timing, provenance and table-model values | [test_results_view.py](../tests/test_results_view.py), [test_table_models.py](../tests/test_table_models.py) |
| Official gait aggregates, observed-time gait percentages and filtered-gait subset rules | [test_gait_overview.py](../tests/test_gait_overview.py), [test_gait_presence.py](../tests/test_gait_presence.py) |
| Epoch medians/percentages, metric-specific presence gates and daily coverage/calendars | [test_epochs.py](../tests/test_epochs.py), [test_epoch_presence_threshold.py](../tests/test_epoch_presence_threshold.py), [test_daily.py](../tests/test_daily.py) |
| Mean 24-hour profiles, equal daily weighting, local clock slots, missingness and presence gates | [test_epoch_profile.py](../tests/test_epoch_profile.py) |
| Pulse availability across the full recording, compact overview, labels and reopening | [test_pulse_availability.py](../tests/test_pulse_availability.py) |

### Result graph layout and rendering

| Responsibility | Test modules |
| --- | --- |
| Measured values, headings, categorical rasters, clock alignment and visible series navigation | [test_result_charts.py](../tests/test_result_charts.py), [test_graph_workspace.py](../tests/test_graph_workspace.py), [test_graph_selector_layout.py](../tests/test_graph_selector_layout.py) |
| Cursor modes, linked axis limits, time scrolling, zoom, history and Home | [test_plot_controls.py](../tests/test_plot_controls.py), [test_result_navigation.py](../tests/test_result_navigation.py) |
| Readable date/time ticks, calendar boundaries and one linked selection line through graph gaps | [test_time_axis.py](../tests/test_time_axis.py), [test_day_axis.py](../tests/test_day_axis.py), [test_epoch_axis.py](../tests/test_epoch_axis.py), [test_selection_lines.py](../tests/test_selection_lines.py) |
| One compact plot scrollbar, pinned controls, independent series scrolling and native mouse/trackpad input | [test_results_scrolling.py](../tests/test_results_scrolling.py) |
| Automatic percentage scaling, shared Y-axis alignment and native-layout comparisons in every view | [test_percentage_scaling.py](../tests/test_percentage_scaling.py), [test_result_layout.py](../tests/test_result_layout.py) |
| Plot/layout reuse, redraw counts, dense-bar pixels, exact shared coordinates, cache eviction and discarded-result cleanup | [test_graph_performance.py](../tests/test_graph_performance.py), [test_navigation_performance.py](../tests/test_navigation_performance.py), [test_result_plot_cache.py](../tests/test_result_plot_cache.py), [test_result_coordinates.py](../tests/test_result_coordinates.py) |

### Saving, reopening and exporting

| Responsibility | Test modules |
| --- | --- |
| Export selection, numeric/JSON precision, bounded batches, protected sources, atomic failures and background completion | [test_result_exports.py](../tests/test_result_exports.py) |
| Analysis-time software/build identity, JSON/ZIP/CSV metadata, checksum companions and safe deletion | [test_run_provenance.py](../tests/test_run_provenance.py) |
| Complete local snapshots, responsive reopening, isolated-reader cleanup, exact restored values and unsaved-close/bulk-save behavior | [test_saved_results.py](../tests/test_saved_results.py) |
| Run history, cancellation, owned-output deletion and native multi-selection | [test_run_management.py](../tests/test_run_management.py), [test_bulk_runs.py](../tests/test_bulk_runs.py) |
| Exact-byte checksums and run ownership, rejected edits/replacements, failure-state preservation and snapshot/history consistency | [test_result_integrity.py](../tests/test_result_integrity.py) |
| Versioned history/results, required fields, rejection without migration and explicit export completeness | [test_saved_format.py](../tests/test_saved_format.py) |

### Composition, contracts and error boundaries

| Responsibility | Test modules |
| --- | --- |
| Window integration, loaded bar/table/export behavior, shared settings, page shortcuts and recovery | [test_app.py](../tests/test_app.py), [test_workspace.py](../tests/test_workspace.py) |
| Components with declared dependencies, partial results, clock fallback and interrupted deletion | [test_workspace_components.py](../tests/test_workspace_components.py) |
| Data/Results page construction, action order, deferred graph callbacks and resizing | [test_data_page.py](../tests/test_data_page.py), [test_results_page.py](../tests/test_results_page.py) |
| Frozen view ports, callbacks connected before worker start, snapshots, terminal cleanup and coordinator size | [test_composition_order.py](../tests/test_composition_order.py) |
| Application workflows with the internal driver disabled | [test_composition_without_facade.py](../tests/test_composition_without_facade.py) |
| Typed lazy adapters, pinned upstream signatures/defaults and object-preserving forwarding | [test_paradigma_api.py](../tests/test_paradigma_api.py); static examples in [preparation_contracts.py](../tests/typing/preparation_contracts.py) |
| Specific input errors, complete worker/UI tracebacks, failed startup/smoke status and unchanged failure counts | [test_error_handling.py](../tests/test_error_handling.py) |

### Build, security and source guards

| Responsibility | Test modules |
| --- | --- |
| Deferred imports, first-use graphs and packaged startup/analysis probes | [test_startup.py](../tests/test_startup.py), [test_smoke.py](../tests/test_smoke.py) |
| Runtime assets, clean bundle layout, YAML benchmark/upload contracts and upstream attribution | [test_packaging.py](../tests/test_packaging.py), [test_acknowledgements.py](../tests/test_acknowledgements.py) |
| Unsafe loading, protected exports and diagnostic writes | [test_security.py](../tests/test_security.py) |
| Native uv gates, target dependency graphs, audit/environment agreement, scoped exceptions and CI ordering | [test_dependency_evidence.py](../tests/test_dependency_evidence.py) |
| Release versions, source/package inventory, checksums, complete artifacts and verified publication | [test_release.py](../tests/test_release.py) |
| Signature policy, publisher/timestamp validation and native Windows inspection | [test_signing.py](../tests/test_signing.py) |
| Studio identity, launcher and exclusive storage paths | [test_branding.py](../tests/test_branding.py) |
| Source-module physical-line limit | [test_module_size.py](../tests/test_module_size.py); [check_module_size.py](../scripts/check_module_size.py) |
| Shrink-only internal driver ports/line budget and retired-name protection | [test_workspace_facade.py](../tests/test_workspace_facade.py); [check_workspace_facade.py](../scripts/check_workspace_facade.py) |

## Shared fixtures and interactions

Prefer the existing helpers when they fit the scenario. Keep specialized window
fixtures for native sizes, dark palettes, styles or background-job lifecycles.

| Location | Fixtures and helpers |
| --- | --- |
| [conftest.py](../tests/conftest.py) | Fresh `synthetic_imu` and `tremor_outputs`; visible `window` with temporary history; independent binary `tsdf_writer`; `wait_for_previews`, `wait_for_job`, bar measurements and `select_plot_metric` |
| [analysis_helpers.py](../tests/analysis_helpers.py) | Native Analyze sizing and full-control visibility assertions |
| [run_fixtures.py](../tests/run_fixtures.py) | Complete current `saved_settings`, `make_run` and checksum-backed `export_receipt` helpers |
| [ui/compatibility.py](../src/paradigma_studio/ui/compatibility.py) | Internal workspace driver shared by UI tests, startup/smoke probes and benchmarks |

The synthetic data/output fixtures remain function-scoped because tests modify
samples to exercise validation and missing-data behavior. The shared window
processes its initial Qt events before yielding and waits for background jobs
before closing. Global teardown releases closed windows and Qt deferred deletes;
close-warning tests supply their own responses rather than relying on the normal
test discard response.

`select_plot_metric` drives the visible Plot series tree and normal signals;
metric-change tests should not drive a hidden legacy selector. Dataset-row
resets use `activate_dataset_rows`. Test names distinguish plot zoom, row
selection and sensor context from scientific filtered-gait processing.

For isolated assertions, use the owning state/controller. For UI integration,
drive widgets and signals, using the internal driver where useful. Application
code uses explicit component owners and works without driver ports. These ports
follow implementation details and carry the
[shrink-only policy](DEVELOPMENT.md#internal-workspace-driver).

Public recording provenance and licences remain in the
[bundled-data notes](../src/paradigma_studio/data/README.txt) and
[official fixture README](../tests/data/paradigma/README.md). Tests require no
private recording or external fixture download.

## Test-writing conventions

### Match the assertion to the boundary

An export unit test checks unusual numeric values, an independent scientific
comparison checks real official outputs, and a packaged probe checks frozen
imports and classifier assets. These layers are complementary when they protect
different failure modes. Use the coverage map to extend the owning scenario
rather than repeating the same setup and assertions elsewhere.

Check observable behavior and the complete relevant output. Boundary tests can
capture or fail a dependency deliberately; real scientific comparisons must
execute the processing stages. The [scientific guide](SCIENTIFIC_TESTS.md)
defines their independent references and numerical rules.

### Numeric values and source integrity

Use **zero relative tolerance** with an explicit absolute tolerance for calendar
coordinates, normally `1e-10` days (about 8.64 microseconds). Relative tolerances
on dates since the epoch can silently allow minute-scale errors. Mouse-drag
checks retain their explicit pixel/window-derived tolerance. Scientific-value
tolerances are separate.

Compare complete expected calendar ranges, not prefixes. Loading tests retain
exact TSDF values/dtypes, signed-zero/float bit patterns, unchanged source files
and shared arrays. Inspection checks retain exact quantiles and complete missing
counts, including nullable, non-sensor and time columns.

### Qt interaction, layout and lifecycle

- Deliver the queued paints/layout events needed by the scenario before recording
  baseline geometry. Compact pinned-control tests complete the source paint first;
  a fixed short delay can leave native footer hints pending. Keep exact geometry,
  full visibility and single-scrollbar assertions.
- Compare relative layout positions when those express the contract, such as
  metadata labels below and left-aligned with parameter names. Preserve the native
  style, control-height, compact-size and font-fallback cases.
- Help interaction belongs in dialog tests; settings preservation uses loaded,
  non-default settings and automatic/manual origins. Inspect actual widget trees,
  including hidden children, when proving that retired controls are absent.
- Check required callbacks before worker start and meaningful terminal/cleanup
  order. Independent signal-registration order is unrestricted. Clear fake
  workers in `finally` so a failed assertion cannot leave teardown waiting.
- Establish that two workers are otherwise possible before testing a resource or
  configuration fallback. Keep real process ownership/cancellation tests alongside
  isolated policy tests.

### Rendering and navigation

Keep elapsed/calendar coordinates, all four graph views, scroll positions and
device-pixel ratios in the relevant matrices. Navigation tests create the
eight-graph workspace only for shared/offscreen-axis scenarios; dense single-graph
cases start from an empty window. Setup processes queued paints and draws only
if the figure is still stale. Assertion-specific draws and events stay explicit.

Rendering checks compare visible pixels with a complete native render at both
display scales, after horizontal release and at successive vertical positions.
Reference draws restore the partial image afterward so they cannot hide missing
viewport updates. Retain marker changes, unchanged-row reuse, invalidation,
drawing failures and complete exports.

Dense Detailed gait checks compare moving and stopped range-of-motion/peak-velocity
pixels with segment metadata, scrollbar/trackpad controls and both pixel ratios.
Independent assertions retain gaps, signed peaks, long intervals, original paths
when zoomed and all original visible bars in exports.

Selection and cache checks preserve original values/paths, settings and navigation
when a shared-axis owner is removed. They also check bounded caches, eviction,
context invalidation and collection of detached axes/arrays. Rapid series changes
keep immediate signal delivery while sharing the final graph/ruler paint.
Runtime cache budgets belong in [Performance](PERFORMANCE.md#cache-and-worker-budgets).

Axis-limit fields follow zoom, hand dragging, scrolling, history, Home and silent
linked-limit changes. Display precision is at most three decimals; unedited
bounds and user-entered values retain full precision. Keep pending edits on
unchanged redraws. The time marker must match one native dashed stroke across
plots/gaps, with value points above it, including resize/pan and 600-DPI export.
Date-transition cases include hidden first dates, partial-day zoom, complete
boundaries and non-overlapping labels.

### Files, failures and workflow contracts

Failure tests deliberately raise unexpected exceptions, preserve original
tracebacks and require a failed probe exit status. Bulk-save cases fail the
first or second save, reopen the successful snapshot with exact values, and keep
the failed run unsaved with the window open.

Workflow tests parse YAML and check semantic command arguments and artifact
contracts. Preserve benchmark scripts, first-creation mode, report destinations,
bundle paths and hidden runtime libraries while allowing YAML reformatting and
additional benchmarks. Benchmarks drive visible series and module/output table
selectors, with Tables open when measuring table changes.

Performance regressions check retained values, cache reuse, redraw counts and
event-loop responsiveness. Hardware timing comparisons belong in the
[benchmark scripts](PERFORMANCE.md#reproduce-measurements), not strict CI timing limits.

## Branch coverage

### Gate and measured scope

Both Windows workflows run the full suite with the pinned `pytest-cov` and
coverage.py tools. The required **80%** is coverage.py's combined percentage of
executed statements and branch outcomes. It is not a whole-app coverage claim.

[`pyproject.toml`](../pyproject.toml) owns branch mode, measured source patterns,
the floor and report paths. Its current scope is:

| Group | Included modules |
| --- | --- |
| Controllers | Every `*_controller.py` under `src/paradigma_studio/`, including new or untested controllers |
| Processing and jobs | `analysis_process`, `analysis_progress`, `core`, `jobs`, `parallel_analysis`, `previews`, `recording_results` |
| Input and rendering boundaries | `axis_mapping`, `column_mapping`, `input_metadata`, `raw_signals` |
| Result preparation and persistence | `result_preparation`, `result_reopening`, `result_integrity`, `provenance`, `saved_format`, `storage` |

Other Studio modules and the upstream toolbox are outside this reporting scope.
Static lint, size and [typing checks](DEVELOPMENT.md#type-checking) complement
runtime tests; they do not replace them.

### Commands and reports

Use the [Windows/Linux full-suite commands](DEVELOPMENT.md#before-submitting),
which include the same coverage flags as CI. Plain focused pytest runs keep
coverage off. For a partial local measurement:

```sh
uv run --locked --all-groups python -m pytest -q tests/test_analysis_settings.py --cov --cov-fail-under=0
```

That override is for inspecting an incomplete local run; the full CI gate keeps
the configured floor. Add behavior tests for missing error/recovery branches
rather than excluding them or lowering the gate. Coverage timings are not
performance benchmarks.

| Output | Location |
| --- | --- |
| Full-suite JUnit | `test-results.xml` |
| Early Analyze-layout JUnit | `test-reports/analyze-layout.xml` |
| Early shortcut JUnit | `test-reports/navigation-shortcuts.xml` |
| Coverage XML | `test-reports/coverage.xml` |
| Browsable coverage HTML | `test-reports/coverage-html/index.html` |
| CI test artifact | `ParaDigMaStudio-test-results` |

CI uploads available JUnit/coverage reports even when an earlier test step fails.
Reports stay outside the portable app; raw `.coverage*` data and generated reports
are ignored by Git.

### Worker coverage limitations

Coverage combines completed Python subprocesses and multiprocessing workers.
Forcibly terminated workers can exit before saving measurements. Direct boundary
tests complement real process/thread integration tests, and Qt worker entry
points are also exercised synchronously to trace failure/cleanup paths.

In particular, `recording_results` coverage can undercount merges in terminated
workers. Real-process scientific comparisons still exercise that behavior;
inspect the relevant tests as well as the percentage when judging a gap.

## Maintaining the suite

Keep the coverage map aligned with current responsibilities and links. Preserve
distinct scientific, format/rejection, real-worker and native-display cases when
consolidating shared setup. A removed UI or compatibility path may justify
retiring its tests; the age of a regression alone does not.

The [archived cleanup record](archive/test-suite-cleanup.md) retains earlier
consolidation decisions, mutation probes and validation counts. Its latest probes
checked that clock shifts and help-triggered origin changes were rejected.

Current counts and coverage come from pytest collection and reports for the
tested commit. Report that commit, relevant checks and platform limitations;
keep dated measurements separate from the current policy.
