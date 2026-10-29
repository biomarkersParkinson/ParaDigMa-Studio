# Documentation archive

These records preserve development evidence. They are not current user or
setup instructions; use the [documentation index](../README.md) instead.

- [Performance history, 0.2.2–0.5.31](performance/REVIEW_HISTORY.md): versioned
  changes and before/after measurements. Referenced JSON files remain unchanged,
  including original environment details and older package names.
- [Runtime measurements, October 2026](performance/runtime-measurements-2026-10.md):
  dated loading, rendering, saving and component comparisons moved from the
  active performance guide; [component extraction JSON](performance/component-review-2026-10-16.json)
  retains the original full samples and qualifications.
- [Codebase audit, 0.5.23](codebase-audit-0.5.23.md): the refactor reviewed on
  9 October 2026 and its validation results.
- [Test-suite cleanup](test-suite-cleanup.md): consolidation decisions and
  validation from the cleanups based on commits `b8f84b7` and `1337c33`.
- [Security review, 6 October 2026](security-review-2026-10-06.md): the earlier
  audit, superseded by the current repository security summary.
- [Security review evidence, 18 October 2026](security-review-0.6.0a3-2026-10-18.json):
  the unchanged 0.6.0a3 review, including its original package/test counts,
  manual findings and limitations.
- [Published 1.0.0rc1 security verification, 26 October 2026](security-review-1.0.0rc1-2026-10-26.md)
  and its [JSON evidence](security-review-1.0.0rc1-2026-10-26.json): release-preparation,
  tagged Windows CI and public-ZIP verification with their original scope.
- [Original supplied Windows dependency baseline](dependency-baseline.json):
  the historical inventory used for dependency hardening; current environment
  instructions are in the [dependency guide](../DEPENDENCIES.md).
- [Workspace gallery](workspace.md): screenshots and descriptions from multiple
  earlier revisions. Additional captures show [old graph settings](screenshots/graph-settings.png)
  and an [earlier gait overview](screenshots/results.png).

Screenshot appearance, control names, test counts and measured sizes are
historical. Scientific fixture provenance and current test methodology remain
in the active [scientific guide](../SCIENTIFIC_TESTS.md).
