# Development and building

Use 64-bit Python 3.12 and Git, matching the Windows workflows. Dependencies pin
official ParaDigMa 1.1.2 and an official Open Movement reader revision compatible
with NumPy 2 CWA timestamps.

The Python distribution and launcher are `paradigma-studio`; the importable
package and its `_internal` folder are `paradigma_studio`. New user data goes to
`%LOCALAPPDATA%\ParaDigMaStudio`. Existing history and result locations under
`ParaDigMaDesktop` remain usable without moving files or changing stored paths.

## Run from source on Windows

Clone the repository and run these commands in PowerShell:

```powershell
git clone https://github.com/biomarkersParkinson/ParaDigMa-Studio.git
cd ParaDigMa-Studio
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2,<27"
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe desktop.py
```

Running through Python avoids the generated unsigned launcher, but Windows may
still check or block native dependencies. See [signing](../SIGNING.md) and
[security](../SECURITY.md).

## Build and verify a Windows executable

Build on Windows; a Linux build does not generate a Windows executable.

```powershell
.\.venv\Scripts\python.exe scripts/check_module_size.py
.\.venv\Scripts\python.exe -m ruff check src scripts tests desktop.py
.\.venv\Scripts\python.exe -m ruff format --check src scripts tests desktop.py
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/build_desktop.py
.\.venv\Scripts\python.exe scripts/check_frozen.py dist/ParaDigMaStudio/ParaDigMaStudio.exe
.\.venv\Scripts\python.exe scripts/benchmark_desktop.py dist/ParaDigMaStudio/ParaDigMaStudio.exe --report performance.json
```

Distribute the entire `dist\ParaDigMaStudio` folder. The portable executable
depends on `_internal`. The build includes model assets, SVG icons and native
scikit-learn runtime libraries, including `vcomp140.dll` and `msvcp140.dll`.
The build also places Studio's Apache 2.0 licence and the ParaDigMa
acknowledgement, licence and citation files
beside the executable; keep these with any redistributed bundle.
CI additionally generates the dependency audit, source/package provenance and
checksums; `build_desktop.py` alone does not create those security reports.

Builds recreate only `dist/ParaDigMaStudio` and `build/desktop` from scratch.
Python modules are packaged in the executable, without duplicate loose `.py`
files for ParaDigMa or Open Movement. Model assets, package metadata and native
dependencies are retained. The packaged check rejects leftover app versions
and unexpected files at the top of the app folder.

Both Windows workflows enforce the pinned Ruff formatter, error and import
checks, bugbear (`B`), comprehensions (`C4`), simplification (`SIM`) and Python
modernization (`UP`) rules, and a McCabe complexity limit of 10 (`C901`). They
also run mypy API checks. Split complex functions into cohesive helpers; keep
any rule-specific suppression narrow and explain its reason in a nearby comment.
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
python -m venv .venv
.venv/bin/python -m pip install --upgrade 'pip>=26.2,<27'
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/check_module_size.py
.venv/bin/python -m ruff check src scripts tests desktop.py
.venv/bin/python -m ruff format --check src scripts tests desktop.py
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/paradigma-mpl .venv/bin/python -m pytest -q
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

`python -m mypy` checks `contracts`, `core`, `recordings`, `history`, `jobs`,
`analysis_process`, `analysis_limits`, `parallel_analysis`, `recording_results`,
`serialization` and `epoch_profile`. This is a lenient starting point:
annotated functions are checked, while unannotated helpers and UI code can be
typed incrementally. Extend the file list in `pyproject.toml` as coverage grows.
Shared contracts type frames, paths, pipeline names, worker callbacks and process
messages; extensible ParaDigMa payloads and upstream forwarding arguments retain
`Any`. pandas stubs are development dependencies. Keep scientific type imports
under `TYPE_CHECKING`; the packaged `py.typed` marker exposes available annotations
to callers without adding startup imports.

## Python service APIs

Use these entry points for integrations without constructing the desktop window:

