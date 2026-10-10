# Test suite organization

The suite is organized around current application responsibilities. Tests protect
scientific values, supported file formats, user workflows, responsiveness and
packaging. A fixed historical bug remains a useful regression test when its
trigger and expected behavior still apply.

## Coverage map

| Responsibility | Test modules |
| --- | --- |
| Independent official ParaDigMa comparisons | `test_scientific_equivalence.py` |
| Loading, validation and preparation | `test_core.py`, `test_preparation.py`, `test_missing_samples.py`, `test_cwa.py`, `test_empatica.py` |
| Multiple recordings, source clocks and identifiers | `test_recordings.py` |
| Data-page statistics and recording previews | `test_inspection.py`, `test_previews.py` |
| Analysis settings and help | `test_analysis_settings.py`, `test_analysis_help_stability.py`; cross-page integration in `test_workspace.py` |
| Prepared-data coverage and recording overview | `test_availability.py`, `test_availability_plot_stability.py`, `test_recording_overview.py` |
| Gait overview, gait presence and epoch summaries | `test_gait_overview.py`, `test_gait_presence.py`, `test_epochs.py`, `test_epoch_presence_threshold.py` |
| Result overview, timing and original table selection | `test_results_view.py`, `test_table_models.py` |
| Graph values, headings, scaling, selection and scrolling | `test_result_charts.py`, `test_graph_workspace.py`, `test_graph_selector_layout.py`, `test_plot_controls.py`, `test_time_axis.py` |
| Plot reuse, redraw avoidance and discarded-result cleanup | `test_graph_performance.py`, `test_pan_performance.py` |
| Original sensor drill-down and channel selection | `test_sensor_context_workspace.py`, `test_raw_modalities.py` |
| Export selection, serialization and background completion | `test_result_exports.py` |
| Run history, warnings, cancellation and confirmed deletion | `test_run_management.py`, `test_bulk_runs.py`; cross-page history integration in `test_workspace.py` |
| File protection, unsafe loading and dependency-audit checks | `test_security.py` |
| Startup, packaged execution, notices and signatures | `test_startup.py`, `test_smoke.py`, `test_acknowledgements.py`, `test_signing.py` |
| Window integration, shared settings and background error recovery | `test_app.py`, `test_workspace.py` |

Some behaviors are checked at several boundaries for different reasons: an export
unit test exercises special numeric values, a scientific test checks real outputs,
and a packaged probe checks that frozen imports and classifier assets work.
Those layers are complementary. Performance regressions primarily check retained
values, cache reuse, redraw counts and event-loop responsiveness; hardware timings
belong in the benchmark scripts rather than strict CI time limits.

## Shared fixtures and interactions

`conftest.py` contains fresh, function-scoped synthetic IMU and tremor-output
fixtures, a visible window fixture, and helpers for preview completion and bar
measurements. Modules retain their own window fixtures when they require special
sizes, dark palettes, Qt styles or background-job handling. The shared data
fixtures must remain function-scoped because several tests deliberately modify
samples to exercise validation and missing-data behavior.

`select_plot_metric` drives the current Plot series tree and its normal signals.
Tests for metric changes use it instead of changing the hidden legacy metric
selector. Dataset-row resets call the current `activate_dataset_rows` method;
scientific processing and comparisons do not depend on the old `apply_filters`
compatibility alias. Test names distinguish plot zoom, row selection and sensor
context from scientific filtered-gait processing.

## Cleanup record

The cleanup starts from commit `b8f84b7`, with **386 collected cases**:

- Moved 37 test definitions into feature modules, replacing the mixed
  `test_regressions.py`, `test_results_redesign.py` and
  `test_review_performance.py` files. Their distinct numeric, safety, rendering,
  storage and responsiveness cases remain.
- Combined the single module-help positioning check with the broader all-fields
  help test. The latter now also checks absolute module-button positions, button
  sizes and the explicit 16-pixel spacing, across its existing parameter variants.
- Combined the two basic zoom/table-preservation checks. The merged test retains
  both original zoom ranges, including an empty visible range, and verifies the
  full original rows, bars and CSV export.
- Split the combined overview-clock/run-button check into two feature-specific
  tests, preserving both expectations.
- Renamed seven tests whose titles referred to removed Results filters or
  ambiguous filtering. Scientific filtered-gait tests keep that terminology.
- Consolidated identical seeded recordings and common output tables. Explicit
  assertions, comparison calls and parameter decorators in all 272 retained
  test definitions were checked against the previous definitions; none were
  lost through moving or renaming. Scientific parameter combinations, fixtures,
  expected values and numerical tolerances are unchanged.
- Centralized headless Qt setup and removed the now-unneeded Ruff import-order
  exception for `test_workspace.py`.

The revised suite collects **385 cases**, including the same **31 scientific
cases**. The decrease is the net result of two consolidations and one split;
it is not removal of a scientific scenario or a Windows paint/size variant.

Validation on Linux: **384 passed, 1 skipped**, with Ruff lint and formatting
checks passing. The skipped case exercises native Windows signature verification.
Application code, UI and dependency versions are unchanged by this cleanup.

Run the suite and style checks using the [development commands](DEVELOPMENT.md).
The [scientific methodology](SCIENTIFIC_TESTS.md) explains the independent
references, tolerances and limits. Native Windows execution and signature checks
remain responsibilities of the Windows build workflows.
