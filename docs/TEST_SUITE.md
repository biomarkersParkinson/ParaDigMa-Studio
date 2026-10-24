# Test suite organization

The suite is organized around current application responsibilities. Tests protect
scientific values, supported file formats, user workflows, responsiveness and
packaging. A fixed historical bug remains a useful regression test when its
trigger and expected behavior still apply.

## Regression coverage map

| Responsibility | Test modules |
| --- | --- |
| Source-module 900-line limit and boundary cases | `test_module_size.py`; CI entry point `scripts/check_module_size.py` |
| Internal driver port budget, physical-line limit and retired-name protection | `test_workspace_facade.py`; CI entry point `scripts/check_workspace_facade.py` |
| Independent official ParaDigMa comparisons | `test_scientific_equivalence.py` |
| Loading, validation and preparation | `test_core.py`, `test_preparation.py`, `test_missing_samples.py`, `test_cwa.py`, `test_empatica.py`, `test_tsdf_input.py` |
| Multiple recordings, source clocks and identifiers | `test_recordings.py` |
| Spawned recording workers, CPU/RAM policy, CPU affinity, cancellation and official batch equivalence | `test_parallel_execution.py`, `test_parallel_scientific.py` |
| Exact Data-page statistics, bounded batch concurrency, CPU/RAM fallbacks, recording order, worker cleanup and recording previews | `test_inspection.py`, `test_previews.py` |
| Shared Data time formats, cached multi-recording statistics, cumulative differences and unchanged source samples | `test_input_time_plot.py` |
| Raw PPG-only preparation, official pulse equivalence across numeric time formats, required-value checks and source-clock alignment | `test_pulse_input.py` |
| Pulse estimate availability over the full recording timespan, compact overview, readable plot labels and saved-result reopening | `test_pulse_availability.py` |
| Raw source-rate zoom detail, isolated peaks, gaps, original exports, bounded caches, renderer failures and Home | `test_raw_signal_detail.py` |
| Clock-only previews, module requirements, time formats and editable pending origins | `test_origin_preview.py`, `test_previews.py` |
| Selected-column clock authority, ignored unrelated dates across generic formats, precise device start metadata, origin defaults and shared preview/result alignment | `test_recording_clock.py` |
| Analysis settings, defaults and help semantics | `test_analysis_settings.py`; cross-page integration in `test_workspace.py` |
| Analyze field layout, compact-window reachability, help geometry and native font/control regressions | `test_analysis_layout.py`, `test_analysis_help_stability.py`; shared assertions in `analysis_helpers.py` |
| File-derived unit/origin defaults, provenance label placement, mapping-dependent unit controls, manual overrides and resets for new input | `test_input_metadata.py`, `test_analysis_input_reset.py` |
| App-wide field wheel/trackpad page scrolling, unchanged focused numeric/calendar/dropdown values, embedded text editors, pinned graph fields, open-list scrolling and keyboard/button edits | `test_analysis_scrolling.py` |
| Signal-column dropdowns, header-only batch validation, ambiguity/conflicts, persisted choices and independent official pipeline equivalence | `test_column_mapping.py` |
| Authoritative signal inputs, manual overrides, explicit absence, clock/preparation agreement, saved selections and unchanged original samples | `test_signal_selection.py` |
| Per-sensor inversion, fixed-order official preparation, all legacy signed permutations, saved-setting validation and migration | `test_axis_mapping.py`, `test_column_mapping.py` |
| Prepared-data coverage and recording overview | `test_availability.py`, `test_availability_plot_stability.py`, `test_recording_overview.py` |
| Gait overview, gait presence and epoch summaries | `test_gait_overview.py`, `test_gait_presence.py`, `test_epochs.py`, `test_epoch_presence_threshold.py`, `test_daily.py` |
| Mean 24-hour profiles, equal daily weighting, local clock slots, missingness and presence gates | `test_epoch_profile.py` |
| Result overview, timing and original table selection | `test_results_view.py`, `test_table_models.py` |
| Graph values, headings, scaling, selection and scrolling | `test_result_charts.py`, `test_graph_workspace.py`, `test_graph_selector_layout.py`, `test_plot_controls.py`, `test_result_navigation.py`, `test_time_axis.py`, `test_day_axis.py`, `test_epoch_axis.py`, `test_selection_lines.py` |
| Automatic percentage scaling, fixed Y-axis alignment and exact native-layout comparisons across all four graph views | `test_percentage_scaling.py`, `test_result_layout.py` |
| Plot reuse, redraw avoidance, exact shared time coordinates and discarded-result cleanup | `test_graph_performance.py`, `test_navigation_performance.py`, `test_result_plot_cache.py`, `test_result_coordinates.py` |
| Original sensor drill-down, indexed opening, stable channel windows and Home navigation | `test_sensor_context_workspace.py`, `test_raw_modalities.py` |
| Export selection, exact JSON precision, bounded batches, source integrity, atomic failures and background completion | `test_result_exports.py` |
| Complete local snapshots, responsive background reopening, isolated-reader cleanup/failure, exact restored values, deferred graphs, unsaved-close warnings and mixed-success bulk saves | `test_saved_results.py` |
| Run history, validated record/output metadata, transient-cache exclusion, cancellation and confirmed deletion | `test_run_management.py`, `test_bulk_runs.py`; cross-page history integration in `test_workspace.py` |
| Run identity and exact-byte checksums, rejected replacements/edits, isolated verification, unchanged displayed results on failure and snapshot/history consistency | `test_result_integrity.py`; export receipts in `test_saved_results.py` |
| File protection, unsafe loading and dependency-audit checks | `test_security.py` |
| Deferred startup imports, first-use graph construction, packaged execution, notices and signatures | `test_startup.py`, `test_smoke.py`, `test_packaging.py`, `test_acknowledgements.py`, `test_signing.py` |
| Release version checks, complete artifacts, checksums and verified publication | `test_release.py` |
| Studio identity, launcher and legacy user-data compatibility | `test_branding.py` |
| Window integration, shared settings and background error recovery | `test_app.py`, `test_workspace.py` |
| Specific input errors, complete worker/UI tracebacks, startup/smoke failure reports and unchanged failure counts | `test_error_handling.py` |
| Independent component composition, partial results, clock fallback and interrupted deletion | `test_workspace_components.py` |
| Frozen layout/graph ports, required callbacks connected before worker start, terminal cleanup, queued input/cancellation snapshots and coordinator size | `test_composition_order.py` |
| Data page tab/action order, callback delivery, deferred graphs and responsive splitter transitions | `test_data_page.py` |
| MainWindow ownership boundaries and recording/results/sensor workflows without driver ports | `test_composition_without_facade.py` |

