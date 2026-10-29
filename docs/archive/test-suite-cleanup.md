# Test-suite cleanup record

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

This historical validation applies to that cleanup only. See the
[current test guide](../TEST_SUITE.md) for the maintained coverage map and commands.

## 2026-10-29: stronger assertions and focused UI consolidation

Starting point: `1337c33`, with **1,718 collected cases** in 791 test functions.

- Replace relative tolerances on absolute calendar coordinates with zero
  relative tolerance and explicit absolute bounds in Results navigation and
  day/epoch tick tests. Keep mouse/pixel-derived tolerances and scientific-value
  tolerances separate.
- Check the complete Analyze settings and displayed origin with loaded,
  non-default columns, units, axes and thresholds after every help open and
  close. Cover both an automatic file origin and a custom origin. Move repeated
  tooltip/text/window assertions to the dedicated help-dialog checks.
- Fold the basic Data-to-Analyze time-selection case into the shared-time
  diagnostic test, retaining its sampling-rate and selected-channel-exclusion
  assertions.
- Retain the mapping-heading/editor gap assertion in the main layout test;
  the existing native-size matrix owns help-position stability.
- Combine the basic loaded-results plot check with numeric metric-name handling,
  retaining default-storage isolation, all three table rows/bar paths, original
  time/value assertions, export availability and an actual canvas draw.
- Rename missing-source-metadata and editor-schema-refresh cases so their names
  distinguish them from unsupported saved formats and replacement-file loads.

Three scenarios are consolidated and the help-origin case gains one distinct
mode, giving **1,716 cases** in 788 functions. Scientific comparisons, supported
format/rejection cases, real worker tests and all native-size/display-scale
variants remain. Application code, dependencies and runtime behavior are unchanged.

Focused validation: **216 passed**. Isolated test-only injections of a 60-second
pinned-ruler error and help-triggered origin corruption are now rejected by the
strengthened tests; the latter fails for both automatic and custom origins.

Full validation on Linux: **1,715 passed, 1 skipped**, with **89.36% coverage**
against the unchanged 80% gate. The skip is native Windows signature verification.
Ruff lint/formatting, the module/facade limits and both Linux- and Windows-target
mypy checks pass. Native Windows CI remains a separate check.
