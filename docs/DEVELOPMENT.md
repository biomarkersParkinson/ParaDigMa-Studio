# Development and building

Use uv 0.13.5, 64-bit Python 3.12 and Git. Windows build jobs pin Python 3.12.10 and use a
complete dependency lock, including official ParaDigMa 1.1.2 and the Open Movement
reader revision compatible with NumPy 2 CWA timestamps. See the
[dependency policy and update procedure](DEPENDENCIES.md).

The Python distribution and launcher are `paradigma-studio`; the importable
package and its `_internal` folder are `paradigma_studio`. See the
[API and saved-run reference](PYTHON_API.md) for storage, provenance and persistence
contracts. Start with [Contributing](../CONTRIBUTING.md) for issue reporting and
pull-request expectations.

## Run from source on Windows

Clone the repository and run these commands in PowerShell:

```powershell
git clone https://github.com/biomarkersParkinson/ParaDigMa-Studio.git
cd ParaDigMa-Studio
uv sync --locked --all-groups
.\.venv\Scripts\python.exe desktop.py
```

Running through Python avoids the generated unsigned launcher, but Windows may
still check or block native dependencies. See [signing](../SIGNING.md) and
[security](../SECURITY.md).

## Build and verify a Windows executable

Build on Windows; a Linux build does not generate a Windows executable.

```powershell
uv sync --locked --all-groups --check
uv pip list --format json > dependency-environment.json
.\.venv\Scripts\python.exe scripts/check_module_size.py
.\.venv\Scripts\python.exe scripts/check_workspace_facade.py
.\.venv\Scripts\python.exe -m ruff check src scripts tests desktop.py
.\.venv\Scripts\python.exe -m ruff format --check src scripts tests desktop.py
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest --junitxml=test-results.xml --cov --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=html
.\.venv\Scripts\python.exe scripts/build_desktop.py
.\.venv\Scripts\python.exe scripts/check_frozen.py dist/ParaDigMaStudio/ParaDigMaStudio.exe
New-Item -ItemType Directory -Force build-reports | Out-Null
.\.venv\Scripts\python.exe scripts/benchmark_desktop.py dist/ParaDigMaStudio/ParaDigMaStudio.exe --report build-reports/performance.json
```

Distribute the entire `dist\ParaDigMaStudio` folder. The portable executable
depends on `_internal`. The build includes model assets, SVG icons and native
scikit-learn runtime libraries, including `vcomp140.dll` and `msvcp140.dll`.
The build also places Studio's Apache 2.0 licence and the ParaDigMa
acknowledgement, licence and citation files
beside the executable; keep these with any redistributed bundle.
CI additionally generates the dependency audit, source/package provenance,
lock evidence and checksums; `build_desktop.py` alone does not create those
reports. The manifest writer rejects environment drift and audit reports from a
different package/version set.

Builds recreate only `dist/ParaDigMaStudio` and `build/desktop` from scratch.
Python modules are packaged in the executable, without duplicate loose `.py`
files for ParaDigMa or Open Movement. Model assets, package metadata and native
dependencies are retained. The packaged check rejects leftover app versions
and unexpected files at the top of the app folder.

## Quality gates and implementation conventions

Both Windows workflows run the Analyze layout regression under the default and
classic Windows styles and the page-navigation keyboard regression before the
full test suite. This catches native control sizing and shortcut failures early;
the complete suite and coverage floor still run afterward. Keyboard tests wait
for the button's actual click signal with a bounded timeout, rather than assuming
its animation timer has fired after a fixed delay.

