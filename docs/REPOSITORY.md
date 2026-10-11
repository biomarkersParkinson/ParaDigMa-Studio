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
| `scripts/` | Build, frozen-app verification, benchmarks, dependency auditing and signing |
| `docs/` | Current user, developer, validation and performance guides; start with `docs/README.md` |
| `docs/archive/` | Version-specific audits, measurements and historical screenshots |
| `.github/workflows/` | Ordinary and signed Windows build pipelines |

`desktop.py` is the launcher. `pyproject.toml` defines dependencies, packaging,
pytest and Ruff checks. `README.md` is the user entry point; `SECURITY.md` and
`SIGNING.md` describe the distribution and publisher workflows.

## Application boundaries

| Responsibility | Modules |
| --- | --- |
| Window lifecycle, component composition, navigation and Qt signal wiring | `app.py` |
| Input, result, run and sensor state shared through explicit dependencies | `workspace_state.py` |
| Public service contracts and shared payload types; no startup scientific imports | `contracts.py`, `py.typed` |
| Result installation, source alignment, clock selection and completion status | `result_controller.py` |
| Run lifecycle, history selection, local saving, reopening and confirmed deletion | `run_controller.py`; file/schema operations in `history.py` |
| Sensor context selection, indexed navigation and channel rendering | `sensor_controller.py`; timing helpers in `exploration.py`, `sensor_navigation.py` |
| Construction of the four existing pages and their controls | `ui/layout.py` |
| Overview cards/charts and plot-series selection tree | `ui/result_overview.py`, `ui/result_series.py` |
| Results rendering, epoch caches and linked graph selection | `ui/result_graphs.py` |
| Shared channel selection and original sensor plotting | `channels.py` |
| Original output tables, presentation timing and optional table columns | `result_data.py`, `results_view.py` |
| Official ParaDigMa loading, preparation and orchestration | `core.py`, `empatica.py`, `recordings.py` |
| Scientific worker isolation/cancellation and job signals | `analysis_process.py`, `jobs.py` |
| Read-only, replaceable recording previews | `previews.py`, `inspection.py` |
| Coverage, epoch summaries, gait presence and overview charts | `availability.py`, `epochs.py`, `gait_presence.py`, `gait_overview.py`, `overview.py` |
| Export selection, encoding and safe file writes | `exports.py`, `serialization.py`, `storage.py` |
| Reusable Qt controls, lazy run-record tables and forms | `widgets.py`, `time_controls.py` |
| Graph controls, rendering, selection overlay and pinned time axis | `plot_controls.py`, `plotting.py`, `time_axis.py` |
| Application identity, compatible user-data paths, palette and resources | `branding.py`, `theme.py`, `assets.py` |
| Matplotlib font-cache initialization | `bootstrap.py`, `plot_cache.py` |
| About, licences and citations | `acknowledgements.py`, `data/notices/` |
| Packaged startup and scientific smoke probes | `startup.py`, `smoke.py` |

## Conventions for changes

`MainWindow` owns Qt widgets and workers and composes the result, run and sensor
controllers after constructing the pages. Controllers receive specific state
objects, typed widget bundles and named callbacks; they do not receive a window
or access an implicit host API. `RunController` also receives the existing
`RunHistory` and a Qt parent used only for confirmation dialogs. Overview and
series renderers receive their layout/tree and result inputs directly.

`workspace_state.py` is the single owner of shared input, result, run and sensor
state. Window properties preserve the existing attribute API, including the
plot caches, for integrations and the remaining `WorkspaceLayout` and
`ResultGraphs` implementation mixins. These mixins retain page construction and
graph interactions; they have no separate constructor or lifecycle. Keep the
window's signal entry points and widget attributes stable. Import aliases for
existing `app` job/channel helpers and `core` export functions remain available.

Keep controller callbacks limited to cross-component actions. Put local logic in
the owning component and presentation/scientific calculations in the existing
Qt-independent helpers. Component tests exercise result installation and partial
deletion without constructing a complete window; the full UI regressions cover
composition, signals and saved-run compatibility.

Keep functions around 100 lines or fewer. Extract named helpers for validation,
preparation, execution and rendering, with explicit inputs and return values.
Ruff enforces a McCabe complexity limit of 10 across application code, scripts
and tests. Explain any narrow lint suppression beside the affected code.
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

Run the [development checks](DEVELOPMENT.md) before submitting changes. The
[archived codebase audit](archive/codebase-audit-0.5.23.md) records the earlier
refactoring and its validation scope. The [test suite guide](TEST_SUITE.md) maps
checks to current features.