Some behaviors are checked at several boundaries for different reasons: an export
unit test exercises special numeric values, a scientific test checks real outputs,
and a packaged probe checks that frozen imports and classifier assets work.
Those layers are complementary. Performance regressions primarily check retained
values, cache reuse, redraw counts and event-loop responsiveness; hardware timings
belong in the benchmark scripts rather than strict CI time limits.

Results rendering checks compare visible pixels against a complete native render
at both display scales, after horizontal release and at successive vertical
positions. Reference draws restore the partial image afterward, so they cannot
mask missing viewport updates. Checks cover marker changes, unchanged-row reuse,
cache invalidation, drawing failures and full exports. Shared-axis owner removal
retains path identity, settings and navigation in all four views; clearing hidden
results must release previously painted axes.
Dense Detailed gait cases also compare moving and stopped pixels for range of
motion and peak velocity using segment metadata, scrollbar/trackpad controls and
both pixel ratios. Display density stays consistent after release; independent
checks retain visible gaps, signed peaks, long intervals, original per-bar paths
when zoomed and every original visible bar during export.

Navigation tests build the eight-graph workspace only when they exercise shared
or offscreen axes; dense single-graph cases start from an empty window. Setup
processes queued Qt paints and forces a draw only if the figure is still stale.
Draws and event delivery that form part of an assertion remain explicit. Keep the
elapsed/calendar, graph-view, scroll-position and device-pixel-ratio matrices.
The first-date transition test also covers a hidden first date and a partial-day
zoom, including the next date's position, label bounds and non-overlap.

Loading regressions check exact TSDF values/dtypes against the previous scaling
operation, signed-zero and float bit patterns, metadata errors, and untouched
source files/shared arrays. Inspection cases retain exact quantiles and complete
missing counts, including nullable, non-sensor and time columns. Scientific
TSDF comparisons continue to exercise the real official pipeline stages.

## Shared fixtures and interactions

`conftest.py` contains fresh, function-scoped synthetic IMU and tremor-output
fixtures, a visible window fixture, and helpers for preview completion and bar
measurements. The shared window processes its initial Qt events before a test
starts; graph-performance and background-preview tests use this same fixture.
Modules retain their own window fixtures when they require special
sizes, dark palettes, Qt styles or background-job handling. The shared data
fixtures must remain function-scoped because several tests deliberately modify
samples to exercise validation and missing-data behavior.

