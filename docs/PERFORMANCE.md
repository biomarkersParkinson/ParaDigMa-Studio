# Performance and measurement

## Current runtime behavior

- Startup defers pandas, Arrow and scientific pipeline imports until data is
  needed. Matplotlib and the three graph workspaces initialize on first use;
  opening Analyze, Runs or the empty Results overview does not load plotting.
  Later graph visits reuse their canvases and controls. The packaged app reuses
  a per-user Matplotlib font cache. First use still pays the deferred import cost.
- Data statistics and clock previews use bounded background caches. Recording
  switches reuse previews; obsolete requests cannot replace the latest selection.
  Analyze module changes derive only the recording clocks, without constructing
  result alignments. Equivalent sensor requirements reuse the same clock preview;
  Time origin stays editable and user edits take precedence over pending previews.
  Missing-sample checks combine one channel's validity at a time, avoiding copies
  of the complete sensor matrix.
  Initial inspection counts missing values once per column and reuses those
  counts in the channel summaries. Finite channels avoid a filtered sample copy;
  quantiles retain their own workspace so source values stay unchanged. TSDF
  scaling casts and multiplies into one double-precision output array through
  NumPy, retaining the official reader and metadata validation. Every initial
  statistic still finishes before a recording is displayed.
- Results reuse prepared graph data and existing plots where possible. Hidden
  graphs defer painting, and rendering excludes bars outside the visible range.
  Results scrollbar drags and horizontal trackpad gestures reuse settled axes,
  tick positions and measured date-label widths. Ordered intervals use indexed
  viewport lookup. Dense scrolling previews retain pixel-column minima/maxima,
  gaps and long intervals; the full bars return when movement stops, and exports
  always use original bars. Only visible plots redraw during a gesture. Interval
  selection paints directly over the cached Qt image without redrawing graph data,
  including when the figure exceeds the timepoint overlay's memory budget. Raw
  graphs retain panning. Dense full-recording plots still cost more than zoomed views.
- Raw plots display at most 20,000 samples per channel. Sensor context indexes
  source timestamps and loads the visible window while preserving the initial
  context, selected time and navigation history. Sensor tables build and size
  columns only when Tables is selected; panning in Graphs skips that work.
  Switching to Tables shows the latest window immediately and reuses its model
  on subsequent visits until the samples change. Original tables and exports
  retain all samples; Results retain every output value.
- Analysis uses one owned process for a single recording. Multiple recordings
  can use two workers, reused within the batch, with one native computation thread
  per worker. Existing gap sections stay inside their recording's worker.
  Dispatch reserves a CPU and 1 GiB of available RAM, estimating each worker's
  need as at least 1 GiB or 12 times the largest loaded frame. Low/unknown RAM,
  limited CPU, explicit mutable toolbox configs or restricted `run_steps` retain
  sequential execution. These are conservative estimates, not hard memory limits.
  The processing log records measured CPU availability, free RAM, frame size and
  the estimated worker budget, and explains any single-worker fallback.
  Results merge in input order; official aggregation functions run once on the
  pooled quantifications, with consistent gait segment IDs. Stop terminates all
  owned workers before deleting their private temporary files. Worker startup and
  file transfers can outweigh parallel gains for short recordings.
- Saving serializes the complete in-memory result to JSON in a background worker.
  Temporary analysis files have already been removed; saving writes a snapshot,
  including tables, metadata and provenance. It does not rerun analysis. Large
  outputs and repeated saves can therefore take time. Normalization reuses fresh
  string-keyed row dictionaries within each 1,000-row batch, retaining the standard
  JSON encoder, cooperative yields and atomic file replacement.

The portable bundle includes Python, Qt, Arrow and the scientific libraries.
These native dependencies account for most of its size. Collection hooks retain
models, readers, package metadata, licences and required DLLs while excluding
redundant loose Python source copies and unused Arrow development components.
Builds clear their app output and work directories before packaging.

## JSON saving check — 17 October 2026

Five alternating before/after pairs compared the writer at `7d7e77e` with the
updated writer on synthetic tables in one Linux process (Python 3.12, pandas
2.3.3, warm imports and file caches). Timings include the complete JSON export
and atomic replacement in the same temporary directory; fixture construction and
allocation tracing are excluded. Numeric inputs use ten normally distributed
metrics (NumPy seed 42), elapsed time, binary predictions and large integers.

