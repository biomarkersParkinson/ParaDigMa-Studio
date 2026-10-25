# Reviewed dependency environment

Use **uv 0.13.5** and Git. Install uv using its
[standard installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
CI uses a commit-pinned `astral-sh/setup-uv` action with that exact version;
`tool.uv.required-version` enforces it locally too.

`uv.lock` is the sole dependency lock. `.python-version` pins Python 3.12.10 for
the Windows build and normal development setup. The reviewed lock environments
are Python 3.12 on Windows x64 and Linux x64; the supplemental Linux checks use
glibc 2.34 or newer. General package Python compatibility remains in `project`.

## Install and verify

From the repository root:

```sh
uv lock --check
uv sync --locked --all-groups
uv sync --locked --all-groups --check
uv pip list --format json
```

uv creates `.venv`, installs Studio editable and the declared dependency groups,
and removes packages outside the selected graph. Use a dedicated project
environment. `--locked` rejects stale lock inputs instead of updating the lock;
`--check` verifies synchronization without changing the environment. `uv pip check`
only checks dependency compatibility and is not a substitute for the lock check.

Registry artifacts have native lock hashes. The patched Open Movement reader is
one normal Git dependency at its full immutable commit; its same-numbered PyPI
release is not a substitute. uv manages the Git source and Studio together, so
an unchanged sync does not uninstall/reinstall either package.

Development, audit and build tools live in the standard `dev` dependency group.
The installer itself runs outside this environment. The scientific version
policy is `tool.uv.constraint-dependencies`. Hashed
`tool.uv.build-constraint-dependencies` constrain isolated builds of Studio and
the Git reader; `require-build-hashes` makes missing build hashes an error.
uv records those constraints and hashes in `uv.lock`.

The pinned uv version enables its `build-dependency-hashes` and `json-output`
preview features explicitly. Revalidate these interfaces during a uv upgrade.

## Update deliberately

1. Edit the relevant dependency group, direct requirement or build/scientific
   constraint in `pyproject.toml`. For a pinned uv upgrade, update
   `required-version` and both CI installer versions together.
2. Run `uv lock`. Existing versions remain preferred. Use
   `uv lock --upgrade-package NAME` for a deliberate transitive upgrade;
   direct pins/constraints must also permit the new version.
3. Review the lock diff, Git source and distribution/build hashes. App-version
   bumps also refresh the root project entry with `uv lock`; they do not require
   upgrading dependencies. Commit the metadata and lock together.
4. Sync a clean environment and run auditing, style/types, the complete suite
   with scientific comparisons, and the packaged executable checks. Verify
   Windows and Linux inventories when changing cross-platform dependencies.

Do not use `--frozen` as the build freshness gate: it intentionally bypasses
checking whether project metadata changed. Do not use `--inexact` for reviewed
builds. Locking fixes dependency choices, not operating-system/compiler details
or every executable byte.

## Audit and artifact evidence

```sh
uv run --locked --all-groups python scripts/audit_dependencies.py dependency-audit.json
```

pip-audit enumerates the installed environment and produces its normal JSON
report. The small policy adapter retains raw findings, accounts for Studio as
first-party source, rejects unexpected skipped packages and permits only the
documented package-specific PyArrow/CVE exception. It does not generate another
requirements file or resolve a second environment. No new exception is added.

The app ships `security/uv.lock`, `dependency-audit.json` and `build-info.json`.
The manifest records installed versions, source commit, actual uv version,
native lock hash and installed Git URL/revision. Before writing it, native
`uv sync --locked --all-groups --check` verifies the build environment and the
adapter checks that the audit covers that same inventory.

Release preparation uses native `uv tree --locked --format json` to select the
Windows graph, including development/build tools, from the tagged source. It
compares the shipped lock, Python/uv identity, actual package versions and Git
sources, matching audit, and complete file hash inventory. A passing local sync
does not replace these checks on the actual published ZIP.

Audits use current advisory data, so an unchanged lock may later need an update.
Package/version advisories do not attest that arbitrary Git source is safe;
the immutable reader commit and its source provenance are retained separately.

The [original supplied Windows baseline](dependency-baseline.json) is historical
evidence. Migration to the native lock preserved every selected package version,
with uv moved out of the application environment into the pinned installer.
