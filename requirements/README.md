# Reviewed dependency environments

Windows builds and source development use committed CPython 3.12 locks.
Windows build jobs pin Python 3.12.10. The supplemental Linux lock targets
x86-64/glibc 2.34 or newer; its Python patch version is recorded in verification.

The initial baseline is the owner's Windows Actions build at
`04b61d45ebf9868d40a7c739d21a4a3f69594a64`. Its supplied audit has no blockers
and the two existing PyArrow advisory entries. `windows-baseline.json` retains
its inventory, Git revision and supplied-report hashes. Its numerical versions
are preserved. The locks add the pinned installer/wheel builder and omit
preinstalled packages that are not project or development-tool dependencies.

| File | Purpose |
| --- | --- |
| `bootstrap.in` / `bootstrap.lock` | Exact uv compiler/installer and allowed distribution hashes. |
| `build.in` / `build.lock` | Complete hashed build-backend environment, also constraining isolated source builds. |
| `tools.in` | Installer, audit and build tools, combined with `pyproject.toml` and its dev extra. |
| `scientific-constraints.txt` | Explicit numerical-version policy; changes require scientific validation. |
| `windows-py312.lock` | Complete Windows x64 runtime, test and build dependencies. |
| `linux-py312.lock` | Supplemental Linux x64 development/test dependencies. |
| `lock-metadata.json` | Input fingerprint, targets, compiler version and hashes of all generated locks. |

Registry packages have exact versions and required SHA-256 hashes. The Open
Movement reader is installed separately without resolving dependencies, using the
full Git commit in `pyproject.toml`. Its installed URL/commit are checked; the
same-numbered PyPI release is not a substitute. Isolated source builds require
hashed dependencies from `build.lock`. Studio itself installs from the checkout,
without dependency resolution/build isolation, using that locked build backend.

## Install or verify

Create a dedicated environment with 64-bit Python 3.12, then run from the repo root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe scripts/sync_dependencies.py
.\.venv\Scripts\python.exe scripts/sync_dependencies.py --check --report dependency-environment.json
```

On Linux, use `python3.12 -m venv .venv` and `.venv/bin/python`. Sync removes
packages outside the selected lock; use a project-specific environment. It
refuses to sync the system interpreter. `--check` verifies without installing:
input/lock hashes, installed inventory/versions, Git source, Studio metadata and
`pip check`.

Both Windows workflows start with a fresh `.venv`. Audit and environment reports
are uploaded even if a later step fails. Manifest generation requires an audit
covering the same packages/versions; a stale or unrelated report is rejected.

`pyproject.toml` retains general library compatibility requirements. An arbitrary
`pip install -e '.[dev]'` is not the reviewed release environment. Locks fix
dependency choices, not every operating-system/compiler detail or executable byte.

## Update deliberately

1. Edit the relevant direct/tool/build input for exact requirements. Review
   `scientific-constraints.txt` before changing the numerical stack.
2. From the locked development environment, run:

   ```sh
   python scripts/lock_dependencies.py
   ```

   Existing pins are retained where compatible. Use repeatable
   `--upgrade-package NAME` options for transitive updates; direct pins and
   scientific constraints must permit the new version first. Compiler updates
   require changing `bootstrap.in` and `COMPILER_VERSION` in
   `scripts/dependency_lock.py`, then generating with that uv version.
3. Review both platform locks, source commits, hashes and metadata. The metadata
   stamp is written only after every resolution succeeds; partial updates fail
   verification. Commit inputs, locks and metadata together.
4. Sync clean environments; run the audit, style/type checks, complete tests with
   independent scientific comparisons, and packaged probes. Publish updates in a
   new release, preserving already published assets.

App-version-only bumps do not invalidate the dependency fingerprint; reinstall
Studio to refresh its own metadata. Requirement changes do invalidate it.
Regeneration does not copy a developer's installed package inventory.
Lock files use LF through `.gitattributes`, and input fingerprints normalize
native text line endings so Windows checkouts do not create false drift.

## Evidence shipped with the app

`security/build-info.json` records installed versions, source commit, reader
revision and selected lock/input fingerprints. The bundle also contains
`dependencies.lock`, `build-dependencies.lock`, `dependency-lock.json` and
`dependency-audit.json` under `security/`, all covered by the file inventory.
Release preparation compares these against the tagged source, rejecting changed
versions, wrong locks and audits from a different environment.

Audits use current advisory data, so a previously clean lock can later need an
update. The exception remains limited to the documented PyArrow C++ issue whose
Python bindings are unaffected. Lock adoption adds no advisory exemptions.
