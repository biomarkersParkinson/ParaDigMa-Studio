# Security review

Release verification updated **26 October 2026** for published
[ParaDigMa Studio 1.0.0rc1](https://github.com/biomarkersParkinson/ParaDigMa-Studio/releases/tag/v1.0.0rc1),
source commit
[`fc6df51`](https://github.com/biomarkersParkinson/ParaDigMa-Studio/commit/fc6df51fc06f776e843c35dad1ca97c3af1f8c05).

The [current evidence](docs/security-review.json) combines release-preparation
checks, the successful tagged Windows workflow and independent inspection of the
published Windows ZIP. Linux checks and Windows checks are identified separately.
This is scoped release verification, not a security certification or a repeat of
the entire manual audit performed on 18 October. That
[historical report](docs/archive/security-review-0.6.0a3-2026-10-18.json) is preserved
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

## Dependency reproducibility

Official build jobs install one [native uv lock](docs/DEPENDENCIES.md) in a clean
virtual environment, using the commit-pinned setup action and uv 0.13.5.
Registry artifacts have lock hashes, and isolated builds require hashed
constraints. The Open Movement reader is pinned to its full Git commit.
Native lock/sync/check commands reject stale inputs and environment drift.

Manifest generation requires an audit covering the same installed package/version
set. The download includes `security/uv.lock`, `security/build-info.json` and
`security/dependency-audit.json`. Release preparation compares that evidence with
the tagged Windows dependency graph, including the reader's source revision,
before checking the complete file inventory and uploaded asset digests.
No new advisory exceptions were introduced for this release candidate.

PyArrow 22.0.0 has two audit entries for **CVE-2026-25087 / PYSEC-2026-113**.
The [advisory](https://github.com/advisories/GHSA-rgxp-2hwp-jwgg) excludes Python
bindings; its affected C++ IPC API is not used here. ParaDigMa constrains Arrow
below the fixed release. The audit policy permits only this package-specific
issue; no C++ patch is claimed.

## Safeguards and trust boundaries

| Area | Current behavior |
| --- | --- |
| Input | Pickle requires explicit trust. Trusted pickle inputs and bundled models use executable deserialization. Result JSON reopening loads neither user-selected pickle nor original recordings. |
| Saved data | Plaintext results/history under `%LOCALAPPDATA%\ParaDigMaStudio\runs`. Run identity and SHA-256 checks detect mismatched or changed result files. History is trusted local metadata; checks do not authenticate files against an attacker who can rewrite both history and results. There is no app encryption or authentication. |
| Saved formats | History and result JSON require Studio format version 2. Unsupported versions are reported, without migration or discovery of the former ParaDigMaDesktop storage directory. |
| Diagnostics | Worker tracebacks, paths and error details may identify recordings/subjects. Logs have no automatic redaction. |
| Files | Atomic single-file replacement; known-input/alias protection, including TSDF companion files; CSV formula-text protection. Deletion requires confirmation, defaults to Cancel and protects inputs, directories and shared outputs. |
| Workers | At most two recording workers using CPU/RAM estimates; owned workers and temporary files are cleaned up on Stop and normal failure. Estimates are not hard limits; worker processes are not a sandbox. Private pickle transfers rely on trusted code and OS protection of temporary files. |
| UI and caches | Preview/display caches have budgets and context invalidation, but saved inactive runs can retain sources and result tables. There is no total session-memory cap. |
| Network | No automatic recording upload or telemetry in the wrapper. Explicit documentation links open a browser. Dependency downloads and advisory queries belong to development/build tooling. |

Runs retain the Studio and ParaDigMa versions used for analysis, plus the Studio
build commit when available. Reopening and exporting preserve that identity.
CSV exports have a metadata companion with the CSV's SHA-256. Both files are
staged before replacement, but replacing two files is not one filesystem
transaction; a checksum mismatch identifies a separated or partially replaced
pair. These checks provide no authentication.

## Distribution and remaining limits

The published candidate is **unsigned**. Windows execution was checked by tagged
CI, and the public download was inspected independently; a manual clean-machine
Windows acceptance run, Defender scan, actual publisher signing, certificate-chain
verification and Smart App Control acceptance are not claimed. See the
[candidate acceptance checklist](docs/RELEASE_CANDIDATE.md#windows-verification-and-acceptance)
and [publisher-signing guide](SIGNING.md).

Actions commits are pinned. Release/status jobs receive tag-scoped workflow
conditions and write permission; status-job checkout credentials push the Git
receipt. OIDC is confined to environment-gated signing. Checksums and CI receipts
identify checked content and publication results; they do not replace a publisher
signature or certify every dependency's behavior.

Malformed or large inputs can exhaust resources; parsers have not been fuzz-tested.
Abrupt termination may leave workers or temporary data, and deletion is not secure
erasure. Sensitive results and logs rely on OS permissions and disk encryption.
Instrumented network isolation and an exhaustive dependency source audit remain
outside these checks. Scientific and workload limitations are recorded separately
in the [candidate record](docs/RELEASE_CANDIDATE.md#candidate-limitations).