| Entry point | Input and return value |
| --- | --- |
| `core.load_sensor_file` | A supported file path → one original DataFrame; pickle requires `allow_pickle=True` |
| `recordings.load_recordings` | Paths → `(sources, frames)`, dictionaries sharing recording identifiers |
| `core.analyze` | One DataFrame or a dictionary of recordings plus `pipelines` → the result dictionary |
| `serialization.export_results` | Destination, results and provenance → a structured JSON export of the supplied outputs |
| `history.load_result_export` | Result JSON path → `(provenance, results)`, without loading sensor recordings |

`pipelines` accepts `gait`, `tremor`, `pulse_rate` or a sequence of those names.
`analyze` runs synchronously; GUI cancellation uses `analysis_process.run_isolated_analysis`
through the worker. Its multiple-recording path owns up to two spawned processes
directly and merges their outputs with official pooled aggregation functions.
One original recording uses the original single-process path even when its
preparation creates several gap sections. `max_workers=1` forces sequential
execution for profiling; it is an execution keyword, not an analytical setting.
Missing-sample exclusion defaults to **False** in the Python
API and **True** in the GUI. Pass all original recording paths through
`protected_sources` when exporting several recordings programmatically.
The `core` export aliases remain available for existing callers.

## Test setup and scientific checks

Headless UI tests configure a 1920×1080 virtual Qt screen using
`tests/data/qt-offscreen.json`. Qt's default 800×800 screen is smaller than the
app's minimum width and can clip visibility checks on Windows. Graph-workspace
tests use the same Fusion style as the shipped app and wait for layout updates.

The normal suite includes scientific equivalence tests. To run only those:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m scientific -q
```

See [scientific test methodology](SCIENTIFIC_TESTS.md) for independent references,
fixtures, tolerances and limits. App tests cover imports, preparation settings,
background error handling, navigation, selection, graph/table values, presentation
controls, history and exports. The frozen-app check loads bundled classifiers,
runs real pipelines, renders graphs and reopens exported results.

## Branch coverage

Both Windows workflows run the full suite with pinned `pytest-cov` and coverage.py.
The initial floor is **80%**, using coverage.py's combined percentage of executed
statements and branch outcomes. The report includes all `*_controller.py` modules
and these error boundaries: `analysis_process`, `core`, `jobs`, `parallel_analysis`,
`previews`, `recording_results` and `storage`. New controllers automatically join
the gate, including modules with no tests. Other Studio modules and the upstream
toolbox are outside this initial reporting scope; this is not whole-app coverage.
The source scope, branch mode and floor live in `pyproject.toml`.
The initial Linux full-suite baseline is 90.2% of statements and 76.5% of branch
outcomes, or 87.0% combined across 16 modules (893 tests passed, one skipped).

Run the same coverage check locally after installing `.[dev]`:

```bash
python -m pytest --cov --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=html
```

On a headless machine, set `QT_QPA_PLATFORM=offscreen` as in the Linux commands
above. XML is written to `test-reports/coverage.xml`; open
`test-reports/coverage-html/index.html` to inspect missing lines and branch exits.
Both reports are retained with JUnit in the CI test-results artifact, outside the
application bundle. Raw `.coverage*` data and generated reports are ignored by Git.

Coverage combines completed Python subprocesses and multiprocessing workers.
Forcibly terminated workers can exit before saving their measurements; direct
boundary tests complement real process/thread integration tests. Qt thread entry
points are also tested synchronously so their failure and cleanup paths are traced.
In particular, the low `recording_results` measurement undercounts merging inside
terminated workers; the real-process scientific comparisons still run.
Normal `pytest` runs keep coverage off for fast focused work. For a local partial
measurement, use `--cov --cov-fail-under=0`; the full CI run always enforces the
configured floor. Add behavior tests for missing error/recovery branches rather
than excluding them or lowering the floor. Coverage timings are not performance
benchmarks.

Public fixture provenance and licenses are under `src/paradigma_studio/data/`
and `tests/data/paradigma/`. No patient data or external fixture download is needed.

See the [repository map](REPOSITORY.md) for folder and module responsibilities
and the [test suite guide](TEST_SUITE.md) for coverage, shared fixtures and
regression-test maintenance.

Read the [performance guide](PERFORMANCE.md) before changing import timing or
bundle exclusions. Runtime optimization must preserve native libraries, model
assets, supported formats and scientific output.
