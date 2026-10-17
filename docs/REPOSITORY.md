# Repository map

The application uses a standard Python `src/` layout. Generated bundles, caches
and local build files are ignored by Git. Windows executables belong in GitHub
Actions artifacts, rather than in the source repository.

| Location | Purpose |
| --- | --- |
| `src/paradigma_studio/` | Installed application code |
| `src/paradigma_studio/ui/` | Page construction, overview/series rendering and Results graph interactions |
| `src/paradigma_studio/data/` | Packaged graphics and public smoke-test recordings; provenance in `README.txt` |
| `LICENSE` | Apache 2.0 licence for ParaDigMa Studio |
| `src/paradigma_studio/data/notices/` | Packaged Studio licence and ParaDigMa acknowledgement, licence and citation files |
| `tests/` | UI, processing, security, startup, performance and scientific-equivalence tests |
| `tests/data/paradigma/` | Independent official reference fixtures and checksums, excluded from the executable |
| `scripts/` | Build/CI checks, frozen-app verification, benchmarks, dependency auditing, releases and signing |
| `docs/` | Current user, developer, validation and performance guides; start with `docs/README.md` |
| `docs/archive/` | Version-specific audits, measurements and historical screenshots |
| `.github/workflows/` | Ordinary and signed Windows build pipelines |

`desktop.py` is the launcher. `pyproject.toml` defines dependencies, packaging,
pytest, coverage.py, Ruff and mypy checks. `README.md` is the user entry point;
`SECURITY.md` and `SIGNING.md` describe the distribution and publisher workflows.

## Application boundaries

| Responsibility | Modules |
| --- | --- |
| Component creation, Qt lifecycle adapters and ordered signal wiring | `app.py` |
| Internal workspace driver API for tests, probes and benchmarks | `ui/compatibility.py` |
| Explicit attribute forwarding between composed UI components | `ui/component_ports.py` |
| Input, result, run, sensor, job and presentation state | `workspace_state.py` |
| Recording loading, inspection previews and raw Data graphs | `data_controller.py` |
| Analysis controls, field guidance, origin previews and run configuration | `analysis_controller.py`, `analysis_help.py` |
| Worker creation, control restoration, failure and cancellation actions | `job_controller.py` |
| Result tables, detail selection, series and shared view controls | `result_workspace_controller.py` |
| Exports, save actions and unsaved-close handling | `export_controller.py` |
| Navigation, notices and About dialog | `shell_controller.py` |
| Public service contracts and shared payload types; no startup scientific imports | `contracts.py`, `py.typed` |
| Result installation, source alignment, clock selection and completion status | `result_controller.py` |
| Run lifecycle, history selection, local saving, reopening and confirmed deletion | `run_controller.py`; file/schema operations in `history.py` |
| Sensor context selection, indexed navigation and channel rendering | `sensor_controller.py`; timing helpers in `exploration.py`, `sensor_navigation.py` |
| Page construction and shared frozen callbacks | `ui/layout.py`, `ui/workspace_callbacks.py`; Data widgets in `ui/data_page.py`, Analyze widgets in `ui/analysis_page.py` |
| First-use graph construction and frozen graphics handles | `ui/deferred.py`, `ui/graph_views.py` |
| Overview cards/charts and plot-series selection tree | `ui/result_overview.py`, `ui/result_series.py` |
| Results rendering and linked graph selection | `ui/result_graphs.py`; cached summaries and display transforms in `ui/result_plot_data.py` |
| Shared channel selection and original sensor plotting | `channels.py` |
| Original output tables, presentation timing and optional table columns | `result_data.py`, `results_view.py` |
| Recording loading, TSDF scaling, preparation and official ParaDigMa orchestration | `core.py`, `empatica.py`, `tsdf_input.py`, `recordings.py` |
| Scientific worker isolation/cancellation, resource limits and job signals | `analysis_process.py`, `parallel_analysis.py`, `analysis_limits.py`, `jobs.py` |
| Ordered recording-output merging and official pooled aggregation | `recording_results.py` |
| Read-only, replaceable recording previews | `previews.py`, `inspection.py` |
| Prepared coverage, gait presence and overview charts | `availability.py`, `gait_presence.py`, `gait_overview.py`, `overview.py` |
| Half-hour, day and 24-hour-profile summaries | `epochs.py`, `daily.py`, `epoch_profile.py` |
| Export selection, encoding and safe file writes | `exports.py`, `serialization.py`, `storage.py` |
| Reusable Qt controls, lazy run-record tables and forms | `widgets.py`, `time_controls.py` |
| Graph controls, rendering, selection overlay and pinned time axis | `plot_controls.py`, `plotting.py`, `time_axis.py` |
| Results date/time labels and fixed Y-axis layout | `day_axis.py`, `epoch_axis.py`, `profile_axis.py`, `result_layout.py` |
| Results time navigation, interval painting and history | `result_navigation.py`, `result_canvas.py` |
| Application identity, compatible user-data paths, palette and resources | `branding.py`, `theme.py`, `assets.py` |
| Matplotlib font-cache initialization | `bootstrap.py`, `plot_cache.py` |
| About, licences and citations | `acknowledgements.py`, `data/notices/` |
| Packaged startup and scientific smoke probes | `startup.py`, `smoke.py` |