| Table | Rows × columns | Before | After |
| --- | ---: | ---: | ---: |
| Numeric results | 100,003 × 13 | 0.902 s | 0.754 s |
| Results with recording keys | 100,003 × 14 | 1.085 s | 0.832 s |
| Results with timezone timestamps and nullable integers | 30,003 × 16 | 0.460 s | 0.397 s |

Median saving time fell by 14–23% in these cases. Separately measured peak traced
allocations on 3,003-row subsets fell by 22–25%; this measures temporary saving
allocations, not total application RAM. Every full output matched the previous
writer's SHA-256 digest. Regression tests also compare exact JSON bytes, float
bit patterns, large integers, column-key collisions, nested source objects and
failure cleanup after earlier batches have been written. Non-string column
labels retain their existing normalization. These warm-cache Linux measurements
do not predict Windows timings or other result distributions.

## Hidden sensor-table check — 16 October 2026

A focused Linux/Fusion/offscreen check used 250,000 samples, seven channels and
three sensor-context graphs at 1450×920. Two alternating before/after pairs
compared the former unconditional table refresh with the deferred refresh, using
five drags of eight updates per run and queued Qt painting. Median drag updates
fell from 130–150 ms to 94–106 ms; hidden model replacements fell from 44 to zero
per run, including resets between drags. The comparison reinstated the former
refresh behavior in the same source app. These synthetic timings do not predict
Windows performance. Regression tests check exact table samples on opening,
navigation, Home, new inspection and clearing results.

## Component extraction review — 16 October 2026

Compared `7811818` with `f9294cd`, using the same Python/dependencies on Linux,
Fusion/offscreen at 1450×920. Three alternating process pairs covered 20 UI
workflows, graph navigation, a 3-million-sample sensor context, loading, isolated
gait/tremor processing and saving. First-use and rebuilt portable startup used
nine process pairs. [Full samples and qualifications](performance-review.json)
include additional paired controls and source hashes.

| Measure | Before | Refactored |
| --- | ---: | ---: |
| Portable launch to startup report | 0.786 s | 0.815 s |
| First paint, in-app timer | 0.432 s | 0.492 s |
| First Data graph, including deferred imports | 0.588 s | 0.600 s |
| First Results graph, including deferred imports | 0.659 s | 0.636 s |
| First sensor-context opening | 0.199 s | 0.199 s |
| Large sensor-context peak process RSS | 623.2 MiB | 623.6 MiB |

The extraction adds a small startup cost; bundle growth is 35 KiB with the same
1,746 files. Both portable builds pass identical smoke checks, including all
modules, parallel recordings, graphs, saving and reopening. Startup still imports
no plotting/tabular/scientific libraries. All loaded-data and normalized result
digests match; 16 service/plotting files remain byte-identical, and 84 moved
algorithms match after normalizing dependency access. The focused suite passed
241 tests; the unchanged application commit previously passed 878 tests with one
Windows-only skip.

Some timings need caution. Independent-process medians increased for selecting
three 30-minute series (0.686→0.921 s) and TSDF statistics (2.068→5.292 s).
Same-process/CPU controls measured 1.197→1.267 s for series selection and
2.080→2.157 s for statistics on the exact same frame. Sensor panning varied in
both directions. Graph/context pixels and plot/draw counts match; view-accessor
overhead was below 1 ms across nine profiled actions. These controls do not
reproduce the largest increases, but cannot establish zero timing impact.

The main existing costs remain dense raw-graph panning (about 0.32–0.34 s/frame
with three modalities) and large JSON saves (about 2.6–2.9 s for 66.6 MB).
No large repeatable slowdown attributable to the extraction was established.
Windows packaged measurements on representative recordings are still needed
before a platform-wide performance guarantee; these are warm-cache Linux tests,
not clinical throughput estimates or a long-session memory-leak proof.

## Earlier optimization measurements

A Linux source-launch check on 15 October 2026 compared commit `b1ae33a` with
first-use graph construction. After one warmup per version, five fresh processes
per version ran in alternating order, with empty history, warm OS/font caches and
no concurrent tests or builds. Median first paint decreased from 1.17 s to 0.60 s;
launch-to-report decreased from 1.21 s to 0.64 s. Startup loaded no Matplotlib,
pandas, Arrow or scientific pipeline modules. First graph use pays the deferred
initialization cost once. These source measurements do not predict Windows cold
launch or antivirus overhead; the packaged benchmark checks the same import boundary.

