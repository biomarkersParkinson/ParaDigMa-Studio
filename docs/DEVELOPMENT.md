# Development and building

Use uv 0.13.5, 64-bit Python 3.12 and Git. Windows build jobs pin Python 3.12.10 and use a
complete dependency lock, including official ParaDigMa 1.1.2 and the Open Movement
reader revision compatible with NumPy 2 CWA timestamps. See the
[dependency policy and update procedure](DEPENDENCIES.md).

The Python distribution and launcher are `paradigma-studio`; the importable
package and its `_internal` folder are `paradigma_studio`. User data goes to
`%LOCALAPPDATA%\ParaDigMaStudio`; earlier `ParaDigMaDesktop` storage is not
discovered. Saved history and result JSON require Studio format version 2.
Runs capture `studio_version`, `paradigma_version` and an available
`studio_build_commit` at creation. Frozen builds read the commit from their
`security/build-info.json`; source runs use the app checkout's Git HEAD.
Reopening and exporting use the recorded identity, never the current environment.
Standalone CSVs have a `<filename>.csv.metadata.json` companion with analysis
provenance and the CSV SHA-256; receipts track both files for safe deletion.

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

`ui/result_graphs.py` owns series rendering, axis reuse and viewport restoration.
`ui/result_graph_interactions.py` owns graph clicks, linked table selection,
selection markers and sensor-context availability. Both share the same explicit
view/state objects and `ResultPlotData`, including its existing cache. The renderer
keeps its callback entry points; interaction updates on an empty or unopened graph
must not initialize a canvas.

`ui/results_page.py` owns Results tabs, controls, its deferred result canvas and
frozen workspace/graph views, following the `DataPage`/`AnalysisPage` composition
pattern. `ResultsPageHost` supplies the parent, page layout and shared raw-channel
graph builder/accessor. `WorkspaceLayout` retains page composition and explicit
widget ports; it still builds the shared raw-data/sensor canvases. Constructing
the page or obtaining its views must leave both result and sensor canvases deferred.

`AnalysisPage` owns the info buttons and their non-modal `AnalysisHelpDialog`
windows. Opening one explanation closes the others without changing the form's
layout or scroll range. Dialogs reuse the existing explanation labels so
`FileDefaults` can update value sources while help is open. Long text and the
input-orientation figure scroll inside the window; Close, Escape and the native
close control dismiss it. New input and an accepted application close dismiss
open help; cancelling an application close preserves it. The controller view
exposes these windows for lifecycle cleanup rather than retaining inline-help
layout state or toggle callbacks.

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
`serialization` and `epoch_profile`, plus these controller and service modules:

- `analysis_controller`, `data_controller`, `job_controller`, `result_controller`,
  `export_controller` and `shell_controller`;
- `workspace_state`, `result_data`, `result_preparation`, `result_reopening`,
  `previews`, `storage` and `exports`.

`inspection` is also checked at the lenient service level; its batch-inspection
interface is fully annotated.
The deferred `raw_signals` renderer is checked at the same lenient level.

`axis_mapping`, `column_mapping`, `input_metadata`, `analysis_limits`,
`preparation_contracts` and `paradigma_api` have
stronger per-module requirements: complete function annotations
(`disallow_untyped_defs`), explicit generic arguments such as `list[str]` rather
than bare `list` (`disallow_any_generics`), and warnings when a function with a
concrete declared return type returns `Any` (`warn_return_any`). These services
inherit the shared function-body checks and unused-ignore warnings.

`preparation_contracts` defines supported signal names, signed axes, sensor units
and the six numeric time encodings. `PreparationSettings` describes preparation
keywords; the column mapping and missing-sample policy remain explicit `analyze`
arguments. The Analyze controller constructs these settings before adding the
open saved/display metadata. Qt combo values are narrowed at that boundary;
runtime column/axis/timestamp validation still handles external inputs.

