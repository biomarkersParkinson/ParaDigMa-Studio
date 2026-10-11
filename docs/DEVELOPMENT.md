# Development and building

Use Python 3.12 and Git. The dependencies pin official ParaDigMa 1.1.2 and an
official Open Movement reader revision compatible with NumPy 2 CWA timestamps.

The Python distribution and launcher are `paradigma-studio`; the importable
package and its `_internal` folder are `paradigma_studio`. New user data goes to
`%LOCALAPPDATA%\ParaDigMaStudio`. Existing history and result locations under
`ParaDigMaDesktop` remain usable without moving files or changing stored paths.

## Run from source on Windows

Clone the repository and run these commands in PowerShell:

```powershell
git clone https://github.com/lucevers1991/ParaDigMa-Studio.git
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
Fresh-process startup tests check both the empty workspace and saved run history;
`benchmark_desktop.py` enforces the same import boundary in packaged builds.

The **Windows desktop** GitHub workflow runs style checks, tests and dependency auditing,
builds the application, launches the packaged executable away from the checkout,
and records startup measurements, package versions, source commit and checksums.
Artifacts include the app folder, a separate JUnit test report, and
`ParaDigMaStudio-build-reports` for performance measurements. Benchmarks write
to `build-reports/`, outside the distributable app. Security provenance,
dependency audit results and checksums remain with the app. These checks
do not replace a publisher signature.

## Run development checks on Linux

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade 'pip>=26.2,<27'
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m ruff check src scripts tests desktop.py
.venv/bin/python -m ruff format --check src scripts tests desktop.py
.venv/bin/python -m mypy
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/paradigma-mpl .venv/bin/python -m pytest -q
.venv/bin/python desktop.py
```

The interactive launcher requires a graphical desktop. Use offscreen pytest and
the packaged probes for a headless cloud environment.

`python -m mypy` checks `contracts`, `core`, `recordings`, `history`, `jobs`,
`analysis_process` and `serialization`. This is a lenient starting point:
annotated functions are checked, while unannotated helpers and UI code can be
typed incrementally. Extend the file list in `pyproject.toml` as coverage grows.
Shared contracts type frames, paths, pipeline names, worker callbacks and process
messages; extensible ParaDigMa payloads and upstream forwarding arguments retain
`Any`. pandas stubs are development dependencies. Keep scientific type imports
under `TYPE_CHECKING`; the packaged `py.typed` marker exposes available annotations
to callers without adding startup imports.

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

Public fixture provenance and licenses are under `src/paradigma_studio/data/`
and `tests/data/paradigma/`. No patient data or external fixture download is needed.

See the [repository map](REPOSITORY.md) for folder and module responsibilities
and the [test suite guide](TEST_SUITE.md) for coverage, shared fixtures and
regression-test maintenance.

Read the [performance guide](PERFORMANCE.md) before changing import timing or
bundle exclusions. Runtime optimization must preserve native libraries, model
assets, supported formats and scientific output.
