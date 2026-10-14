# Performance and measurement

## Current runtime behavior

- Startup defers pandas, Arrow and scientific pipeline imports until data is
  needed. The packaged app reuses a per-user Matplotlib font cache. First use
  of data still pays the deferred import cost.
- Data statistics and clock previews use bounded background caches. Recording
  switches reuse previews; obsolete requests cannot replace the latest selection.
- Results reuse prepared graph data and existing plots where possible. Hidden
  graphs defer painting, and rendering excludes bars outside the visible range.
  Panning reuses settled layouts and redraws visible plots before a full redraw
  on release. Dense full-recording plots still cost more than zoomed views.
- Raw plots display at most 20,000 samples per channel. Sensor context indexes
  source timestamps and loads the visible window while preserving the initial
  context, selected time and navigation history. Original tables and exports
  retain all samples; Results retain every output value.
- Analysis uses one owned process for a single recording. Multiple recordings
  can use two workers, reused within the batch, with one native computation thread
  per worker. Existing gap sections stay inside their recording's worker.
  Dispatch reserves a CPU and 1 GiB of available RAM, estimating each worker's
  need as at least 1 GiB or 12 times the largest loaded frame. Low/unknown RAM,
  limited CPU, explicit mutable toolbox configs or restricted `run_steps` retain
  sequential execution. These are conservative estimates, not hard memory limits.
  Results merge in input order; official aggregation functions run once on the
  pooled quantifications, with consistent gait segment IDs. Stop terminates all
  owned workers before deleting their private temporary files. Worker startup and
  file transfers can outweigh parallel gains for short recordings.
- Saving serializes the complete in-memory result to JSON in a background worker.
  Temporary analysis files have already been removed; saving writes a snapshot,
  including tables, metadata and provenance. It does not rerun analysis. Large
  outputs and repeated saves can therefore take time.

The portable bundle includes Python, Qt, Arrow and the scientific libraries.
These native dependencies account for most of its size. Collection hooks retain
models, readers, package metadata, licences and required DLLs while excluding
redundant loose Python source copies and unused Arrow development components.
Builds clear their app output and work directories before packaging.

## Reproduce measurements

An isolated Linux check on 14 October 2026 compared the production single-worker
and automatic paths on four prepared gait recordings, each an eightfold synthetic
repetition of the bundled recorded IMU fixture (583,576 rows; about 97 minutes).
Complete runtime, including process startup, private transfers and pooled
aggregation, decreased from 8.72 s to 7.09 s with two workers. All result values
matched. This one measurement is not a timing guarantee for Windows or other data.

Install the development dependencies and build on Windows as described in
[Development](DEVELOPMENT.md). Run from the repository root in PowerShell:

```powershell
New-Item -ItemType Directory -Force build-reports | Out-Null
.\.venv\Scripts\python.exe scripts/benchmark_desktop.py dist/ParaDigMaStudio/ParaDigMaStudio.exe --report build-reports/performance.json
.\.venv\Scripts\python.exe scripts/benchmark_workflows.py --report build-reports/ui-performance.json
.\.venv\Scripts\python.exe scripts/benchmark_pan.py --report build-reports/pan-performance.json
.\.venv\Scripts\python.exe scripts/benchmark_sensor_context.py --report build-reports/sensor-context-performance.json
```

| Report | Measures |
| --- | --- |
| `performance.json` | Fresh packaged launches, first paint, import boundaries and bundle component sizes |
| `ui-performance.json` | Synthetic input switching, settings, Results interactions, exports and history |
| `pan-performance.json` | Toolbar drags and queued painting in Results, Data and sensor context |
| `sensor-context-performance.json` | First and repeated context openings on a large synthetic recording |

Both Windows workflows publish these files in the separate
**ParaDigMaStudio-build-reports** artifact. They are development reports and
are not needed to run the app. Security provenance and checksums stay in the
application download.

Compare measurements with the same dependencies, inputs, window dimensions and
cache state. Linux offscreen timings do not predict local Windows performance,
cold startup or antivirus overhead. CI checks import boundaries, retained values,
cache reuse and redraw behavior rather than imposing hardware-specific timing
limits. See the [test guide](TEST_SUITE.md) and
[scientific methodology](SCIENTIFIC_TESTS.md) before changing these boundaries.

## Historical evidence

Version-specific before/after measurements and their original JSON reports are
in the [performance review history](archive/performance/REVIEW_HISTORY.md).
Their test counts, bundle sizes and interface descriptions apply to those
versions. The [archived codebase audit](archive/codebase-audit-0.5.23.md) records
the earlier structural refactor.
