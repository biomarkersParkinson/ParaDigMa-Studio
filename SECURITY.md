# Security policy

This policy describes current safeguards and trust boundaries on `main`, the
supported releases and how to report vulnerabilities. Release verification
records identify their own versions, dates and scope.

- [Reporting a vulnerability](#reporting-a-vulnerability)
- [Supported versions](#supported-versions)
- [Safeguards and trust boundaries](#safeguards-and-trust-boundaries)
- [Release verification](#release-verification)
- [Dependency reproducibility](#dependency-reproducibility)
- [Distribution and remaining limits](#distribution-and-remaining-limits)

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/biomarkersParkinson/ParaDigMa-Studio/security/advisories/new)
for suspected security vulnerabilities. Include:

- **Environment:** Studio version or source commit and Windows version.
- **Affected behavior:** file format or action, and expected security impact.
- **Reproduction:** minimal steps and, where possible, a synthetic example.

Remove identifying paths, sensor recordings and subject information. Keep exploit
details and sensitive data out of public issues. If GitHub does not show the
private reporting option, open an issue requesting a private contact route
without describing the vulnerability.

Ordinary bugs and scientific-output questions can use the
[bug-report form](https://github.com/biomarkersParkinson/ParaDigMa-Studio/issues/new?template=bug_report.yml).

## Supported versions

Security fixes target the latest published Studio release or prerelease and the
current `main` branch. Report the exact version or commit; older builds may need
updating to receive a fix.

The published candidate is [**1.0.0rc1**](https://github.com/biomarkersParkinson/ParaDigMa-Studio/releases/tag/v1.0.0rc1).
Supported saved-data formats follow the independent
[saved-run contract](docs/PYTHON_API.md#saved-run-contract). Unsupported history
and result versions are reported without migration or discovery of the former
ParaDigMaDesktop storage directory.

## Safeguards and trust boundaries

### Inputs and deserialization

| Input | Behavior and trust requirement |
| --- | --- |
| Pickle recordings | Require explicit trust before loading. Pickle can execute code; accepting that prompt does not make the input safe. |
| Bundled models | Use executable deserialization and rely on trusted application/model files. |
| Saved results | Decoded from JSON. Reopening does not load user-selected pickle files or automatically reload original recordings. Internal worker transfers are described below. |

### Local data and diagnostics

On Windows, local run history and saved snapshots are stored as plaintext under
`%LOCALAPPDATA%\ParaDigMaStudio\runs`. Studio provides no application-level
encryption or authentication. Sensitive files rely on operating-system permissions
and disk encryption. See the [storage reference](docs/PYTHON_API.md#application-storage)
for directory details.

Processing logs and worker tracebacks can contain paths, error details and
recording/subject information. Logs have no automatic redaction; review them
before sharing.

### File protection and result integrity

| Operation | Safeguard |
| --- | --- |
| Reopen saved results from disk | Require the recorded run identity and SHA-256. The same result-file bytes are checked and decoded. |
| Save or export | Complete a temporary write before atomic single-file replacement; protect known source paths and their aliases, including TSDF companion binaries. |
| Export CSV | Neutralize formula-like text and include analysis metadata with a checksum companion for standalone app CSV exports. |
| Delete runs/outputs | Ask for confirmation with Cancel selected by default; protect inputs, directories and shared outputs. Deletion is not secure erasure. |

History is trusted local metadata. Run IDs and checksums detect mismatched or
changed files; they do not authenticate results against an attacker who can
rewrite both history and result files. The [integrity implementation](src/paradigma_studio/result_integrity.py)
and [saved-run contract](docs/PYTHON_API.md#saved-run-contract) define those checks.

Runs retain the Studio and ParaDigMa versions used for analysis, plus the Studio
build commit when available. Reopening and exports preserve that identity.
For standalone app CSV exports, the CSV and its `.csv.metadata.json` companion
are both staged before replacement, but the replacements are not one filesystem
transaction. A checksum mismatch
identifies a separated or partially replaced pair; it provides no authentication.
See [CSV metadata companions](docs/PYTHON_API.md#csv-metadata-companions).

### Workers, memory and network

| Area | Current behavior and limit |
| --- | --- |
| Analysis workers | At most two recording workers, selected using CPU/RAM estimates. Stop and normal failure clean up owned workers and temporary files. Estimates are not hard limits, and workers are not a sandbox. |
| Private transfers | Analysis and large-result reopening use parent-owned temporary pickle files. Their safety relies on trusted code and OS protection of the temporary directory. |
| UI and caches | Preview/display caches have budgets and context invalidation. Inactive saved runs can retain source frames and result tables, so there is no total session-memory cap. |
| Network | The wrapper does not automatically upload recordings or send telemetry. Explicit documentation links open a browser. Dependency downloads and advisory queries belong to development/build tooling. |

Worker ownership is explained in [Architecture](docs/ARCHITECTURE.md#execution-and-cancellation);
cache and worker budgets are maintained in [Performance](docs/PERFORMANCE.md#cache-and-worker-budgets).

## Release verification

The following records preserve completed checks for their own revisions:

| Record | Scope |
| --- | --- |
| [26 October 2026 candidate verification](docs/archive/security-review-1.0.0rc1-2026-10-26.md) and [JSON evidence](docs/archive/security-review-1.0.0rc1-2026-10-26.json) | Published 1.0.0rc1 source, tagged Windows workflow, independently checked public ZIP, dependency inventory and supplemental Linux checks |
| [18 October 2026 manual review](docs/archive/security-review-0.6.0a3-2026-10-18.json) | Earlier source review, findings and limitations, retained with their original scope |

These are dated findings, not a security certification or a fresh audit of later
commits. Advisory results are snapshots of the data available when the audit ran.
The candidate's Windows execution was verified in tagged CI; independent public
ZIP inspection was performed on Linux. Remaining manual acceptance work is
listed [below](#distribution-and-remaining-limits).

For download checks, see [release verification instructions](docs/RELEASES.md#release-page-and-download).
The release guide distinguishes archive checksums, the bundle's complete file
inventory and the build evidence shipped beside the executable.

## Dependency reproducibility

### Locked builds and artifact checks

Official build jobs install one [native uv lock](docs/DEPENDENCIES.md) in a clean
virtual environment, using the commit-pinned setup action and uv 0.13.5.
Registry artifacts have lock hashes, isolated builds require hashed constraints,
and the Open Movement reader is pinned to its full Git commit. Native
lock/sync/check commands reject stale inputs and environment drift.

Manifest generation requires an audit covering the same installed package/version
set. The download includes `security/uv.lock`, `security/build-info.json` and
`security/dependency-audit.json`. Release preparation compares that evidence with
the tagged Windows dependency graph, including the reader's source revision,
before checking the complete file inventory and uploaded asset digests.

The [dependency guide](docs/DEPENDENCIES.md#audit-and-artifact-evidence) owns the
audit commands and evidence format. The installed-package inventory describes
the build environment, including development/build tools; the separate checksum
inventory describes the actual shipped files.

### Reviewed advisory exception

The existing exception concerns **PyArrow 22.0.0** and
**CVE-2026-25087 / PYSEC-2026-113**. The published candidate's audit recorded two
entries for that issue. The [advisory](https://github.com/advisories/GHSA-rgxp-2hwp-jwgg)
excludes Python bindings; its affected C++ IPC API is not used here. ParaDigMa
constrains Arrow below the fixed release.

The [audit policy](scripts/audit_dependencies.py) permits only this
package-specific issue, including its advisory aliases; other findings and
unexpected package skips block verification. Studio itself is checked against
its tagged first-party source rather than audited as a PyPI release. The
candidate retained the existing exception; no C++ patch is claimed.

## Distribution and remaining limits

### Signing and workflow permissions

The published candidate is **unsigned**. The [publisher-signing guide](SIGNING.md)
describes the separate manual workflow and account setup. A checksum or CI receipt
identifies checked content or publication status; it does not replace a publisher
signature or certify every dependency's behavior.

Actions commits are pinned. In the [release workflow](.github/workflows/windows.yml),
release/status jobs receive tag-scoped conditions and write permission; the
status job retains checkout credentials to push its Git receipt. OIDC permission
is confined to the environment-gated signing job in the
[signed-build workflow](.github/workflows/windows-signed.yml), with application
execution checked in a separate job without signing credentials.

### Remaining verification and runtime limits

- **Windows acceptance:** a manual clean-machine run, Defender scan, actual
  publisher signing, certificate-chain verification and Smart App Control
  acceptance are not claimed. The [candidate checklist](docs/RELEASE_CANDIDATE.md#windows-verification-and-acceptance)
  records that work separately from CI execution and ZIP inspection.
- **Resource exhaustion:** malformed or large inputs can exhaust resources;
  parsers have not been fuzz-tested. CPU/RAM estimates and individual cache
  budgets do not impose an application-wide memory limit.
- **Abrupt termination:** workers or temporary data can remain after a crash or
  forced exit. Normal cleanup does not provide secure erasure.
- **Review scope:** instrumented network isolation and an exhaustive dependency
  source audit remain outside the recorded checks.

Scientific and workload limitations are maintained separately in the
[candidate record](docs/RELEASE_CANDIDATE.md#candidate-limitations).
