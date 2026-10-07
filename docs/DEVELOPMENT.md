# Development and building

Use Python 3.12 and Git. The dependencies pin official ParaDigMa 1.1.2 and an
official Open Movement reader revision compatible with NumPy 2 CWA timestamps.

## Run from source on Windows

Clone the repository and run these commands in PowerShell:

```powershell
git clone https://github.com/lucevers1991/ParaDigMa4DBS.git
cd ParaDigMa4DBS
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
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/build_desktop.py
.\.venv\Scripts\python.exe scripts/check_frozen.py dist/ParaDigMaDesktop/ParaDigMaDesktop.exe
.\.venv\Scripts\python.exe scripts/benchmark_desktop.py dist/ParaDigMaDesktop/ParaDigMaDesktop.exe --report performance.json
```

Distribute the entire `dist\ParaDigMaDesktop` folder. The portable executable
depends on `_internal`. The build includes model assets, SVG icons and native
scikit-learn runtime libraries, including `vcomp140.dll` and `msvcp140.dll`.
The build also places the ParaDigMa acknowledgement, licence and citation files
beside the executable; keep these with any redistributed bundle.

The **Windows desktop** GitHub workflow runs tests and dependency auditing,
builds the application, launches the packaged executable away from the checkout,
and records startup measurements, package versions, source commit and checksums.
Artifacts include the app folder and a separate JUnit test report. These checks
do not replace a publisher signature.

## Run development checks on Linux

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade 'pip>=26.2,<27'
.venv/bin/python -m pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/paradigma-mpl .venv/bin/python -m pytest -q
.venv/bin/python desktop.py
```

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
background error handling, navigation, filters, graph/table values, presentation
controls, history and exports. The frozen-app check loads bundled classifiers,
runs real pipelines, renders graphs and reopens exported results.

Public fixture provenance and licenses are under `src/paradigma_desktop/data/`
and `tests/data/paradigma/`. No patient data or external fixture download is needed.

See the [repository map](REPOSITORY.md) for folder and module responsibilities.

Read the [performance review](PERFORMANCE.md) before changing import timing or
bundle exclusions. Runtime optimization must preserve native libraries, model
assets, supported formats and scientific output.
