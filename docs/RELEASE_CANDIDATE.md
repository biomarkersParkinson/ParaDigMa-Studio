# ParaDigMa Studio 1.0.0rc1

Published 26 October 2026 as the first candidate for Studio 1.0. Scientific
processing uses official ParaDigMa 1.1.2. The distribution target is Windows x64;
local Linux checks supplement the Windows build and acceptance checks below.
The [candidate is a GitHub prerelease](https://github.com/biomarkersParkinson/ParaDigMa-Studio/releases/tag/v1.0.0rc1),
separate from stable 1.0.0. Its tagged source is `fc6df51fc06f776e843c35dad1ca97c3af1f8c05`.
See the [release notes](../CHANGELOG.md#100rc1--2026-10-26).

## Source and dependency checks

Checks use a newly created native-uv environment on Linux x64, Python 3.12.14
and offscreen Qt. The Windows workflow selects Python 3.12.10. Application code,
build scripts and workflows match source commit
[`1d20b79`](https://github.com/biomarkersParkinson/ParaDigMa-Studio/commit/1d20b7994fe391141d22786f80b954f8da7dfe40);
this preparation changes version metadata, release-test examples and documentation.
These checks do not constitute clinical validation.

| Check | Local outcome |
| --- | --- |
| Native uv lock/sync/check and dependency compatibility | Passed in a fresh environment; 99 installed packages. Only Studio's root version changed in the lock; third-party versions, sources and hashes are unchanged. |
| Current pip-audit findings | No blockers; two entries covered by the existing PyArrow Python-binding exception. |
| Ruff lint and formatting | Passed; 203 Python files formatted consistently. |
| Mypy, default and `win32` platforms | Passed; 53 configured source files. |
| Module-size and facade guards | Passed; 92 modules within 900 lines, facade within its 150-alias / 165-line budget. |
| Complete test suite, scientific comparisons and branch coverage | **1,567 passed, one Windows-native test skipped**, in 774.88 seconds. Configured combined statement/branch coverage **88.96%**, above the 80% floor. |
| Fresh portable Linux build and execution away from checkout | Passed: bundled models, real pipelines, two-worker batch, source plots, help, provenance, exports, saving and isolated reopening. |
| Wheel and source distribution | Built with standard `uv build`; version, current orientation resources and obsolete-asset exclusion verified. |
| Startup/import boundary | Five fresh-process checks passed; deferred data, scientific and plotting imports remain deferred. |
| User-guide captures | All seven regenerated through a real public-example gait run, saved normally and visually reviewed; six were byte-identical, Runs now shows the candidate version. |
| Documentation references | 105 local links/anchors and 171 local Python-file references checked; upstream test names remain linked to their official source. |

A separate Bandit 1.9.4 scan covered 112 source/script files, with no scan errors,
suppressions or high-severity findings. Its eight medium findings were reviewed:
six concern parent-owned private pickle transfers for worker results/inputs, and
two flag UI `shell=` state arguments rather than subprocess execution. The 38 low
findings cover imports, argument-list subprocesses and benchmark assertions.
This is a scoped static review, not an exhaustive dependency or security audit.

Local packaged startup was about 0.74 seconds to the report and 0.52 seconds to
first paint (five-process medians, warm OS/font caches). These observations were
collected during other checks and are not Windows performance guarantees.

## Documentation review

- README download instructions and release notes identify `1.0.0rc1`.
- The user guide follows Data, Analyze, Results and Runs, using one public
  example throughout. Its screenshots are refreshed together for the candidate.
- Analyze guidance covers shared time controls, file-derived values, resets,
  explicit source mapping, automatic preparation and the reviewed input axes.
- Saving and export guidance describes analysis-time software identity, CSV
  companions, checksum checks and the current saved-format requirement.
- Scientific documentation describes the current tests and rejection of retired
  settings. Older security/performance evidence retains its original date and
  scope; it is not relabeled as a new candidate audit.

## Candidate limitations

- The ordinary Windows build is unsigned. Publisher signing and Windows trust
  acceptance require separate setup; see [signing](../SIGNING.md).
- One configuration applies to an entire batch. Use the same subject and
  consistently formatted columns, units, wrist side and axes. Metadata warnings
  do not prevent analysis with the selected configuration.
- Gap-section filtering estimates duration from sample count and a
  recording-wide cadence. A recording with substantially different sampling
  rates in different sections can lose valid sections. Normalize such recordings
  before analysis; this case needs resolution before stable 1.0.
- Saved inactive runs can retain sources and result caches in memory during a
  session. There is no overall session-memory cap; long repeated workloads need
  acceptance testing before stable 1.0.
- Studio history/results require format version 2; older saved runs are not
  migrated. Preserve original recordings for re-analysis.
- The existing PyArrow advisory exception applies only to the documented C++ API
  issue that excludes Python bindings. No additional exception is introduced.

## Windows verification and acceptance

The [tagged release workflow #222](https://github.com/biomarkersParkinson/ParaDigMa-Studio/actions/runs/40385822649)
passed Windows auditing, tests, executable checks and publication. Its Git receipt
confirms the source, tag and published archive checksum. The actual public ZIP was
then downloaded and verified independently on Linux: its checksum, source/version,
locked Windows package graph, audit and all 1,772 inventory file hashes matched.
The [security summary](../SECURITY.md) and [evidence](archive/security-review-1.0.0rc1-2026-10-26.json) record
the results and archive SHA-256. Windows execution was verified in CI; manual
clean-machine acceptance remains separate.

Before stable 1.0, test the exact candidate ZIP on a Windows machine without a
source Python environment and record its checksum, Windows version and display
scaling:

- [ ] Extract into a fresh folder; launch with `_internal`, notices and security
  evidence present. Confirm About and new runs report `1.0.0rc1` / ParaDigMa 1.1.2.
- [ ] Check Data/Analyze at normal and enlarged display scaling and compact
  window sizes: shared time edits, file labels/defaults, new-file resets, mapping,
  help, warning controls and wheel scrolling without unintended value changes.
- [ ] Analyze one IMU recording, a uniformly formatted batch, and raw PPG-only
  input. Review missing samples, gaps, warnings, outputs and source preservation.
- [ ] Stop an analysis and check cancellation and temporary-worker cleanup.
- [ ] Save, close, restart and reopen. Verify Overview, Graphs, Tables, figures,
  standalone CSV plus companion, CSV ZIP and complete JSON export.
- [ ] Delete test runs after confirmation; verify original recordings remain.
- [ ] Exercise representative long recordings and repeated datasets; observe
  memory, temporary disk, load/save/reopen responsiveness and practical limits.

Record completed checks and any remaining issues before promoting a later
candidate to stable. Do not move a published tag; fixes get a new candidate.
