# Dependency management

This guide describes the current source on `main`: the reviewed environment,
dependency policy, update procedure and evidence shipped with a release.
Use [Development](DEVELOPMENT.md#set-up-the-environment) for a fresh checkout and
[Releases](RELEASES.md) for publication steps.

- [Reviewed environment](#reviewed-environment)
- [Dependency roles and pinning](#dependency-roles-and-pinning)
- [Install and verify](#install-and-verify)
- [Update deliberately](#update-deliberately)
- [Audit and artifact evidence](#audit-and-artifact-evidence)
- [Licences and attribution](#licences-and-attribution)
- [Historical baseline](#historical-baseline)

## Reviewed environment

| Requirement | Reviewed configuration |
| --- | --- |
| uv | **0.13.5**, installed outside the project environment |
| Python | **3.12.10** for the Windows build and normal development setup |
| Windows | x64, Python 3.12; target for the distributed executable |
| Linux | x64, Python 3.12, glibc 2.34 or newer; supplemental checks |
| Git | Available on `PATH` to fetch the pinned Open Movement source |

Install uv using its [official instructions](https://docs.astral.sh/uv/getting-started/installation/).
The exact uv version is enforced by `tool.uv.required-version` in
[`pyproject.toml`](../pyproject.toml). Both Windows workflows install it using a
commit-pinned `astral-sh/setup-uv` action.

[`.python-version`](../.python-version) selects the interpreter. The reviewed
platforms are declared in `tool.uv.environments`; general package Python
compatibility is declared separately in `project.requires-python`.

## Dependency roles and pinning

[`uv.lock`](../uv.lock) is the sole dependency lock. Edit requirements and policy
in `pyproject.toml`, then let uv update the resolved versions, sources and hashes.

- **Runtime requirements** (`project.dependencies`): ParaDigMa processing,
  PySide6 widgets, Matplotlib charts, native thread limits through `threadpoolctl`,
  and the Open Movement CWA reader.
- **Scientific constraints** (`tool.uv.constraint-dependencies`): preserve the
  reviewed NumPy, pandas, SciPy, scikit-learn and PyArrow versions.
- **Development tools** (`dependency-groups.dev`): test, coverage, lint,
  type-checking, audit and packaging tools.
- **Isolated build constraints** (`tool.uv.build-constraint-dependencies`):
  constrain setuptools, wheel and packaging versions and hashes for source builds.

The Open Movement reader is pinned to the full immutable Git commit declared in
the runtime requirements. That source fixes fractional CWA timestamp handling
with NumPy 2. Its same-numbered PyPI release does not contain the fix. uv manages
the reader and editable Studio installation together, so an unchanged sync
keeps both installed.

Registry artifacts have hashes in the lock. Isolated builds of Studio and the
Git reader use hashed build constraints; `require-build-hashes` rejects missing
build hashes. uv records those constraints and hashes in `uv.lock`.

The pinned uv version explicitly enables the `build-dependency-hashes` and
`json-output` preview features. Revalidate both interfaces during a uv upgrade.

## Install and verify

Run from the repository root, in PowerShell or Bash:

```sh
uv lock --check
uv sync --locked --all-groups
uv sync --locked --all-groups --check
uv pip list --format json
```

Sync creates `.venv`, installs Studio in editable mode and includes all declared
dependency groups. It also removes packages outside the selected graph, so use
a dedicated project environment. The final command prints the installed inventory;
CI saves it as `dependency-environment.json`.

When inspecting an existing environment, run the sync check before `uv run`,
which may synchronize the environment before executing its command.

| Check or option | Meaning |
| --- | --- |
| `uv lock --check` | Verify that the lock is current with project metadata |
| `uv sync --locked --all-groups --check` | Verify the environment against the lock without repairing it |
| `--locked` | Reject stale lock inputs instead of updating the lock |
| `uv pip check` | Check installed dependency compatibility; lock freshness and environment verification are separate checks |
| `--frozen` | Bypass lock freshness checking; unsuitable as the reviewed build gate |
| `--inexact` | Retain packages outside the selected graph; excluded from reviewed builds |

## Update deliberately

1. **Edit the declaration.** Change the relevant runtime requirement, dependency
   group or scientific/build constraint in `pyproject.toml`.
2. **Resolve the intended change.** Run `uv lock`; existing versions remain
   preferred. Use `uv lock --upgrade-package NAME` for a deliberate transitive
   upgrade. Direct pins and constraints must permit the requested version.
3. **Review the diff.** Check changed versions, Git sources and distribution/build
   hashes. Confirm that unrelated packages have retained their reviewed versions.
4. **Verify a clean environment.** Follow [Install and verify](#install-and-verify),
   then run the [dependency audit](#run-the-installed-environment-audit).
   Compare Windows and Linux inventories for cross-platform dependency changes.
5. **Validate behavior and packaging.** Run the
   [development checks](DEVELOPMENT.md#run-development-checks), complete suite with
   [scientific comparisons](SCIENTIFIC_TESTS.md), and
   [packaged executable checks](DEVELOPMENT.md#build-and-verify-a-windows-executable).
6. **Commit the metadata and lock together.** Include any corresponding installer
   or interpreter configuration changes and report the validation results.

For a **uv upgrade**, update `required-version` and every setup-uv installer
version in both [Windows](../.github/workflows/windows.yml) and
[signed Windows](../.github/workflows/windows-signed.yml) workflows together.
Recheck the enabled preview features. For a **Python upgrade**, keep
`.python-version`, workflow interpreter selections and reviewed platform markers
consistent with the intended environment.

An **app-version bump** also needs `uv lock` to refresh Studio's root project
entry; it does not require upgrading dependencies. The lock fixes dependency
choices. Operating-system/compiler details and executable bytes can still vary
between builds.

## Audit and artifact evidence

### Run the installed-environment audit

Check the environment, then audit the installed packages:

```sh
uv sync --locked --all-groups --check
uv run --locked --all-groups python scripts/audit_dependencies.py dependency-audit.json
```

[`audit_dependencies.py`](../scripts/audit_dependencies.py) invokes pip-audit on
that environment and retains its raw JSON findings. The policy adapter:

- Treats Studio as first-party source, whose revision is checked during release
  verification.
- Rejects unexpected skipped packages and unresolved findings.
- Classifies only the documented, package-specific PyArrow exception for
  **CVE-2026-25087**, including advisory aliases. The rationale is maintained in
  [Security](../SECURITY.md#dependency-reproducibility).

This command audits the installed graph without creating another requirements
file or resolving a second environment. Advisory data can change while the lock
stays unchanged, so rerun the audit for release preparation. Git source provenance
and review remain separate from package/version advisory checks.

### Evidence included in the portable folder

Paths below are relative to the distributed `ParaDigMaStudio` folder:

| File | Evidence |
| --- | --- |
| `security/uv.lock` | The native dependency lock used for the build |
| `security/dependency-audit.json` | Installed-package audit, raw findings and policy classifications |
| `security/build-info.json` | Source commit, Python/uv versions, installed package versions, lock hash and installed Git URLs/revisions |
| `SHA256SUMS.txt` | Hash inventory of the complete shipped file set, excluding the inventory itself |

[`write_build_manifest.py`](../scripts/write_build_manifest.py) first runs
`uv sync --locked --all-groups --check` against the build's actual virtual
environment. It then verifies that the audit covers the same installed
package/version inventory before writing the evidence.

The package inventory describes the build environment, including development and
build tools. The checksum inventory describes the files actually shipped.

### Release verification

[`prepare_release.py`](../scripts/prepare_release.py) selects the tagged Windows
dependency graph through uv's native JSON tree output, including all dependency
groups. It checks the shipped lock, source commit, Python/uv identity, installed
package versions and Git sources, matching audit, and complete file/hash inventory.

The [release workflow](RELEASES.md) also verifies uploaded asset digests before
publication. Checks on the release artifact complement local environment checks.
See [Security](../SECURITY.md#safeguards-and-trust-boundaries) for the trust boundaries.

## Licences and attribution

Studio uses [Apache License 2.0](../LICENSE); third-party components retain their
own licences and notices. Packaged Studio/ParaDigMa licence texts, research
citations and attribution live in the
[notice directory](../src/paradigma_studio/data/notices/) and are shown in About.
Review upstream licence and distribution requirements when changing dependencies.

## Historical baseline

The [original supplied Windows baseline](archive/dependency-baseline.json)
records the inventory used for dependency hardening. The native-lock migration
preserved those selected package versions and moved uv out of the application
environment into the pinned installer. Use the current lock and CI evidence to
review today's environment. Other dated records are in the
[archive index](archive/README.md).
