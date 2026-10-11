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