A Linux clock-preview check on 15 October 2026 compared commit `311500a` with
the clock-only preview on two recordings of 500,000 samples each (six IMU channels,
green PPG and nanosecond-precision timestamps). With warm imports, missing-sample
exclusion and three repeats, deriving clocks for Tremor, Gait and all three modules
took a median 1.72 s before and 0.15 s after. Every clock matched exactly. This
measures uncached calculations; equivalent module selections reuse the UI cache.

An isolated Linux check on 15 October 2026 compared time-interval selection with
commit `4092a6e` on six graphs of 30,000 points each (Fusion, 1450×920, eight drag
updates with queued Qt painting). Median updates decreased from 1.26 s to 7.3 ms
at normal pixel density and from 1.87 s to 8.6 ms at double density. Full graph
redraws decreased from eight to zero during each drag. These are synthetic,
offscreen measurements; Windows timings depend on the display and data.

A warm three-repeat scrollbar benchmark on the same six graphs (eight updates
per drag, normal pixel density) measured 0.62 s → 0.10 s per update for a wide
view and 0.11 s → 0.057 s when zoomed in. The wide view uses a temporary
peak-preserving preview; stopping and exporting retain the full original bars.

An isolated Linux loading check on 14 October 2026 compared these changes with
commit `7ed2988` using a synthetic 24-hour, 100 Hz TSDF recording (8,640,000 rows,
six int16 sensor channels, 0.01 scaling factors and difference-ms time). Warm
imports and file caches, five repeats per operation, and exact comparisons of
the complete loaded frames and statistics produced these median times:

| Operation | Before | After |
| --- | --- | --- |
| Decode and scale TSDF | 0.50 s | 0.40 s |
| Complete initial statistics | 2.10 s | 1.84 s |
| Decode, scale and complete statistics | 2.40 s | 2.07 s |

The combined operation took about 14% less time. Separately measured peak traced
allocations were essentially unchanged: remaining reader and time-statistic
workspaces still dominate the peak. This comparison excludes Qt rendering and
does not predict cold-file loading, Windows timings or other input distributions.
Regression cases compare exact dtypes, missingness and float bit patterns against
the previous scaling operation, and verify untouched files/shared source arrays.

An isolated Linux check on 14 October 2026 compared the production single-worker
and automatic paths on four prepared gait recordings, each an eightfold synthetic
repetition of the bundled recorded IMU fixture (583,576 rows; about 97 minutes).
Complete runtime, including process startup, private transfers and pooled
aggregation, decreased from 8.72 s to 7.09 s with two workers. All result values
matched. This one measurement is not a timing guarantee for Windows or other data.

## Reproduce measurements

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
| `ui-performance.json` | Synthetic input switching, settings, series selection in all four Results graph views, visible table controls, exports and history |
| `pan-performance.json` | Results time scrolling and interval selection, raw toolbar drags and queued painting |
| `sensor-context-performance.json` | First and repeated context openings on a large synthetic recording |

Both Windows workflows publish these files in the separate
**ParaDigMaStudio-build-reports** artifact. They are development reports and
are not needed to run the app. Security provenance and checksums stay in the
application download.

Two additional source benchmarks are available for manual comparisons:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_first_use.py --graph data --report build-reports/first-data-graph.json
.\.venv\Scripts\python.exe scripts/benchmark_first_use.py --graph results --report build-reports/first-results-graph.json
.\.venv\Scripts\python.exe scripts/benchmark_processing.py --report build-reports/processing-performance.json
```

The first-use probe starts without plotting or scientific imports, measures the
first graph opening and checks canvas reuse through 120 page changes. The processing
probe uses temporary synthetic files, including a 24-hour TSDF recording, and the
recorded scientific fixture under `tests/data/paradigma`. It measures complete
loading/statistics, single/two-recording gait and tremor processing, and a
600,000-row saved-run round trip. It verifies unchanged inputs and output digests
outside the timers. Its two-worker workload requires sufficient CPU/RAM and fails
explicitly when the automatic resource policy selects one worker. These manual
reports are not generated by the Windows workflows.

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