## Conventions for changes

`MainWindow` inherits only `QMainWindow` and creates the builder and controllers.
`WorkspaceLayout` constructs the pages from explicit callbacks and state, then
returns frozen page views. `ResultGraphs` receives result/graph state, a frozen
`ResultGraphView` and named callbacks. Controllers use their declared state,
view and service ports. A Qt parent provides ownership/dialog APIs, never access
to application attributes. New UI controllers retain GUI-thread QObject affinity.
Overview and series renderers receive their layout/tree and result inputs directly.
`DataPage` owns the recording header, overview/tabs, footer action and responsive
splitter. Its frozen `DataPageHost` supplies the parent and page/footer layouts;
callbacks and the deferred channel-graph factory are separate explicit dependencies.

The main result and run responsibilities belong to these components:

| Responsibility | Implementation |
| --- | --- |
| Render the result overview | `ui.result_overview.ResultOverview.render` |
| Install completed analysis results | `result_controller.ResultController.analyzed` |
| Populate result series | `ui.result_series.ResultSeries.populate` |
| Delete runs | `run_controller.RunController.delete_runs` |

`workspace_state.py` owns shared state. Application code, including MainWindow's
composition and signal wiring, uses explicit layout/state/controller owners.
State assertions use those objects directly, such as
`window._result_state.provenance` for result metadata.

`ui/compatibility.py` is the **internal workspace driver API** for UI tests,
startup/smoke probes and benchmarks. Its historical filename is retained. The
`workspace_ports` decorator exposes declared widgets and actions on MainWindow
for automation; the application also works without installing those ports.
The ports follow UI implementation details and carry no public stability
guarantee. Keep useful driver ports; further removal is not a goal by itself.
Choosing a stable supported driver contract requires a separate review.
The [driver-port budget guard](DEVELOPMENT.md#quality-gates-and-implementation-conventions)
remains shrink-only and requires both budgets to match any removals. The reusable
`component_attribute` descriptor belongs to `ui/component_ports.py`; it supports
explicit component composition without a generic host fallback.
Graphics stay deferred through frozen callable ports and reuse their canvases.
Preview receivers and lazy sensor slots remain thin Qt adapters on the window.
The window connects worker signals in their original order; `JobController`
starts the worker only after those connections exist. Import aliases for
existing `app` job/channel helpers and `core` export functions remain available.

Keep controller callbacks limited to cross-component actions. Put local logic in
the owning component and presentation/scientific calculations in the existing
Qt-independent helpers. Component tests exercise result installation and partial
deletion without constructing a complete window. Layout/graph component tests
use a plain `QMainWindow`, while ordering tests pin signal delivery, GUI-thread
completion, control restoration and queued close after saving. The full UI
regressions cover composition and saved-run compatibility.

Extract named helpers for validation, preparation, execution and rendering, with
explicit inputs and return values.
Follow the [quality gates and implementation conventions](DEVELOPMENT.md#quality-gates-and-implementation-conventions)
for function/module size, branching, complexity, typing and justified suppressions.
Preserve calculation order, Qt construction order, lazy imports and assertions;
this also applies to smoke checks, benchmarks and tests.

Prepare output data in Qt-independent helpers before updating models and plots.
`ResultData` separates the original tables from derived graph and timing views;
its frozen container does not make its DataFrames immutable. Treat official
frames as read-only and use separate columns or frames for presentation.

Initialize the portable font cache before importing Matplotlib. Keep scientific
imports deferred to loading and analysis. Run cancellation stays in the isolated
analysis process; background previews only read data and deliver the newest
requested result. GUI changes belong on the Qt thread.

Use `storage.atomic_file` for destination replacement and `recording_files` /
`same_file` for sensor-file protection. Keep result/history JSON schemas, CSV
escaping and original-input protections compatible with existing saved runs.

The supported build entry point is `scripts/build_desktop.py`. PyInstaller specs
are generated under `build/desktop/` and ignored by Git; old specs left in a local
checkout are not build inputs. Keep generated reports outside the portable app.

Run the [development checks](DEVELOPMENT.md) before submitting changes. The
[archived codebase audit](archive/codebase-audit-0.5.23.md) records the earlier
refactoring and its validation scope. The [test suite guide](TEST_SUITE.md) maps
checks to current features.
