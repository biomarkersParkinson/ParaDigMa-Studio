# Performance review — 0.2.2

The app now opens before importing the scientific pipelines, reuses fonts between
portable-app launches, and ships fewer unused Arrow files. Analysis algorithms,
classifiers, supported sensor formats, parameters and exports remain unchanged.

## Measurements

Measured on 6 October 2026 in the Linux cloud environment, with Python 3.12,
ParaDigMa 1.1.2 and identical dependencies. These are **Linux results, not Windows
benchmarks**. Each launch used a fresh process, empty run history and Qt offscreen
rendering. OS caches were already available; this does not measure a cold Windows
boot, antivirus scanning, or the user's accumulated history.

| Metric | Before | After |
| --- | ---: | ---: |
| Packaged launch to first-window report, median of 5 | 3.36 s | 1.23 s |
| Source launch to first paint, median of 5 | 2.13 s | 1.13 s |
| Portable bundle, regular-file bytes | 572.3 MiB | 539.2 MiB |
| Bundle files, excluding symlinks | 2,341 | 1,760 |

Packaged launch improved by **63.4%**; bundle size fell by **33.1 MiB (5.8%)**.
The optimized packaged launch samples were 2.35, 1.20, 1.20, 1.23 and 1.25 seconds.
The first sample built the font cache; the following samples reused it. The
baseline rebuilt fonts on every launch. Download ZIP sizes and filesystem-allocated
space differ from the regular-file lengths reported here.

The baseline was built from commit `68638a6`, with only the startup-report
entrypoint added for measurement. Startup reports are written after the main
window paints and Qt returns to its event loop. The external timer includes the
PyInstaller bootloader and up to roughly 10 ms of report polling. Raw samples and
component sizes are in [performance-measurements.json](performance-measurements.json).

## Changes

- **Deferred scientific imports:** lightweight forwarding functions call the same
  official ParaDigMa functions when loading or analyzing in the existing worker.
  The initial window no longer imports ParaDigMa, SciPy or scikit-learn. The first
  file load/analysis pays this one-time import cost.
- **Persistent fonts:** PyInstaller normally creates a new temporary Matplotlib
  configuration directory each launch. The stable `_internal` directory of this
  portable build permits a per-user cache. Its key includes the bundle location
  and Matplotlib version, so relocation or upgrades use a fresh cache. Source and
  one-file launches keep their existing configuration; unavailable cache storage
  falls back to temporary caching.
- **Smaller Arrow collection:** omit Flight/query Python modules and development
  headers. Keep dataset, filesystem, compute, Parquet codecs and encryption.
  Native dependency scanning retains required shared libraries, including
  `libarrow_substrait` on Linux. Windows scikit-learn runtime DLL collection and
  all four classifier assets remain in place. The bundle stays portable/onedir.
- **Less repeated UI work:** count missing values once on load and reuse the
  Results overview summary when switching graph metrics. Changing rows or
  datasets refreshes the summary; graph/table selections still agree.

The largest remaining components are Qt/PySide6 (118.5 MiB) and Arrow/Parquet
(111.9 MiB), followed by the scientific Python libraries. A standalone scientific
app includes these runtimes. Further major size reductions would require different
dependencies or a separately installed runtime, which needs a broader compatibility
review. This update retains them to preserve existing functionality.

## Verification and Windows measurements

All **139 tests passed**, with one Windows-only test skipped locally. This includes
all **23 scientific equivalence cases** against independent official ParaDigMa
workflows. Startup/cache and summary-filter tests cover the new behavior. The
rebuilt executable also passed its classifier, CWA, Empatica, Physilog, plotting,
export and run-history smoke checks. Source scanning found no Bandit issues.

Both Windows build workflows now run `scripts/benchmark_desktop.py` and include
`performance.json` in the artifact before generating its checksums. This records
native Windows launch samples, Qt platform and component sizes without imposing
a hardware-dependent timing threshold. The first-frame check also rejects
accidental eager scientific imports. To benchmark locally after building:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_desktop.py dist/ParaDigMaDesktop/ParaDigMaDesktop.exe --report performance.json
```

The probe opens an empty window and exits without opening sensor data, running
analyses or changing run history. Numerical reproducibility coverage and its
limits remain documented in [SCIENTIFIC_TESTS.md](SCIENTIFIC_TESTS.md).