Both Windows workflows enforce the pinned Ruff formatter, error and import
checks, bugbear (`B`), comprehensions (`C4`), simplification (`SIM`) and Python
modernization (`UP`) rules. Functions are limited to McCabe complexity 10
(`C901`), 60 statements (`PLR0915`) and 12 branches (`PLR0912`) across source,
scripts and tests. Statement counts catch long, straight-line builders that a
complexity limit alone allows. Both workflows also run mypy API checks. Split
large or complex functions into cohesive helpers; keep any rule-specific
suppression narrow and explain its reason in a nearby comment.
Keep functions around 100 lines or fewer; statement and branch counts apply
independently of physical length.
Review functions over 60 physical lines for distinct responsibilities. Extract
cohesive phases with explicit inputs; declarative widget builders and callback
lists can remain longer when they read clearly.
Ruff rejects unused suppressions (`RUF100`). The documented immutable Qt
`QModelIndex()` default is allowed for native model method signatures.
Use `python -m ruff format src scripts tests desktop.py` to format changes. Keep
Qt platform initialization and Matplotlib cache configuration ahead of the
imports that depend on them. The justified `isort: split` boundary in `app.py`
keeps cache initialization ahead of plotting imports during automatic sorting.
Keep pandas/Arrow and scientific-stack imports deferred until data is needed.
Catch specific exceptions for expected input or filesystem failures. Broad catches
belong at job/UI boundaries or around independent toolbox operations that retain
partial results; preserve full tracebacks in the processing log or probe report.
Ruff's `BLE001` rule flags blind exception handlers. Where it cannot recognize
an intentional boundary's Qt, queue or report-based traceback propagation, use
a line-scoped `# noqa: BLE001` with the boundary reason. Keep the nearby explanation
of error delivery and recovery; avoid file-wide exemptions. Cleanup handlers that
re-raise and recognized `logger.exception` calls do not need exemptions. `RUF100`
rejects exemptions that become unnecessary after refactoring.
Keep diagnostic stacks separate from concise notices and structured error counts,
including when forwarding log records between recording workers and the GUI.
Keep Matplotlib imports and graph construction behind first use, and reuse the
created canvases. Fresh-process startup tests check the empty workspace, saved
run history and independent graph initialization; `benchmark_desktop.py` enforces
the same startup import boundary in packaged builds.

Every Python module (`*.py`, including `__init__.py`) under `src/` must contain
**at most 900 physical lines**, including comments, docstrings and blank lines.
Exactly 900 lines is allowed; a final line without a newline still counts.
Both Windows workflows run `python scripts/check_module_size.py` before installing
dependencies. The script reports every oversized module and exits with failure;
there are no exemptions. Extract cohesive components or helpers before reaching
the limit, preserving explicit dependencies and deferred imports.

`ui/compatibility.py` provides an internal workspace driver API for UI tests,
startup/smoke probes and benchmarks. Keep its historical filename. Automation
may use its declared widget/action ports; application code uses explicit owners.
These ports are coupled to UI implementation details and have no public API
stability guarantee. Keep useful ports; removing them is not a target by itself.
Choosing a stable supported driver contract requires a separate review.

The existing shrink-only budget guard remains in place:
`python scripts/check_workspace_facade.py`. Both Windows workflows run it before
installing dependencies. `scripts/workspace_facade_budget.json` lists the exact
driver ports and physical-line budget for `ui/compatibility.py`. When a port is
removed, remove its budget entry and lower the line budget to match; new aliases,
retired names returning, and file growth fail the check. Do not raise the budget;
any future policy change needs a separate review of the supported driver ports.
Preserve Qt signal ordering and job lifecycles when migrating callers. The reusable
component descriptor lives in `ui/component_ports.py`, outside the driver API.
MainWindow's composition must access widgets and callbacks through their explicit
layout/state/controller owners. `test_composition_without_facade.py` checks this
boundary and exercises loading, results and sensor context with the driver-port
decorator disabled. Preserve deferred lambdas and the real Qt receiver methods
when changing callback wiring.

See [Architecture](ARCHITECTURE.md) for component ownership, Analyze state,
graph interactions and worker lifecycles. The [repository map](REPOSITORY.md)
lists the implementing modules.

## CI artifacts

The **Windows desktop** GitHub workflow runs style checks, tests and dependency auditing,
builds the application, launches the packaged executable away from the checkout,
and records startup measurements, package versions, source commit and checksums.
Artifacts include the app folder, JUnit and branch-coverage test reports, and
`ParaDigMaStudio-build-reports` for performance measurements. Benchmarks write
to `build-reports/`, outside the distributable app. Security provenance,
dependency audit results and checksums remain with the app. These checks
do not replace a publisher signature.

## Run development checks on Linux

```bash
uv sync --locked --all-groups
.venv/bin/python scripts/check_module_size.py
.venv/bin/python scripts/check_workspace_facade.py
.venv/bin/python -m ruff check src scripts tests desktop.py
.venv/bin/python -m ruff format --check src scripts tests desktop.py
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/paradigma-mpl .venv/bin/python -m pytest --junitxml=test-results.xml --cov --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=html
.venv/bin/python desktop.py
```

The interactive launcher requires a graphical desktop. Use offscreen pytest and
the packaged probes for a headless cloud environment.

To check a Linux bundle in that environment:

