# Test suite organization

The suite is organized around current application responsibilities. Tests protect
scientific values, supported file formats, user workflows, responsiveness and
packaging. A fixed historical bug remains a useful regression test when its
trigger and expected behavior still apply.

## Regression coverage map

| Responsibility | Test modules |
| --- | --- |
| Source-module 900-line limit and boundary cases | `test_module_size.py`; CI entry point `scripts/check_module_size.py` |
| Shrinking workspace aliases, line budget and retired-name protection | `test_workspace_facade.py`; CI entry point `scripts/check_workspace_facade.py` |
| Independent official ParaDigMa comparisons | `test_scientific_equivalence.py` |
| Loading, validation and preparation | `test_core.py`, `test_preparation.py`, `test_missing_samples.py`, `test_cwa.py`, `test_empatica.py`, `test_tsdf_input.py` |
| Multiple recordings, source clocks and identifiers | `test_recordings.py` |
| Spawned recording workers, CPU/RAM policy, CPU affinity, cancellation and official batch equivalence | `test_parallel_execution.py`, `test_parallel_scientific.py` |
| Data-page statistics and recording previews | `test_inspection.py`, `test_previews.py` |
| Raw-graph time encodings, cumulative differences and unchanged source samples | `test_input_time_plot.py` |
| Clock-only previews, module requirements, time formats and editable pending origins | `test_origin_preview.py`, `test_previews.py` |
| Analysis settings and help | `test_analysis_settings.py`, `test_analysis_help_stability.py`; cross-page integration in `test_workspace.py` |
| Prepared-data coverage and recording overview | `test_availability.py`, `test_availability_plot_stability.py`, `test_recording_overview.py` |
| Gait overview, gait presence and epoch summaries | `test_gait_overview.py`, `test_gait_presence.py`, `test_epochs.py`, `test_epoch_presence_threshold.py`, `test_daily.py` |
| Mean 24-hour profiles, equal daily weighting, local clock slots, missingness and presence gates | `test_epoch_profile.py` |
| Result overview, timing and original table selection | `test_results_view.py`, `test_table_models.py` |
| Graph values, headings, scaling, selection and scrolling | `test_result_charts.py`, `test_graph_workspace.py`, `test_graph_selector_layout.py`, `test_plot_controls.py`, `test_result_navigation.py`, `test_time_axis.py`, `test_day_axis.py`, `test_epoch_axis.py` |
| Automatic percentage scaling and fixed Y-axis alignment across all four graph views | `test_percentage_scaling.py`, `test_result_layout.py` |
| Plot reuse, redraw avoidance and discarded-result cleanup | `test_graph_performance.py`, `test_navigation_performance.py` |
| Original sensor drill-down, indexed opening, stable channel windows and Home navigation | `test_sensor_context_workspace.py`, `test_raw_modalities.py` |
| Export selection, serialization and background completion | `test_result_exports.py` |
| Complete local snapshots, reopening and unsaved-close warnings | `test_saved_results.py` |
| Run history, warnings, cancellation and confirmed deletion | `test_run_management.py`, `test_bulk_runs.py`; cross-page history integration in `test_workspace.py` |
| File protection, unsafe loading and dependency-audit checks | `test_security.py` |
| Deferred startup imports, first-use graph construction, packaged execution, notices and signatures | `test_startup.py`, `test_smoke.py`, `test_packaging.py`, `test_acknowledgements.py`, `test_signing.py` |
| Release version checks, complete artifacts, checksums and verified publication | `test_release.py` |
| Studio identity, launcher and legacy user-data compatibility | `test_branding.py` |
| Window integration, shared settings and background error recovery | `test_app.py`, `test_workspace.py` |
| Specific input errors, complete worker/UI tracebacks and unchanged failure counts | `test_error_handling.py` |
| Independent component composition, partial results, clock fallback and interrupted deletion | `test_workspace_components.py` |
| Frozen layout/graph ports without application-window dependencies, Qt/job ordering and coordinator size | `test_composition_order.py` |

Some behaviors are checked at several boundaries for different reasons: an export
unit test exercises special numeric values, a scientific test checks real outputs,
and a packaged probe checks that frozen imports and classifier assets work.
Those layers are complementary. Performance regressions primarily check retained
values, cache reuse, redraw counts and event-loop responsiveness; hardware timings
belong in the benchmark scripts rather than strict CI time limits.

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

`select_plot_metric` drives the current Plot series tree and its normal signals.
Tests for metric changes use it instead of changing the hidden legacy metric
selector. Dataset-row resets call the current `activate_dataset_rows` method;
scientific processing and comparisons do not depend on the old `apply_filters`
compatibility alias. Test names distinguish plot zoom, row selection and sensor
context from scientific filtered-gait processing.

Use the owning state for state assertions and the owning controller for isolated
behavior tests. UI integration tests should continue driving widgets/signals and
checking ordering. Legacy window aliases are being retired incrementally; avoid
introducing new dependencies on that facade.

Selector layout checks cover Detailed, 30-minute epochs, Day and 24-hour profile
views. Workflow benchmarks select series in each view and switch tables through
the visible module tabs and output selector, with the Tables page open.

Use the [development commands](DEVELOPMENT.md) for local and CI checks.
That guide maintains the [lint and size limits](DEVELOPMENT.md#quality-gates-and-implementation-conventions),
[mypy scope](DEVELOPMENT.md#type-checking), and
[branch-coverage scope, floor and reports](DEVELOPMENT.md#branch-coverage).
Static checks complement the runtime and scientific tests; they do not replace them.
The [scientific methodology](SCIENTIFIC_TESTS.md) explains the independent
references, tolerances and limits. Native Windows execution and signature checks
remain responsibilities of the Windows build workflows.

The [archived cleanup record](archive/test-suite-cleanup.md) preserves earlier
consolidation decisions and their validation counts. Current counts come from
pytest collection and the report for the tested commit.
