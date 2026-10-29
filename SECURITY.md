# Security policy

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/biomarkersParkinson/ParaDigMa-Studio/security/advisories/new)
for suspected security vulnerabilities. Include the Studio version or source
commit, Windows version, affected file format or action, expected impact and
minimal reproduction steps. Use synthetic examples and remove identifying paths,
sensor recordings and subject information.

Keep exploit details and sensitive data out of public issues. If GitHub does not
show the private reporting option, open an issue requesting a private contact
route without describing the vulnerability. Ordinary bugs and scientific-output
questions can use the [bug-report form](https://github.com/biomarkersParkinson/ParaDigMa-Studio/issues/new?template=bug_report.yml).

## Supported versions

Security fixes target the latest published Studio release or prerelease and the
current `main` branch. Report the exact version or commit; older builds may need
updating to receive a fix. The published candidate is **1.0.0rc1**. Supported
saved-data formats follow the independent
[saved-run contract](docs/PYTHON_API.md#saved-run-contract).

## Release verification

The [26 October 2026 verification record](docs/archive/security-review-1.0.0rc1-2026-10-26.md)
and [machine-readable evidence](docs/archive/security-review-1.0.0rc1-2026-10-26.json)
identify the published candidate's source, Windows workflow, checked ZIP,
dependency inventory and supplemental Linux checks. These are dated findings,
not a security certification or a fresh audit of every later commit. The
[18 October manual review](docs/archive/security-review-0.6.0a3-2026-10-18.json)
retains its original scope and limitations.

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
| Saved formats | History and result JSON follow the [current saved-run contract](docs/PYTHON_API.md#saved-run-contract). Unsupported versions are reported, without migration or discovery of the former ParaDigMaDesktop storage directory. |
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
