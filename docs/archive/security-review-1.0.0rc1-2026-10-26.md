# Published 1.0.0rc1 security verification

Release verification updated **26 October 2026** for published
[ParaDigMa Studio 1.0.0rc1](https://github.com/biomarkersParkinson/ParaDigMa-Studio/releases/tag/v1.0.0rc1),
source commit
[`fc6df51`](https://github.com/biomarkersParkinson/ParaDigMa-Studio/commit/fc6df51fc06f776e843c35dad1ca97c3af1f8c05).

The [release evidence](security-review-1.0.0rc1-2026-10-26.json) combines release-preparation
checks, the successful tagged Windows workflow and independent inspection of the
published Windows ZIP. Linux checks and Windows checks are identified separately.
This is scoped release verification, not a security certification or a repeat of
the entire manual audit performed on 18 October. That
[historical report](security-review-0.6.0a3-2026-10-18.json) is preserved
unchanged with its original version, findings and limitations.

## Verification for 1.0.0rc1

| Check | Verified outcome |
| --- | --- |
| Published Windows dependencies | The build inventory contains 102 packages including Studio. pip-audit checked 101 third-party packages: no blocking findings or unexpected skips; two entries fall under the existing PyArrow exception below. Studio is first-party source, verified against its tag rather than audited as a PyPI release. |
| Supplemental Linux dependencies | Fresh locked environment: 99 packages including Studio, 98 third-party packages audited, no drift or dependency conflicts, and no blocking audit findings under the same exception. |
| Source scan | Bandit 1.9.4 scanned 112 source/script files: 0 high, 8 medium and 38 low findings reviewed; no scan errors, suppressions or skipped checks. The medium findings are six private-worker pickle loads and two false positives for UI `ShellState` arguments. Findings remain recorded; this is not a zero-findings scan. |
| Local tests | 1,567 passed; one Windows Authenticode test skipped on Linux. Configured combined statement/branch coverage was 88.96%, above the 80% floor; this is not whole-app coverage. Scientific comparisons and security regressions are included in that run. |
| Local packaged executable | A fresh Linux bundle passed smoke/startup checks away from the checkout, including real pipelines, parallel workers, model assets, provenance, exports, saving and isolated reopening. |
| Tagged Windows checks | [Workflow #222](https://github.com/biomarkersParkinson/ParaDigMa-Studio/actions/runs/40385822649) passed dependency auditing, lint/types, native layout, full tests/coverage, packaged execution, benchmarks, manifest and release checks. Publication and its Git receipt both report success. |
| Actual public Windows ZIP | Downloaded after publication and checked independently on Linux: the archive matches the published checksum and Git receipt; all 1,772 inventory hashes, source/version, Windows dependency graph, shipped lock/audit, notices and required DLLs passed verification. |

The downloaded archive's SHA-256 is:

```text
412f85e4da0ff3f142f2fb46b535cceb42b03479de3c3aab489a057f0e493e58
```

The ZIP's build environment uses **Python 3.12.10** and **ParaDigMa 1.1.2**.
The package inventory includes development/build tools; it is not a claim that
every listed package is included in the executable. The separate local source
checks used Linux/Python 3.12.14. Audits are dated snapshots of advisory data.

## Dependency exception reviewed for this release

PyArrow 22.0.0 has two audit entries for **CVE-2026-25087 / PYSEC-2026-113**.
The [advisory](https://github.com/advisories/GHSA-rgxp-2hwp-jwgg) excludes Python
bindings; its affected C++ IPC API is not used here. ParaDigMa constrains Arrow
below the fixed release. The audit policy permits only this package-specific
issue; no C++ patch is claimed.

This is a dated record for the tagged candidate. The
[current security policy](../../SECURITY.md) describes reporting, supported
versions and current trust boundaries; the
[candidate checklist](../RELEASE_CANDIDATE.md#windows-verification-and-acceptance)
records remaining manual acceptance work.
