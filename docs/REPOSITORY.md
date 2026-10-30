# Repository map

Use this guide to find the owner of a change in the current source on `main`.
The project uses a standard Python `src/` layout. The
[architecture guide](ARCHITECTURE.md) explains component behavior and lifecycle;
the [Python API reference](PYTHON_API.md) owns service and persistence contracts.

- [Top-level layout](#top-level-layout)
- [Application boundaries](#application-boundaries)
- [Scripts and CI workflows](#scripts-and-ci-workflows)
- [Conventions for changes](#conventions-for-changes)
- [Generated outputs and validation](#generated-outputs-and-validation)

## Top-level layout

| Location | Purpose |
| --- | --- |
| [src/paradigma_studio/](../src/paradigma_studio/) | Installed application code |
| [src/paradigma_studio/ui/](../src/paradigma_studio/ui/) | Page builders, frozen views, overview/series renderers and Results graph interactions |
| [src/paradigma_studio/data/](../src/paradigma_studio/data/) | Packaged graphics and public example recordings; provenance in [README.txt](../src/paradigma_studio/data/README.txt) |
| [src/paradigma_studio/data/notices/](../src/paradigma_studio/data/notices/) | Packaged Studio/ParaDigMa licences, attribution and research citations |
| [tests/](../tests/) | Unit, component, UI, scientific, security, startup and packaging checks |
| [tests/data/paradigma/](../tests/data/paradigma/) | Independent official reference fixtures and checksums, excluded from the executable |
| [scripts/](../scripts/) | Source guards, builds, executable probes, benchmarks, dependency evidence, releases and signing |
| [docs/](README.md) | Current guides, with navigation in the documentation index |
| [docs/images/](images/) | Documentation screenshots and diagrams, with source/regeneration notes |
| [docs/archive/](archive/README.md) | Dated audits, measurements and historical screenshots |
| [.github/](../.github/) | Workflows, issue forms and pull-request template |

The key root files are:

- [desktop.py](../desktop.py): source launcher and packaged executable entry point.
- [pyproject.toml](../pyproject.toml): package metadata, dependencies, packaging,
  pytest, coverage, Ruff and mypy configuration. [uv.lock](../uv.lock) and
  [.python-version](../.python-version) define the reviewed dependency/interpreter
  environment; see [Dependencies](DEPENDENCIES.md).
- [README.md](../README.md), [CONTRIBUTING.md](../CONTRIBUTING.md),
  [SECURITY.md](../SECURITY.md), [SIGNING.md](../SIGNING.md) and [LICENSE](../LICENSE):
  user entry point, contribution policy, security policy, signing setup and
  Studio's Apache 2.0 licence.

## Application boundaries

Module labels below are relative to `src/paradigma_studio/`. Start with the
controller for an interaction change, the page builder for widget layout, or the
service/helper for calculations and file operations.

### Composition and shared UI

| Responsibility | Start here |
| --- | --- |
| Create state, pages and controllers; connect Qt signals | [app.py](../src/paradigma_studio/app.py), the `MainWindow` composition root |
| Shared input, result, run, sensor, job and presentation state | [workspace_state.py](../src/paradigma_studio/workspace_state.py) |
| Whole-window layout, Runs widgets and shared page callbacks | [ui/layout.py](../src/paradigma_studio/ui/layout.py), [ui/workspace_callbacks.py](../src/paradigma_studio/ui/workspace_callbacks.py) |
| Data, Analyze and Results widget construction | [ui/data_page.py](../src/paradigma_studio/ui/data_page.py), [ui/analysis_page.py](../src/paradigma_studio/ui/analysis_page.py), [ui/results_page.py](../src/paradigma_studio/ui/results_page.py) |
| First-use graph construction and frozen graphics handles | [ui/deferred.py](../src/paradigma_studio/ui/deferred.py), [ui/graph_views.py](../src/paradigma_studio/ui/graph_views.py) |
| Explicit forwarding between composed UI components | [ui/component_ports.py](../src/paradigma_studio/ui/component_ports.py) |
| Reusable widgets, time fields and page-directed wheel scrolling | [widgets.py](../src/paradigma_studio/widgets.py), [time_controls.py](../src/paradigma_studio/time_controls.py), [field_scrolling.py](../src/paradigma_studio/field_scrolling.py) |
| Identity, storage paths, palette and resources | [branding.py](../src/paradigma_studio/branding.py), [theme.py](../src/paradigma_studio/theme.py), [assets.py](../src/paradigma_studio/assets.py) |
| Font-cache initialization before plotting imports | [bootstrap.py](../src/paradigma_studio/bootstrap.py), [plot_cache.py](../src/paradigma_studio/plot_cache.py) |

### Data and Analyze

| Responsibility | Start here |
| --- | --- |
| Loading actions, recording selection, previews and raw Data views | [data_controller.py](../src/paradigma_studio/data_controller.py) |
| File decoding and batch loading | `core.load_sensor_file` in [core.py](../src/paradigma_studio/core.py), [recordings.py](../src/paradigma_studio/recordings.py); device readers in [empatica.py](../src/paradigma_studio/empatica.py) and [tsdf_input.py](../src/paradigma_studio/tsdf_input.py) |
| Exact statistics and replaceable read-only previews | [inspection.py](../src/paradigma_studio/inspection.py), [previews.py](../src/paradigma_studio/previews.py) |
| Analyze values, shared time configuration, origin previews and new-run configuration | [analysis_controller.py](../src/paradigma_studio/analysis_controller.py) |
| Signal selection, mapping validation and axis inversions | [ui/column_mapping.py](../src/paradigma_studio/ui/column_mapping.py), [column_mapping.py](../src/paradigma_studio/column_mapping.py), [axis_mapping.py](../src/paradigma_studio/axis_mapping.py) |
| Unit metadata, From file labels and Default actions | [input_metadata.py](../src/paradigma_studio/input_metadata.py), [ui/file_defaults.py](../src/paradigma_studio/ui/file_defaults.py); reset/availability behavior in `AnalysisController` |
| Explanations, non-modal help windows and the input-axis figure | [analysis_help.py](../src/paradigma_studio/analysis_help.py), [ui/analysis_help_dialog.py](../src/paradigma_studio/ui/analysis_help_dialog.py), [ui/analysis_figure.py](../src/paradigma_studio/ui/analysis_figure.py) |

### Scientific processing and jobs

| Responsibility | Start here |
| --- | --- |
| Validation, explicit preparation and official ParaDigMa orchestration | `core.analyze` in [core.py](../src/paradigma_studio/core.py) |
| Shared payload types and processing keywords | [contracts.py](../src/paradigma_studio/contracts.py), [preparation_contracts.py](../src/paradigma_studio/preparation_contracts.py); [py.typed](../src/paradigma_studio/py.typed) marks the typed package |
| Typed, lazy calls to the official toolbox | [paradigma_api.py](../src/paradigma_studio/paradigma_api.py) |
| Owned analysis processes, cancellation and resource selection | [analysis_process.py](../src/paradigma_studio/analysis_process.py), [parallel_analysis.py](../src/paradigma_studio/parallel_analysis.py), [analysis_limits.py](../src/paradigma_studio/analysis_limits.py) |
| QThread job signals, worker lifetime and control restoration | [jobs.py](../src/paradigma_studio/jobs.py), [job_controller.py](../src/paradigma_studio/job_controller.py) |
| Weighted progress milestones and upstream stage-log adapters | [analysis_progress.py](../src/paradigma_studio/analysis_progress.py); visual delivery in `JobController` |
| Ordered recording-output merging and official pooled aggregation | [recording_results.py](../src/paradigma_studio/recording_results.py) |

### Results and graphs

| Responsibility | Start here |
| --- | --- |
| Install completed results and source alignment | [result_controller.py](../src/paradigma_studio/result_controller.py); worker-safe presentation snapshots in [result_preparation.py](../src/paradigma_studio/result_preparation.py) |
| Result tables, detail selection, series and shared view controls | [result_workspace_controller.py](../src/paradigma_studio/result_workspace_controller.py) |
| Original tables, display clocks, recording alignment and optional table columns | [result_data.py](../src/paradigma_studio/result_data.py), [results_view.py](../src/paradigma_studio/results_view.py), [recordings.py](../src/paradigma_studio/recordings.py) |
| Overview and plot-series tree rendering | [ui/result_overview.py](../src/paradigma_studio/ui/result_overview.py), [ui/result_series.py](../src/paradigma_studio/ui/result_series.py) |
| Results graph rendering and prepared plot data | [ui/result_graphs.py](../src/paradigma_studio/ui/result_graphs.py), [ui/result_plot_data.py](../src/paradigma_studio/ui/result_plot_data.py) |
| Graph clicks, linked table selection, result markers and context actions | [ui/result_graph_interactions.py](../src/paradigma_studio/ui/result_graph_interactions.py) |
| Sensor context selection and indexed window navigation | [sensor_controller.py](../src/paradigma_studio/sensor_controller.py), [exploration.py](../src/paradigma_studio/exploration.py), [sensor_navigation.py](../src/paradigma_studio/sensor_navigation.py) |
| Coverage, gait presence and overview chart calculations | [availability.py](../src/paradigma_studio/availability.py), [gait_presence.py](../src/paradigma_studio/gait_presence.py), [gait_overview.py](../src/paradigma_studio/gait_overview.py), [overview.py](../src/paradigma_studio/overview.py) |
| Half-hour, day and 24-hour-profile summaries | [epochs.py](../src/paradigma_studio/epochs.py), [daily.py](../src/paradigma_studio/daily.py), [epoch_profile.py](../src/paradigma_studio/epoch_profile.py) |

Shared graph controls and rendering live outside the page builders:

| Responsibility | Start here |
| --- | --- |
| Channel selection and original-sample drawing | [channels.py](../src/paradigma_studio/channels.py), [raw_signals.py](../src/paradigma_studio/raw_signals.py) |
| Shared toolbars, time-interval selection, zoom, hand dragging and horizontal scrolling | [plot_controls.py](../src/paradigma_studio/plot_controls.py), [time_navigation.py](../src/paradigma_studio/time_navigation.py); raw hooks in [raw_navigation.py](../src/paradigma_studio/raw_navigation.py), Results hooks in [result_navigation.py](../src/paradigma_studio/result_navigation.py) |
| Qt canvas, selection overlays and pinned time ruler | [plotting.py](../src/paradigma_studio/plotting.py), [selection_lines.py](../src/paradigma_studio/selection_lines.py), [time_axis.py](../src/paradigma_studio/time_axis.py) |
| Results viewport painting and retained geometry/coordinates | [result_canvas.py](../src/paradigma_studio/result_canvas.py), [result_plot_cache.py](../src/paradigma_studio/result_plot_cache.py) |
| Results date/time labels and fixed Y-axis layout | [day_axis.py](../src/paradigma_studio/day_axis.py), [epoch_axis.py](../src/paradigma_studio/epoch_axis.py), [profile_axis.py](../src/paradigma_studio/profile_axis.py), [result_layout.py](../src/paradigma_studio/result_layout.py) |

### Runs, exports and shell

| Responsibility | Start here |
| --- | --- |
| Run lifecycle, history selection, save/reopen and confirmed deletion | [run_controller.py](../src/paradigma_studio/run_controller.py) |
| History records, output receipts and current saved-format envelopes | [history.py](../src/paradigma_studio/history.py), [saved_format.py](../src/paradigma_studio/saved_format.py) |
| Run identity, exact-byte checksums and analysis-time software provenance | [result_integrity.py](../src/paradigma_studio/result_integrity.py), [provenance.py](../src/paradigma_studio/provenance.py) |
| Background saved-result reading, including large-JSON isolation | [result_reopening.py](../src/paradigma_studio/result_reopening.py) |
| Export/save actions and unsaved-close handling | [export_controller.py](../src/paradigma_studio/export_controller.py) |
| Export selection, JSON/CSV encoding and atomic source-protected writes | [exports.py](../src/paradigma_studio/exports.py), [serialization.py](../src/paradigma_studio/serialization.py), [storage.py](../src/paradigma_studio/storage.py) |
| Navigation, notices, About, licences and citations | [shell_controller.py](../src/paradigma_studio/shell_controller.py), [acknowledgements.py](../src/paradigma_studio/acknowledgements.py), [data/notices/](../src/paradigma_studio/data/notices/) |

## Scripts and CI workflows

| Task | Implementation or guide |
| --- | --- |
| Source-size and internal-driver guards | [check_module_size.py](../scripts/check_module_size.py), [check_workspace_facade.py](../scripts/check_workspace_facade.py), [workspace_facade_budget.json](../scripts/workspace_facade_budget.json) |
| Portable build and frozen-app checks | [build_desktop.py](../scripts/build_desktop.py), [check_frozen.py](../scripts/check_frozen.py), package hooks under [pyinstaller_hooks/](../scripts/pyinstaller_hooks/) |
| Packaged startup and scientific smoke probes | [startup.py](../src/paradigma_studio/startup.py), [smoke.py](../src/paradigma_studio/smoke.py), invoked through the launcher |
| Dependency audits, target package graphs and manifests | [audit_dependencies.py](../scripts/audit_dependencies.py), [dependency_evidence.py](../scripts/dependency_evidence.py), [write_build_manifest.py](../scripts/write_build_manifest.py); policy in [Dependencies](DEPENDENCIES.md) |
| Runtime benchmarks | `scripts/benchmark_*.py`; choose a probe in [Performance](PERFORMANCE.md#reproduce-measurements) |
| User-guide screenshots | [capture_user_guide.py](../scripts/capture_user_guide.py), with [capture notes](images/user-guide/README.md) |
| Release verification, assets and publication | [prepare_release.py](../scripts/prepare_release.py) and the ordinary Windows workflow; process in [Releases](RELEASES.md) |
| Publisher signing and native signature checks | [signing_bundle.py](../scripts/signing_bundle.py), [windows_signatures.ps1](../scripts/windows_signatures.ps1); setup in [Signing](../SIGNING.md) |

The three workflows have distinct jobs:

| Workflow file | Purpose |
| --- | --- |
| [windows.yml](../.github/workflows/windows.yml) | Source/dependency checks, tests, Windows build, executable checks and benchmarks; tag pushes also publish releases |
| [windows-signed.yml](../.github/workflows/windows-signed.yml) | Manual build, signing and isolated verification from `main` |
| [documentation.yml](../.github/workflows/documentation.yml) | Maintained Markdown lint and repository-wide local file/image/heading-link checks |

Documentation checks use [.markdownlint-cli2.yaml](../.markdownlint-cli2.yaml)
and [.lychee.toml](../.lychee.toml) at the repository root.

## Conventions for changes

### Component ownership and wiring

`MainWindow` inherits only `QMainWindow` and creates the state, builders and
controllers. `WorkspaceLayout` constructs pages from explicit state and callbacks
and returns frozen views. `DataPageHost` and `ResultsPageHost` provide explicit
page dependencies; `ResultGraphs` receives its state, frozen `ResultGraphView`
and named callbacks.

Use the declared state, view and service ports inside controllers. A Qt parent
supplies ownership and dialog APIs. Cross-component actions use named callbacks;
local behavior stays in its owning component. `component_attribute` forwards only
explicitly declared attributes, without a generic host fallback.

Application composition, signal wiring and state assertions use their owners
directly. For example, inspect `window._result_state.provenance` for result
metadata. The [component/lifecycle guide](ARCHITECTURE.md#components-and-ownership)
explains these boundaries in detail.

### Scientific data, imports and Qt lifecycle

Keep validation, preparation, execution and rendering in named helpers with
explicit inputs and return values. Preserve calculation order, Qt construction
order and assertions in application code, tests, smoke probes and benchmarks.

Treat original recording and official result frames as read-only. `ResultData`
separates those tables from derived graph/timing views; frozen containers still
hold mutable DataFrames. Prepare presentation data in Qt-independent helpers
before updating models and plots.

Initialize the portable font cache before importing Matplotlib. Keep scientific
imports and graph construction deferred, use frozen callable graphics ports and
reuse initialized canvases. UI signal receivers keep GUI-thread affinity;
preview receivers and lazy sensor slots remain thin window adapters.

Connect worker signals before starting the worker. Preserve completion,
control-restoration and queued-close ordering. Analysis cancellation belongs to
the owned process boundary; previews read data and deliver only the newest
requested result. See [execution and cancellation](ARCHITECTURE.md#execution-and-cancellation)
for the lifecycle and [graph rendering](ARCHITECTURE.md#graph-coordinates-navigation-and-rendering)
for cache/navigation invariants.

### Persistence and file protection

Use `storage.atomic_file` for destination replacement and `recording_files` /
`same_file` to protect sensor sources. Preserve CSV escaping and companion
metadata. Owned JSON writes include the run ID and return a SHA-256 receipt;
reopening a run from disk verifies identity and the same bytes it decodes,
including the isolated large-file path.

History and result JSON require the current `saved_format.py` envelope.
Unsupported formats remain untouched. Follow the
[saved-run contract](PYTHON_API.md#saved-run-contract) when changing settings,
output receipts or persistence.

### Internal workspace driver

[ui/compatibility.py](../src/paradigma_studio/ui/compatibility.py) is the internal
workspace driver for UI tests, startup/smoke probes and benchmarks. Its
`workspace_ports` decorator exposes declared widgets and actions on `MainWindow`;
application code works without those ports and uses explicit owners.

The historical filename is retained. Ports follow UI implementation details and
carry no public stability guarantee. Retain useful driver ports; defining a stable
supported automation contract requires a separate review. The shrink-only guard
tracks both the exact port list and module-line budget, which must match any
removals. See [Development](DEVELOPMENT.md#internal-workspace-driver) for policy.
Existing `app` job/channel helpers and `core` export aliases remain available.

## Generated outputs and validation

The supported build entry point is `scripts/build_desktop.py`. PyInstaller specs
are generated under `build/desktop/`; local old specs are not build inputs.
Windows executables and release assets belong in CI artifacts/downloads. Public
example/reference recordings retain their documented provenance in source.

Common generated paths are excluded by [.gitignore](../.gitignore):

| Path | Generated content |
| --- | --- |
| `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` | Environment and tool caches |
| `build/desktop/`, `dist/ParaDigMaStudio/`, `*.spec` | PyInstaller work, generated spec and portable app |
| `build-reports/`, `test-reports/`, `test-results.xml` | Benchmark, coverage and test reports |
| `dependency-audit.json`, `dependency-environment.json` | Dependency verification reports |
| `release-assets/` | Prepared release ZIP, checksum, notes and internal plan |

Keep generated reports outside the portable app. For a change, use the
[test guide](TEST_SUITE.md) to choose existing component and integration checks.
Components can be exercised independently with explicit inputs and plain
`QMainWindow` hosts; full UI tests cover composition, signal ordering and the
saved-run workflow. Run the applicable [development checks](DEVELOPMENT.md#run-development-checks)
and [documentation checks](../CONTRIBUTING.md#documentation-checks), following the
[quality gates](DEVELOPMENT.md#quality-gates-and-implementation-conventions).

The [archived codebase audit](archive/codebase-audit-0.5.23.md) preserves the earlier
refactor and its original validation scope. Use the current map and test guide
for ongoing work.
