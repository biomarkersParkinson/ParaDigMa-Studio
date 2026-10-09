# Repository map

The application uses a standard Python `src/` layout. Generated bundles, caches
and local build files are ignored by Git. Windows executables belong in GitHub
Actions artifacts, rather than in the source repository.

| Location | Purpose |
| --- | --- |
| `src/paradigma_desktop/` | Installed application code |
| `src/paradigma_desktop/ui/` | Page construction and Results graph interactions |
| `src/paradigma_desktop/data/` | Packaged graphics and public smoke-test recordings; provenance in `README.txt` |
| `src/paradigma_desktop/data/notices/` | Canonical ParaDigMa acknowledgement, licence and citation files |
| `tests/` | UI, processing, security, startup, performance and scientific-equivalence tests |
| `tests/data/paradigma/` | Independent official reference fixtures and checksums, excluded from the executable |
| `scripts/` | Build, frozen-app verification, benchmarks, dependency auditing and signing |
| `docs/` | User and developer documentation, validation, performance and audit reports |
| `.github/workflows/` | Ordinary and signed Windows build pipelines |

`desktop.py` is the launcher. `pyproject.toml` defines dependencies, packaging,
pytest and Ruff checks. `README.md` is the user entry point; `SECURITY.md` and
`SIGNING.md` describe the distribution and publisher workflows.

## Application boundaries

| Responsibility | Modules |
| --- | --- |
| Window lifecycle, navigation, selection and workflow coordination | `app.py` |
| Construction of the four existing pages and their controls | `ui/layout.py` |
| Results rendering, epoch caches and linked graph selection | `ui/result_graphs.py` |
| Shared channel selection and original sensor plotting | `channels.py` |
| Original output tables, presentation timing and optional table columns | `result_data.py`, `results_view.py` |
| Official ParaDigMa loading, preparation and orchestration | `core.py`, `empatica.py`, `recordings.py` |
| Scientific worker isolation/cancellation and job signals | `analysis_process.py`, `jobs.py` |
| Read-only, replaceable recording previews | `previews.py`, `inspection.py` |
| Coverage, epoch summaries, gait presence and overview charts | `availability.py`, `epochs.py`, `gait_presence.py`, `gait_overview.py`, `overview.py` |
| Sensor context and source timelines | `exploration.py` |
| Export selection, encoding and safe file writes | `exports.py`, `serialization.py`, `storage.py` |
| Run metadata, deletion and JSON reopening | `history.py` |
| Reusable Qt controls and forms | `widgets.py`, `time_controls.py` |
| Graph controls, rendering, selection overlay and pinned time axis | `plot_controls.py`, `plotting.py`, `time_axis.py` |
| Palette, typography and packaged resource paths | `theme.py`, `assets.py` |
| Matplotlib font-cache initialization | `bootstrap.py`, `plot_cache.py` |
| About, licences and citations | `acknowledgements.py`, `data/notices/` |
| Packaged startup and scientific smoke probes | `startup.py`, `smoke.py` |

## Conventions for changes

`MainWindow` owns Qt widgets, workers and selected-run state. `WorkspaceLayout`
and `ResultGraphs` are implementation mixins: they have no separate lifecycle or
constructor and use the window's existing controls and callbacks. Keep shared
widget attributes stable when moving code; the current tests and integrations
use them. Import aliases for existing `app` job/channel helpers and `core`
export functions remain available.

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
[codebase audit](CODEBASE_AUDIT.md) records the refactoring and validation scope.