Analyze layout scenarios live in `test_analysis_layout.py`, including the native
style/control-height matrix used by the early Windows CI gate and the Linux
font-fallback subprocess. `analysis_helpers.py` shares native sizing and full-control
visibility assertions with help and metadata layout checks. Metadata labels must
sit beneath their parameter names and share their left edge; tests compare relative
positions instead of pinning absolute screen coordinates. The common `wait_for_job`
helper keeps window teardown consistent.

Workflow packaging checks parse YAML and inspect the build job's benchmark arguments
and artifact uploads. They retain the required benchmark scripts, creation mode,
report destinations, bundle path and hidden-library inclusion while allowing YAML
formatting changes and additional benchmarks. PyYAML is a development dependency.
Worker tests check each callback before start and retain meaningful terminal/cleanup
ordering; independent signal-registration order is unrestricted. Fake workers are
cleared in a `finally` block so an early failure does not cause teardown timeouts.

`select_plot_metric` drives the current Plot series tree and its normal signals.
Tests for metric changes use it instead of changing the hidden legacy metric
selector. Dataset-row resets call the current `activate_dataset_rows` method;
scientific processing and comparisons do not depend on the old `apply_filters`
compatibility alias. Test names distinguish plot zoom, row selection and sensor
context from scientific filtered-gait processing.

Use the owning state for state assertions and the owning controller for isolated
behavior tests. UI integration tests should continue driving widgets/signals and
checking ordering, using the internal workspace driver API in
`ui/compatibility.py` where useful. Startup/smoke probes and benchmarks share
these implementation-coupled ports. Application code uses explicit component
owners, and the driver API retains its shrink-only budget guard.

Checks for removed UI controls inspect the actual widget tree, including hidden
children; an absent window alias does not prove that a widget is absent.
Settings checks inventory their real editors, buttons and dropdowns, so renamed
or hidden Apply/title controls cannot evade the absence assertions. Resource
policy cases establish that two workers are otherwise possible before checking a
configuration fallback. Calendar boundary cases compare the complete expected
range. Temporary mutation probes verify that these checks reject restored controls,
ignored configurations and truncated calendar boundaries.

Selector layout checks cover Detailed, 30-minute epochs, Day and 24-hour profile
views. The linked time marker is compared with a single native dashed stroke
through plots and their gaps at both display scales, after resizing and panning,
and in 600-DPI export. Value points remain above the line.
Axis-limit fields follow zoom, pan, scrolling, history and Home, including linked
graphs and silent limit changes. Numeric and clock fields display at most three
decimal places while unedited bounds and user-entered values retain full precision.
Checks also retain pending edits on unchanged redraws and release replaced axes.
Selection checks compare reused layouts with native pixels, bound text/row caches,
and require full layout after navigation or incompatible geometry changes.
Recently deselected bar plots reuse every original path within four entries and
a 128-MiB geometry budget. Tests cover eviction, context invalidation, exact
pixels/values, garbage collection of detached axes, discarded-array release and complete exports.
Rapid selection changes preserve synchronous signal delivery while sharing a
final graph/ruler paint and retaining compatible ruler formatters.
Workflow benchmarks select series in each view and switch tables through
the visible module tabs and output selector, with the Tables page open.

Use the [development commands](DEVELOPMENT.md) for local and CI checks.
That guide maintains the [lint and size limits](DEVELOPMENT.md#quality-gates-and-implementation-conventions),
[mypy scope](DEVELOPMENT.md#type-checking), and
[branch-coverage scope, floor and reports](DEVELOPMENT.md#branch-coverage).
Static checks complement the runtime and scientific tests; they do not replace them.
Failure-boundary tests deliberately raise unexpected exceptions, retain their original
tracebacks and require a failed probe exit status. Bulk-save checks fail either the
first or second save, reopen the successful snapshot with exact values and keep the
failed run unsaved with the window open.
The [scientific methodology](SCIENTIFIC_TESTS.md) explains the independent
references, tolerances and limits. Native Windows execution and signature checks
remain responsibilities of the Windows build workflows.

The [archived cleanup record](archive/test-suite-cleanup.md) preserves earlier
consolidation decisions and their validation counts. Current counts come from
pytest collection and the report for the tested commit.