```bash
mkdir -p build-reports
.venv/bin/python scripts/build_desktop.py
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/check_frozen.py dist/ParaDigMaStudio/ParaDigMaStudio
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark_desktop.py dist/ParaDigMaStudio/ParaDigMaStudio --report build-reports/performance.json
```

These commands verify a Linux executable; the Windows workflows verify the EXE.

## Refresh user guide screenshots

Run `python scripts/capture_user_guide.py` from the repository root with development
dependencies installed. It captures all four pages and the supporting graph views
from one real analysis of the bundled public Axivity example, using temporary
history and saved results. See the [capture notes](images/user-guide/README.md)
for image dimensions, provenance and platform details. Inspect the complete set
and update captions when controls or selections change; archived screenshots do
not describe the current interface.

## Type checking

`python -m mypy` checks function bodies throughout its configured scope, including
functions without annotated signatures (`check_untyped_defs = true`). It targets
`contracts`, `preparation_contracts`, `paradigma_api`, `core`, `recordings`, `history`, `jobs`,
`analysis_process`, `analysis_limits`, `parallel_analysis`, `recording_results`,
`analysis_progress`, `serialization` and `epoch_profile`, plus these controller
and service modules:

- `analysis_controller`, `data_controller`, `job_controller`, `result_controller`,
  `export_controller` and `shell_controller`;
- `workspace_state`, `result_data`, `result_preparation`, `result_reopening`,
  `previews`, `storage` and `exports`.

`inspection` is also checked at the lenient service level; its batch-inspection
interface is fully annotated.
The deferred `raw_signals` renderer and shared `time_navigation`/`raw_navigation`
controls are checked at the same lenient level.

`axis_mapping`, `column_mapping`, `input_metadata`, `analysis_limits`,
`preparation_contracts` and `paradigma_api` have
stronger per-module requirements: complete function annotations
(`disallow_untyped_defs`), explicit generic arguments such as `list[str]` rather
than bare `list` (`disallow_any_generics`), and warnings when a function with a
concrete declared return type returns `Any` (`warn_return_any`). These services
inherit the shared function-body checks and unused-ignore warnings.

The entire `ui/` directory is checked recursively, including new modules. Its
function bodies inherit the shared checking policy; the `paradigma_studio.ui.*`
override allows unannotated signatures (`disallow_untyped_defs = false`). Callback,
graphics and small-component public contracts are annotated; other UI signatures
can be completed incrementally. Scientific and plotting types stay under
`TYPE_CHECKING` to preserve deferred imports. Dynamic descriptor values retain
`Any` at their boundary; do not suppress whole UI modules or error categories.

The controller and supporting-service modules listed above require complete
function annotations (`disallow_untyped_defs`). Body checking also covers nested
helpers, including job operations, preview completion and export writers.
Callback protocols describe optional arguments and service dependencies; atomic
writes distinguish text and binary streams. Existing service signatures remain
gradual while their bodies are checked. Add service/controller targets to the
`files` list in `pyproject.toml`; apply the stricter override only
when a module has complete annotations. Additional UI modules need no new file
entry. Clock-summary inputs use read-only `Mapping` annotations so the stored
`ClockMetadata` contract can pass through without copying or conversion.

Data and analysis controller contracts describe single/batch recording-load
payloads, cached recording descriptives, clock previews and analysis launch inputs.
Their frozen views use concrete widget/graphics types, and callbacks declare their
arguments and results. The loader protocol retains keyword-only trust and logger
options. Loading still accepts a single frame with or without cached descriptives;
neither annotations nor type narrowing convert or copy source frames.

Extensible saved/display settings, provenance and results and the heterogeneous Qt
job-completion payload retain `Any`. Official adapter keywords are explicitly typed;
open dictionaries loaded from history still require runtime validation. pandas stubs are
development dependencies. Keep scientific type imports under `TYPE_CHECKING`;
the packaged `py.typed` marker exposes available annotations to callers without
adding startup imports.

The [architecture guide](ARCHITECTURE.md) explains preparation boundaries and
configuration ownership. The [API reference](PYTHON_API.md#saved-run-contract)
defines persisted run/result contracts.

## Tests and performance

Use the [test suite guide](TEST_SUITE.md) for headless setup, scientific checks,
coverage scope and reports, and shared test helpers. The full commands above
match the Windows coverage gate. The [scientific guide](SCIENTIFIC_TESTS.md) describes
independent reference outputs and numerical tolerances.

Read the [performance guide](PERFORMANCE.md) before changing import timing or
bundle exclusions. Runtime optimization must preserve native libraries, model
assets, supported formats and scientific output.
