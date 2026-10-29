# Development and building

This guide takes a contributor from a fresh checkout to running, checking and
building Studio. It describes the current source on `main`. Start with
[Contributing](../CONTRIBUTING.md) for issue reports and pull-request expectations.

- [Set up the environment](#set-up-the-environment)
- [Run the app](#run-the-app)
- [Run development checks](#run-development-checks)
- [Build and verify a Windows executable](#build-and-verify-a-windows-executable)
- [Quality gates and implementation conventions](#quality-gates-and-implementation-conventions)
- [Type checking](#type-checking)
- [Refresh user guide screenshots](#refresh-user-guide-screenshots)
- [CI artifacts](#ci-artifacts)
- [Troubleshooting](#troubleshooting)

## Set up the environment

| Requirement | Project expectation |
| --- | --- |
| Platform | Windows x64 for the distributed app; Linux x64 for supplemental development checks |
| Python | 3.12.10, selected by `.python-version` and the Windows workflows |
| uv | 0.13.5, enforced by `tool.uv.required-version` in `pyproject.toml` |
| Git | Available on `PATH` for the checkout and the pinned Open Movement dependency |

Install the pinned uv version using its [official instructions](https://docs.astral.sh/uv/getting-started/installation/).
uv can download the selected Python interpreter if it is not installed. The
[dependency guide](DEPENDENCIES.md) owns the reviewed platform requirements,
scientific pins, audit policy and update procedure.

Run the following in PowerShell on Windows or Bash on Linux:

```sh
git clone https://github.com/biomarkersParkinson/ParaDigMa-Studio.git
cd ParaDigMa-Studio
uv lock --check
uv sync --locked --all-groups
uv sync --locked --all-groups --check
```

The sync creates `.venv`, installs Studio in editable mode and includes the
pinned test, lint, type-checking and build tools. Keep this environment dedicated
to the project. Source edits are available without reinstalling the package.

Run all remaining commands from the repository root. `uv run --locked --all-groups`
selects the project environment and synchronizes it when needed; activating the
virtual environment is optional. `uv sync --locked --all-groups --check` verifies
its state without repairing it. Dependency changes follow the
[deliberate update procedure](DEPENDENCIES.md#update-deliberately).

## Run the app

```sh
uv run --locked --all-groups python desktop.py
```

The interactive app needs a graphical desktop. For a headless Linux session,
use the tests and executable probes below. A local source launch uses the normal
Studio user-data directory; the tests use their isolated fixtures. See the
[storage reference](PYTHON_API.md#storage-and-analysis-time-identity) before
using personal run history during development.

`paradigma-studio` is the Python distribution and installed GUI command;
`paradigma_studio` is the importable package. The portable build has its own
`_internal` runtime directory beside the executable.

## Run development checks

### During development

Run the tests for the behavior you changed. For example:

```sh
uv run --locked --all-groups python -m pytest -q tests/test_analysis_settings.py
```

The [test guide](TEST_SUITE.md) maps features to their tests. Preparation,
processing and output changes also need the independent
[scientific comparisons](SCIENTIFIC_TESTS.md). Packaging changes need a built
executable check. Documentation changes use the separate
[Markdown and link checks](../CONTRIBUTING.md#documentation-checks).

### Before submitting

Check the environment before commands that might synchronize it, then run the
same source guards, lint and type checks used by Windows CI:

```sh
uv sync --locked --all-groups --check
uv run --locked --all-groups python scripts/check_module_size.py
uv run --locked --all-groups python scripts/check_workspace_facade.py
uv run --locked --all-groups python -m ruff check src scripts tests desktop.py
uv run --locked --all-groups python -m ruff format --check src scripts tests desktop.py
uv run --locked --all-groups python -m mypy
```

To apply formatting while editing:

```sh
uv run --locked --all-groups python -m ruff format src scripts tests desktop.py
```

Run the complete test suite with the configured branch-coverage gate before
merging code changes. In PowerShell:

```powershell
uv run --locked --all-groups python -m pytest --junitxml=test-results.xml --cov --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=html
```

For headless Linux checks, select offscreen Qt and a writable Matplotlib cache
for that command:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/paradigma-mpl uv run --locked --all-groups python -m pytest --junitxml=test-results.xml --cov --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=html
```

The test setup selects its configured offscreen screen when no Qt platform is
overridden. Windows CI explicitly selects offscreen Qt and runs the native
Analyze-layout and page-shortcut regressions before the full suite. Linux
checks supplement native Windows execution.

Read [coverage policy and reports](TEST_SUITE.md#branch-coverage) for the measured
scope, floor and output paths. Benchmark commands and interpretation belong in
[Performance](PERFORMANCE.md#reproduce-measurements).

## Build and verify a Windows executable

Build on Windows after the development checks pass. Close any running copy from
`dist/ParaDigMaStudio` first: the builder recreates that directory and
`build/desktop` from scratch, preserving other build directories.

```powershell
uv run --locked --all-groups python scripts/build_desktop.py
uv run --locked --all-groups python scripts/check_frozen.py dist/ParaDigMaStudio/ParaDigMaStudio.exe
```

The output is a portable folder at `dist/ParaDigMaStudio`. The check launches the
EXE from a temporary directory outside the checkout, checks the runtime layout
and notices, and runs real analysis, graph, saving and reopening smoke checks.
A source checkout cannot supply missing packaged resources during that launch.

Keep the entire folder together, including `_internal`, model assets, icons,
notices and required native libraries such as `vcomp140.dll` and `msvcp140.dll`.
Python modules are packaged without duplicate loose ParaDigMa or Open Movement
source files. Generated PyInstaller specs under `build/desktop` are build
outputs; `scripts/build_desktop.py` is the supported entry point.

To measure the built app's startup and size:

```powershell
New-Item -ItemType Directory -Force build-reports | Out-Null
uv run --locked --all-groups python scripts/benchmark_desktop.py dist/ParaDigMaStudio/ParaDigMaStudio.exe --report build-reports/performance.json
```

Keep benchmark reports outside the portable folder. Local building and smoke
checks do not create the complete dependency audit, build manifest and checksum
evidence. The [release workflow](RELEASES.md) generates and verifies that evidence
before publishing a download. Publisher signing has a
[separate workflow](../SIGNING.md).

### Supplemental Linux bundle

A Linux build produces a Linux executable. In a headless session:

```bash
uv run --locked --all-groups python scripts/build_desktop.py
QT_QPA_PLATFORM=offscreen uv run --locked --all-groups python scripts/check_frozen.py dist/ParaDigMaStudio/ParaDigMaStudio
```

Use the Windows workflow to validate the distributed EXE.

## Quality gates and implementation conventions

The configuration in `pyproject.toml` and the source guards define the enforced
limits. They apply independently:

| Check | Enforced limit |
| --- | --- |
| Python modules under `src/`, including `__init__.py` | At most 900 physical lines, including comments and blanks; no exemptions |
| McCabe complexity, `C901` | At most 10 per function |
| Statement count, `PLR0915` | At most 60 per function |
| Branch count, `PLR0912` | At most 12 per function |
| Internal workspace driver | Exact allowed ports and line budget in `scripts/workspace_facade_budget.json`; shrink-only |

Function lint rules cover source, scripts and tests. Both Windows workflows run
the module and driver guards before installing dependencies. Review functions
over 60 physical lines for separate responsibilities and aim for about 100 lines
or fewer. These length recommendations are review guidance; the enforced
function limits count complexity, statements and branches.

### Imports, lifecycle and error handling

Keep scientific, pandas/Arrow and Matplotlib imports deferred until needed.
Initialize the font cache before plotting imports and reuse graph canvases.
Preserve the justified `isort: split` boundary in `app.py`. GUI changes belong on
the Qt thread; preserve receiver affinity, signal ordering and worker cleanup.
The [architecture guide](ARCHITECTURE.md) explains component ownership and the
[repository conventions](REPOSITORY.md#conventions-for-changes) describe wiring.

Catch specific exceptions for expected input and filesystem failures. Broad
catches belong at job/UI boundaries or independent toolbox operations that
retain partial results. Preserve the original traceback in the processing log
or probe report, separately from concise notices and structured error counts.

Ruff checks imports, common errors, modernization, bugbear, comprehensions and
simplification as well as the limits above. Keep suppressions line-scoped and
explain the boundary reason nearby. `BLE001` exemptions are needed where Ruff
cannot recognize intentional Qt/queue/report-based traceback delivery;
recognized logging calls and cleanup handlers that re-raise need no exemption.
`RUF100` rejects unused suppressions. Immutable `QModelIndex()` defaults remain
allowed for Qt model method signatures.

### Internal workspace driver

`ui/compatibility.py` exposes implementation-coupled ports for tests, probes and
benchmarks. Application code uses explicit component owners. Keep useful ports
and the historical filename; the driver has no public API stability guarantee.

When removing a port, remove its budget entry and lower the line budget to match.
New aliases, returning retired names and file growth fail the guard. Changing
this shrink-only policy needs a separate review. Preserve deferred callbacks
and real Qt receivers when migrating callers. The
`test_composition_without_facade.py` regressions exercise the app without the
port decorator; `ui/component_ports.py` owns the reusable descriptor.

## Type checking

Run `uv run --locked --all-groups python -m mypy` from the repository root.
The authoritative scope and overrides are in `[tool.mypy]` in `pyproject.toml`;
the guide does not duplicate the changing target-file list.

| Scope | Policy |
| --- | --- |
| Configured targets | Check function bodies, including unannotated functions; reject incomplete signatures and unused ignores |
| Selected controllers and supporting services | Require complete function annotations with `disallow_untyped_defs` |
| Stronger service overrides | Also require explicit generic arguments and reject returning `Any` from concretely typed functions |
| Recursive `ui/` target | Check bodies while signatures are annotated incrementally; new UI modules join automatically |

For a new service/controller target, add the file to the configured `files` list.
Apply stronger overrides when its annotations are complete. Keep callback
protocols and frozen views explicit, use read-only `Mapping` inputs when no
mutation is needed, and retain runtime validation of externally loaded data.
Dynamic Qt payloads and extensible metadata retain `Any` at their boundaries.
Keep scientific and plotting type imports under `TYPE_CHECKING` to preserve lazy
startup; the packaged `py.typed` marker exposes available annotations to callers.

The normal mypy target includes `tests/typing/preparation_contracts.py`, which
checks valid calls and expected errors for unsupported units, axes, signals and
keywords. Runtime and scientific comparisons remain separate checks. On Linux,
check Windows-specific typing with:

```sh
uv run --locked --all-groups python -m mypy --platform win32
```

See the [preparation boundary](ARCHITECTURE.md#preparation-and-input-contracts)
and [API reference](PYTHON_API.md) for service behavior and persisted contracts.

## Refresh user guide screenshots

```sh
uv run --locked --all-groups python scripts/capture_user_guide.py
```

The script captures all four pages and supporting graph views through one real
analysis of the bundled public Axivity example. Input copies, history and saved
results use temporary storage. Inspect the complete set and update captions and
[capture notes](images/user-guide/README.md) when controls or selections change.
Keep the guide's released/current-source distinction when updating screenshots.

## CI artifacts

The ordinary **Windows desktop** workflow checks the lock and environment,
audits dependencies, runs source checks and tests, builds and launches the EXE,
measures performance and verifies the final download layout. The separate
**Documentation** workflow runs Markdown and local-link checks.

| Ordinary Windows artifact | Contents |
| --- | --- |
| `ParaDigMaStudio-Windows` | Complete portable app, notices, security evidence and checksums |
| `ParaDigMaStudio-test-results` | JUnit and configured branch-coverage reports |
| `ParaDigMaStudio-dependency-reports` | Installed inventory and dependency-audit report |
| `ParaDigMaStudio-build-reports` | Benchmarks, separate from the application folder |

See [Releases](RELEASES.md) for tag-driven publication and
[Security](../SECURITY.md) for provenance and trust boundaries. Passing build
checks does not replace publisher signing or manual Windows acceptance.

## Troubleshooting

| Symptom | Check or next step |
| --- | --- |
| uv rejects its version | Check `uv --version` against the pinned version above; use the dependency guide's installation instructions. |
| Lock or environment check fails | Follow the [dependency update procedure](DEPENDENCIES.md#update-deliberately) for intended changes; preserve the lock freshness gate. |
| Import fails or a tool appears missing | Run from the repository root, sync all groups and use `uv run --locked --all-groups` to select the project environment. |
| Source launch has no visible window | Use a graphical desktop and check that `QT_QPA_PLATFORM` has not been left set to `offscreen`. Clear it with `Remove-Item Env:QT_QPA_PLATFORM` in PowerShell or `unset QT_QPA_PLATFORM` in Bash. |
| Matplotlib cannot write its cache in a restricted environment | Set `MPLCONFIGDIR` to a writable directory, as in the headless Linux example. |
| Windows build cannot replace its output | Close the executable running from `dist/ParaDigMaStudio` and retry the builder. |
| Packaged app fails but source launch works | Inspect `check_frozen.py` output and retain the whole portable folder, including `_internal`; check [packaging and release instructions](RELEASES.md). |