`paradigma_api` provides typed lazy adapters for the pinned ParaDigMa 1.1.2 API.
`Unpack` constrains orchestrator and `analyze` keyword names and values without
injecting defaults into forwarded run options. Boundary casts account for
incomplete upstream annotations; they do not validate a recording's actual unit
or orientation. Adapter tests compare the pinned signatures/defaults and check
that supplied objects pass through unchanged. The normal mypy target also includes
`tests/typing/preparation_contracts.py`: valid calls must pass, and invalid units,
axes, signals and keywords must continue producing the expected type errors.
Scientific equivalence tests independently compare real preparation and pipeline
outputs with direct official calls. Raw/prepared frames and result schemas remain
unchanged.

The header-only `column_mapping` model and pure `axis_mapping` service are also checked; the Qt editor is covered
by the recursive UI target. Controllers supply column-name schemas once per
loaded batch and use the editor's explicit mapping/module APIs and `changed`
signal. Mapping validation never scans sensor samples. Run settings retain the
source-to-target dictionary for the explicit supported signal choices.
Run settings also store `signal_columns`, the complete canonical-signal to
source-column dictionary, with `null` for unassigned signals. These selections are
authoritative for preparation, validation and clock previews: unselected canonical
signal columns cannot supply fallback inputs. Selection metadata is restored
with the rest of the Analyze settings under one signal guard and is not
forwarded to ParaDigMa. Normal editor changes still emit one `changed` signal.
Direct Python API calls without `signal_columns` retain literal renaming
semantics. Original frames remain available for raw-data inspection.
`axis_inversions` stores inverted canonical IMU target channels separately. The
preparation service passes independent signed `x,y,z` lists to the official
accelerometer and gyroscope orientation calls after renaming; permutations belong
only in column mapping. This desktop setting is removed before calling the official
orchestrator. The Python `device_orientation` API remains supported when
`axis_inversions` is absent. Saved GUI settings require explicit selections and
inversions; global permutations and the retired preparation bypass are rejected.
Restoration validates the full settings before changing widgets and installs them
under one signal guard. The editor no longer preserves arbitrary extra mappings,
duplicate targets or redundant identity mapping entries.
Inversion edits do not emit the mapping `changed` signal because they affect
neither clock previews nor original raw plots.

GUI runs always use Studio's normal preparation path with the selected input
conventions. New GUI settings do not contain `skip_preparation`. The Python API
retains that option for explicit callers and their result interpretation.
After Studio prepares inputs, its internal call to the official orchestrator
still sets `skip_preparation=True` to prevent a second preparation pass.

Analyze separates file defaults, derived control state and origin-preview requests.
Its event handlers call the relevant operations directly:

| Event | Updates |
| --- | --- |
| Module selection | Required signals, watch-side relevance, run action and origin preview |
| Time-column edit on either page, other signal selection or Signal columns Default | File unit defaults, sensor-unit availability, origin preview and shared Data diagnostics/plots |
| Time-unit edit on either page or Time units Default | Shared value/provenance and origin preview; Data diagnostics/plots when the value changes |
| Acceleration/gyroscope unit edit or Default | Manual/file provenance; the input clock is unchanged |
| Gap-splitting switch | Availability of gap and minimum-section fields |
| Missing-sample policy | Origin preview |
| Input reset, saved parameters or job completion | One complete `AnalysisController.refresh` |

Input resets and saved-parameter restoration share a guarded settings operation.
It cancels superseded origin requests and blocks widget signals while modules,
units, mappings, policies and origins are installed. Named restoration helpers
apply each group; the controller refreshes once after the guard ends. Pending
preview results still follow the existing generation/key and manual-origin rules.

`AnalysisCallbacks.sync_input` publishes an immutable `TimeConfiguration` after
complete settings are available. It carries the selected source column, unit and
both fields' file/manual provenance. Data edits call the Analyze controller's
normal selection paths; Analyze remains the configuration owner. Both pages use
`FileDefaults.value_source` and `ColumnMappingEditor.value_source` for provenance.
Data applies snapshots under signal blockers so mirroring cannot feed back into
manual-edit handlers. Its last-rendered snapshot detects effective changes even
when a user has already changed the Data widget. Confirming an unchanged value
updates provenance without recomputing sampling statistics.

