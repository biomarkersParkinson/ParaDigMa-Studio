# Security review

Reviewed **16 October 2026**, ParaDigMa Studio **0.6.0a2**,
[source commit `81f2887`](https://github.com/biomarkersParkinson/ParaDigMa-Studio/commit/81f28876f181ecdca4e0c08d9696b7299d014410).
Scope: Linux source, dependencies and build/release/signing workflows; no current
packaged executable examined. [Evidence](docs/security-review.json) records details
and limitations. This is not a security certification.

## Verification

- **Dependencies:** 94 packages audited; no skipped packages or blocking findings
  under the PyArrow exception below. `pip check` passed.
- **Bandit:** 74 files; 0 high, 5 medium and 17 low-severity items, all reviewed;
  no scan errors/suppressions. Medium items concern private worker pickle transfers.
- **Tests:** 178 security-focused tests passed; one Windows-only test skipped.
  The full suite for the same source tree passed **870 tests**, with one skip,
  including scientific comparisons, source smoke testing and startup checks.

## Safeguards and trust boundaries

| Area | Current behavior |
| --- | --- |
| Input | Pickle requires explicit trust; accepted files and bundled models can execute code. Result JSON reopening loads neither pickle nor original recordings. |
| Saved data | Plaintext results/history under `%LOCALAPPDATA%\ParaDigMaStudio\runs`, or the legacy folder. No app encryption, authentication or tamper detection. Original recordings are not copied into saved runs. |
| Diagnostics | Worker tracebacks, paths and error details may identify recordings/subjects. Logs have no automatic redaction. |
| Files | Atomic writes; known-input/alias protection, including TSDF time/value files; CSV formula-text protection. Deletion requires confirmation, defaults to Cancel and protects inputs, directories and shared outputs. History is trusted local metadata. |
| Workers | At most two recording workers using CPU/RAM estimates; cleanup on Stop/normal failure. Estimates are not hard limits; workers are not a sandbox. |
| Network | No automatic recording upload or telemetry in the wrapper. Documentation links open a browser. |

## Dependencies and distribution

PyArrow 22.0.0 has two audit entries for **CVE-2026-25087 / PYSEC-2026-113**.
The [advisory](https://github.com/advisories/GHSA-rgxp-2hwp-jwgg) excludes Python
bindings; its vulnerable C++ IPC API is not used here. ParaDigMa constrains Arrow
below the fixed release. CI excludes only this issue; no C++ patch is claimed.

Runtime versions and Actions commits are pinned; transitive/build dependencies lack
full hash locking. Tag-only release/status jobs have write permission; status-job
checkout credentials push Git notes. OIDC is confined to the environment-gated signing
job. Ordinary builds are unsigned; [publisher signing](SIGNING.md) requires a verified
identity. Release checks cover source, version, inventory and uploaded hashes;
hashes alone do not establish publisher trust.

## Remaining limitations

Malformed/large files can exhaust resources; parsers were not fuzz-tested. Abrupt
termination may leave workers/temporary data; deletion is not secure erasure.
Protect sensitive results/logs with OS permissions and disk encryption. Network
isolation, Windows malware scans, publisher signing, certificate chains and Smart
App Control acceptance were not verified.
