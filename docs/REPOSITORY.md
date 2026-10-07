# Repository map

The repository uses a standard Python `src/` layout. Build outputs and caches
are excluded from Git; the much larger portable bundle belongs in GitHub Actions
artifacts rather than in the source repository.

| Location | Purpose |
| --- | --- |
| `src/paradigma_desktop/` | Installed application code |
| `src/paradigma_desktop/data/` | Packaged graphics and public smoke-test recordings; provenance in `README.txt` |
| `src/paradigma_desktop/data/notices/` | Canonical ParaDigMa acknowledgement, licence and citation files |
| `tests/` | UI, processing, security, startup and scientific-equivalence tests |
| `tests/data/paradigma/` | Official scientific-reference fixtures and checksums; excluded from the application bundle |
| `scripts/` | Build, packaged verification, performance, dependency audit and signing tools |
| `docs/` | User/developer guides, scientific validation, measured performance and screenshots |
| `.github/workflows/` | Ordinary and signed Windows build pipelines |
| `build/`, `dist/`, `*.spec` | Generated local packaging outputs, ignored by Git |

`desktop.py` is the small launcher used by PyInstaller and development. Package
configuration lives in `pyproject.toml`. `README.md` is the new-user entry point;
`SECURITY.md` stays at the root for GitHub discovery and `SIGNING.md` documents
publisher setup.

## Application responsibilities

- `app.py`: the main window, pages, navigation and workflow coordination.
- `widgets.py`: shared table models, readable controls, hover navigation and small layout helpers.
- `acknowledgements.py`: the on-demand About/citation view; attribution text lives
  in the packaged notices, not in duplicated UI strings.
- `core.py`: file loading, official ParaDigMa orchestration and safe export.
- `empatica.py`: device-specific import adaptation.
- `inspection.py`: input statistics; `exploration.py` and `results_view.py`: result
  selection, context, timing and presentation summaries.
- `history.py`: run metadata and JSON reopening.
- `theme.py`, `plot_controls.py`, `plot_cache.py`: styling, figure controls and cache handling.
- `plotting.py`: shared signal/state rendering and canvas scrolling;
  `time_controls.py`: calendar/clock and elapsed-time fields.
- `startup.py`, `smoke.py`: probes that must run inside the packaged executable.

## Review and cleanup

The existing source/tests/scripts/docs separation remains appropriate. Shared
Qt controls have been extracted from the main-window file, and attribution files
are grouped under `data/notices/`. Licence and citation copies beside the built
executable are generated from that single canonical folder. Build paths, entry
points and independent scientific fixtures retain their existing roles.

The main-window module remains large. Future substantial page work could move
individual pages into a UI subpackage, using the current UI and scientific tests
to protect shared selection and run-state behavior. That larger refactoring is
not needed for the present acknowledgement and structural cleanup.