Data's time-column options match the batch's available signal columns and include
an explicit Not included option. Switching the viewed recording preserves the
shared choice, even if it is absent from that file; diagnostics then remain
unavailable. Cached initial descriptives are reused only for the same source
column and format. Time and sensor previews scan only the inspected recording and
reuse their existing caches. New input resets both pages and applies the new
file defaults through the existing guarded refresh. File-default application
cannot become a manual edit or start intermediate origin previews.

`inspection.input_plot_time` converts only display coordinates from the selected
time column. Absolute Unix timestamps become UTC dates, datetime columns retain
their stored time zone, and relative/difference/duration values display in seconds.
Relative values retain their origin; differences include the first increment in
their cumulative sum. Original table values and analysis settings stay unchanged.
Data and Results sensor graphs share `RecordingDateLocator` and
`RecordingTimeFormatter`; the existing graph toolbar uses their date locator to
read and edit calendar limits. Graph exports use the same coordinates and labels.

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

Shared contracts type frames, paths, pipeline names, worker callbacks and process
messages. `RunRecord` and `RunOutput` are `TypedDict` schemas with required fields,
known status/format literals and optional export details and workspace caches.
`saved_format.py` defines independent history (`paradigma-studio.run`) and result
(`paradigma-studio.results`) envelopes, both with integer `format_version: 1`.
Readers reject missing, boolean, non-integer and unsupported versions; they never
migrate or rewrite files. Bump `FORMAT_VERSION` for incompatible persistence
changes rather than introducing missing-field migrations. History also requires its
current record fields, explicit Analyze settings and kind-specific output fields. JSON output receipts require a
checksum; export reopening requires `complete: true`. CSV outputs remain valid
without JSON-specific fields, and local snapshots remain distinct from exports.
`new_run` stamps the format but callers constructing history records must provide
the complete current Analyze settings. Public extension metadata is retained,
while private frame/result caches are never restored from history JSON. The generic
result decoder enforces the result envelope; Runs additionally verifies identity
and the recorded checksum. Unsupported history entries produce issues without
hiding valid entries. The earlier application storage directory is not discovered.
Missing-result/clock handling remains available for partial analyses and recordings
without a calendar origin. Scientific types remain under `TYPE_CHECKING` at startup.
Extensible saved/display settings, provenance and results and the heterogeneous Qt
job-completion payload retain `Any`. Official adapter keywords are explicitly typed;
open dictionaries loaded from history still require runtime validation. pandas stubs are
development dependencies. Keep scientific type imports under `TYPE_CHECKING`;
the packaged `py.typed` marker exposes available annotations to callers without
adding startup imports.

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

Studio calls official preparation and orientation functions explicitly before
`run_paradigma` with prepared inputs. ParaDigMa 1.1.2's raw orchestrator does not
forward all preparation options; explicit preparation preserves the chosen unit,
axis, missing-sample and gap policies without interpolating across recordings.

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
`previews`, `recording_results`, `storage`, `result_preparation` and
`result_reopening`. The `raw_signals` renderer and header-only `column_mapping`
model and `axis_mapping` service are also included. New controllers
automatically join
the gate, including modules with no tests. Other Studio modules and the upstream
toolbox are outside this initial reporting scope; this is not whole-app coverage.
The source scope, branch mode and floor live in `pyproject.toml`.
The initial Linux measurement at [commit `e8bd902`](https://github.com/biomarkersParkinson/ParaDigMa-Studio/commit/e8bd902)
recorded 90.2% of statements and 76.5% of branch outcomes, or 87.0% combined across
16 modules (893 tests passed, one skipped). This is a dated baseline.

The Windows and Linux commands above include the same coverage flags as CI.
XML is written to `test-reports/coverage.xml`; open
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
