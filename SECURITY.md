# Security review

Reviewed **11 October 2026**, ParaDigMa Studio **0.5.32**, commit `9b5b228`.
Scope: application, build/signing workflows, installed dependencies and the local
Linux bundle. This focused review is not a security certification.

## Verification

- **Dependencies:** pip-audit checked 87 packages, with no skipped packages or
  blocking findings under the policy below. `pip check` passed.
- **Source scan:** Bandit found 0 high, 2 medium and 16 low-severity items;
  no scan errors or suppressed checks. The medium items are private pickle
  transfers to/from the owned analysis process. Low items concern pickle imports
  and developer subprocess/tool-path usage. All findings were reviewed.
- **Tests:** 81 passed; one Windows-only signature test skipped. The packaged
  Linux probe passed, including classifiers, analyses, exports and saved-result reopening.

[Structured evidence](docs/security-review.json) records versions, findings and
outcomes. The [older review](docs/archive/security-review-2026-10-06.md) is archived.

## Safeguards and trust boundaries

| Area | Current behavior |
| --- | --- |
| Input | Pickle is rejected unless explicitly trusted; confirmed pickle and bundled models can execute code. Result JSON reopening does not load pickle or automatically reopen recordings. |
| Writes | Atomic exports/snapshots protect existing destinations after failed writes. Known inputs, TSDF companions and filesystem aliases are protected. CSV formula-like text is prefixed; spreadsheet import behavior still matters. |
| Persistence | History, paths, logs and complete saved results persist as plaintext under `%LOCALAPPDATA%\ParaDigMaStudio\runs`. Legacy history remains usable; original recordings are not copied. |
| Deletion | Single/bulk deletion and Clear all require confirmation, defaulting to Cancel. Listed outputs are permanently removed; inputs, directories and outputs shared with retained runs are protected. |
| Analysis | Stop terminates only the owned child; temporary files are cleaned after success, failure or cancellation. Process separation is not a security sandbox. |

The reviewed wrapper has no automatic recording-upload, elevation or registry/service
installation functionality. Documentation links open an external browser. Build
commands use argument lists without a shell; trust the installation and toolchain.

## Dependency exception

The audit reports **CVE-2026-25087 / PYSEC-2026-113** twice for pyarrow 22.0.0.
The [advisory](https://www.cve.org/CVERecord?id=CVE-2026-25087) concerns a C++ IPC
pre-buffering API and explicitly excludes Python bindings. The app uses Python
Parquet loading; ParaDigMa 1.1.2 requires Arrow below the fixed C++ release.
CI retains this specific exception and fails on other findings or skipped audits.
Reassess if usage/advisory changes; the bundled C++ library is not patched.

## Distribution and limitations

Primary dependencies and Actions commits are pinned; transitive versions are
audited and recorded, but not fully locked with artifact hashes. Checkout credentials
are not persisted; OIDC permission is confined to the signing job.
Ordinary builds are **unsigned**; [publisher signing](SIGNING.md) requires a verified identity.
Build provenance, dependency reports and `SHA256SUMS.txt` accompany the executable;
hashes establish agreement with the manifest, not independent publisher trust.

Windows signing, certificate chains, Smart App Control acceptance, Defender scans
and network isolation were not verified here. Native parsers were not exhaustively
audited or fuzz-tested; large/malformed files can exhaust resources, with no hard
memory/time limits. Local results/history are not encrypted or authenticated by the
app. Protect sensitive data with OS access controls. Keep Windows protections enabled,
run without elevation, and use a disposable VM/Sandbox for isolated testing.
