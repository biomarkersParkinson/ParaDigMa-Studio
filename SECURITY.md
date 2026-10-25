# Security review

Reviewed **18 October 2026**, ParaDigMa Studio **0.6.0a3**,
[source commit `838bd7a`](https://github.com/biomarkersParkinson/ParaDigMa-Studio/commit/838bd7adfd9cad6449e197f8e06b93c34e2aa165).
Scope: Linux source, dependencies and fresh portable executable; Windows build,
release and signing workflows. Tagged Windows CI verifies the Windows package
separately. [Evidence](docs/security-review.json) records scope and limitations;
this is not a security certification. The dependency update below is a separate,
later check; the broad review and its historical test counts remain dated above.

## Dependency reproducibility — 25 October 2026

The owner's latest Windows Actions reports identify commit `04b61d4`, Python
3.12.10 and no blocking audit findings. They already contain Pillow 13.0.0 and
updated certifi, filelock and setuptools. Advisories observed in an older Linux
review environment did not establish the same findings in this Windows build.

Official build jobs now install [committed dependency locks](requirements/README.md)
in a clean virtual environment. Registry packages and isolated build dependencies
require SHA-256 hashes; the patched Open Movement source is bound to its full Git
commit. Verification rejects stale lock inputs, missing/extra packages, version
drift and a substituted reader source. The latest Windows numerical versions are
preserved; a supplemental Linux lock supports source validation.

Manifest generation and publication require an audit of the same package/version
set and carry the lock evidence into the download. The fresh locked Linux
environment's 99-package audit has no blockers beyond the existing documented
PyArrow exception. The Windows workflow separately validates its target lock and
packaged executable. No new advisory exceptions were introduced.

## Verification

- **Dependencies:** 96 packages audited; no skipped packages or blocking findings
  under the PyArrow exception below. `pip check` passed.
- **Bandit:** 93 files; 0 high, 7 medium and 22 low items reviewed; no scan
  errors/suppressions. Five medium items concern private worker pickle transfers;
  two are false positives for UI `ShellState` constructor arguments.
- **Tests:** 201 security-related cases passed within the full suite;
  **1,056 passed**, one Windows-only skip. Controller/error-boundary branch
  coverage passed the 80% floor. Scientific comparisons and source probes passed.
- **Portable app:** fresh Linux build passed smoke/startup probes, clean-layout,
  notice and complete SHA-256 inventory checks. Windows checks gate publication.

## Safeguards and trust boundaries

| Area | Current behavior |
| --- | --- |
| Input | Pickle requires explicit trust; accepted files and bundled models can execute code. Result JSON reopening loads neither pickle nor original recordings. |
| Saved data | Plaintext results/history under `%LOCALAPPDATA%\ParaDigMaStudio\runs`. Run identity and checksums detect mismatched/changed result files; there is no app encryption or authentication. Original recordings are not copied into saved runs. |
| Diagnostics | Worker tracebacks, paths and error details may identify recordings/subjects. Logs have no automatic redaction. |
| Files | Atomic writes; known-input/alias protection, including TSDF time/value files; CSV formula-text protection. Deletion requires confirmation, defaults to Cancel and protects inputs, directories and shared outputs. History is trusted local metadata. |
| Workers | At most two recording workers using CPU/RAM estimates; cleanup on Stop/normal failure. Estimates are not hard limits; workers are not a sandbox. |
| UI and caches | Explicit controller dependencies; fixed internal driver ports. Preview/display caches stay in memory and are bounded, with context invalidation; they do not cap total app memory. |
| Network | No automatic recording upload or telemetry in the wrapper. Documentation links open a browser. |

## Dependencies and distribution

PyArrow 22.0.0 has two audit entries for **CVE-2026-25087 / PYSEC-2026-113**.
The [advisory](https://github.com/advisories/GHSA-rgxp-2hwp-jwgg) excludes Python
bindings; its vulnerable C++ IPC API is not used here. ParaDigMa constrains Arrow
below the fixed release. CI excludes only this issue; no C++ patch is claimed.

Official runtime, development and build dependencies are locked with hashes and
the explicit Git source pin; Actions commits are pinned. Locks and audits do not
certify every dependency's behavior. Tag-only release/status jobs have write permission; status-job
checkout credentials push Git notes. OIDC is confined to environment-gated signing.
Ordinary releases are unsigned; [publisher signing](SIGNING.md) needs a verified
identity. Release gates check source/version, complete inventory, packaged execution
and uploaded asset hashes. The [workflow receipt](docs/RELEASES.md) records the
actual publication outcome; hashes alone do not establish publisher trust.

## Remaining limitations

Malformed/large files can exhaust resources; parsers were not fuzz-tested. Abrupt
termination may leave workers/temporary data; deletion is not secure erasure.
Protect sensitive results/logs with OS permissions and disk encryption. Network
isolation, Windows malware scans, actual publisher signing, certificate chains and
Smart App Control acceptance were not verified.
