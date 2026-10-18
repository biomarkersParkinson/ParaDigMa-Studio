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
  Compatible selections reuse bounded layout/text measurements. Recently removed
  bar plots retain original geometry in a four-entry, 128 MiB cache, cleared on
  result, view or display-clock changes. The cache owns no detached axes. Exports
  always solve their complete layout, and unsupported screen layouts fall back
  to the native solver. Rapid toggles coalesce paints without delaying selection
  signals; the pinned time ruler paints after the final graph draw.
  Removing the shared time-axis owner retains the remaining axes, paths and
  per-graph settings. Results scrollbar drags and horizontal trackpad gestures
  reuse settled axes, tick positions and measured date-label widths. Ordered
  intervals use indexed viewport lookup. Dense Results plots retain pixel-column
  minima/maxima, gaps and long intervals both while moving and at rest, so narrow
  bars do not disappear on release. Zooming resolves individual intervals, and
  exports always use original bars. Painting skips offscreen plots after selection
  and when a horizontal gesture ends. Vertical scrolling extends the existing
  static image with newly exposed plots; revisiting painted plots needs no new
  rasterization while limits and layout stay unchanged. This shares the row
  marker overlay's existing 32 MiB budget, uses weak axis references, and falls
  back to a fresh viewport draw after changes or when no background is available.
  Exports render every graph. Interval selection paints directly over the cached
  Qt image without redrawing graph data,
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

## Plot-series selection check — 18 October 2026

Paired processes compared `d9ca122` with validated layout reuse, bounded original
bar-geometry reuse and coalesced ruler painting. Linux/Fusion/offscreen at
1450×920, the same Python 3.12/dependencies, alternating process order, three
real label-click repetitions per view and no concurrent tests/builds. Timings
include queued paints; fixture preparation, imports and source-hash checks are
outside the timer. Each row reports median deselection / re-selection latency.

| Workload | View | Before | After |
| --- | --- | ---: | ---: |
| Six graphs × 30,000 values | Detailed | 240 / 302 ms | 116 / 140 ms |
| Same | 30-minute epochs | 200 / 228 ms | 93 / 116 ms |
| Same | Day | 173 / 202 ms | 79 / 88 ms |
| Same | 24-hour profile | 208 / 233 ms | 84 / 98 ms |
| Six graphs × 150,000 values | Detailed | 380 / 581 ms | 141 / 168 ms |
| Twelve graphs × 30,000 values | Detailed | 357 / 474 ms | 133 / 154 ms |
| Six graphs, double display scale, limits and timepoint visible | Detailed | 258 / 377 ms | 148 / 177 ms |
| Recorded fixture, official gait outputs | Detailed | 218 / 233 ms | 164 / 135 ms |

The synthetic cases reduced repeated-toggle medians by 38–71% across all four
views. First creation still constructs complete geometry and may require a full
layout: Detailed first selection was 339→318 ms for six graphs, 736→757 ms for
150,000 values and 459→596 ms for twelve graphs. The short recorded gait fixture
has missing aggregates; annotated rows retain native layout. Its aggregate-view
changes ranged from 8% slower to 16% faster across both display scales, so these
cases do not establish a consistent gain. Windows measurements remain separate
and no platform-wide timing guarantee follows from these small samples.

Repeated synthetic selections avoided full layout solves after compatible row
templates were available. Every measured click painted the main canvas and ruler
once; rapid-click regression tests also require a single final paint. The largest
measured deselected-geometry accounting was 79.8 MiB for one 150,000-value plot;
the cache evicts to both its byte and entry limits. Layout and text caches retain
at most 32 layouts and 2,048 text measurements, containing no result arrays.
Source-frame hashes matched throughout. Tests compare native/cached pixels at
both display scales, original path identity, complete 600-DPI PNG/PDF/SVG exports,
navigation, cache invalidation and release of discarded axes/arrays. Dense gait
appearance while moving and at rest remains covered by the checks below.

## Detailed gait density correction — 18 October 2026

The moving plot used a pixel-column envelope while the settled plot drew each
original rectangle. At multi-day scales, subpixel gait bars could disappear in
the settled raster image even though every original output was still present.
The Results canvas now requests the same dense display at rest and while moving.
Only bars narrower than a physical display pixel enter the envelope; larger
intervals stay intact. Zoomed plots and exports retain original bar geometry.
Raw and sensor-context canvases keep their existing rendering.

Regression tests use gait range of motion and peak velocity without timestamps,
positioned from official-style segment metadata, with both scrollbar and trackpad
gestures at two display scales. They compare moving/stopped pixels exactly.
Additional checks cover visible density, positive/negative peaks, missing gaps,
long intervals, zoomed individual bars, original tables/paths and complete exports.
A 900×300 synthetic reproduction retained 629 colored columns while moving but
only 140 at rest; the correction retained 629 in every state with the same 27,000
original finite intervals. A source-app benchmark (Linux/Fusion/offscreen,
six graphs × 30,000 values, three eight-update gestures) measured wide-scroll
release at 490 ms before and 221 ms after. Continuous updates were 75–80 ms;
these timings describe this synthetic check and do not predict Windows behavior.

## Results responsiveness check — 17 October 2026

Two before/after pairs compared `a05bded` with plot reuse and viewport painting
in separate Linux/Fusion/offscreen processes at 1450×920, using six continuous
metrics with 30,000 values each. The order was before/after/after/before, with
three gestures or selections per process and six updates per gesture. Timings
include queued Qt paints, warm imports and caches, without profiling or coverage.

| Interaction | Before | After |
| --- | ---: | ---: |
| Deselect the shared-axis owner, Detailed | 1,015 ms | 390 ms |
| Deselect the shared-axis owner, 30-minute epochs | 301 ms | 196 ms |
| Deselect the shared-axis owner, Day | 222 ms | 144 ms |
| Deselect the shared-axis owner, 24-hour profile | 277 ms | 166 ms |
| Finish a wide horizontal scroll | 686 ms | 480 ms |
| Finish a zoomed horizontal scroll | 189 ms | 155 ms |
| Wide scroll update | 71 ms | 70 ms |

These are pooled medians, not Windows performance guarantees. The final extended
pan benchmark reproduced the main gains (392 ms for Detailed owner removal and
481 ms for wide-scroll release). Continuous horizontal scrolling remains the next
rendering bottleneck. Source-frame hashes stayed unchanged. Tests check retained
path identity, shared navigation, complete exports, exact visible RGBA pixels at
both display scales, new viewport painting, marker changes, failure recovery and
release of discarded graph objects. They replace the former requirement to paint
all offscreen graphs on release with pixel equivalence and complete-export checks.

The pan benchmark now measures removal and re-addition of the actual shared-axis
owner in all four views; it does not assume the first tree item remains the owner.
At that stage deselected-plot caching was deferred. The 18 October selection
check above measures the subsequent bounded geometry cache and its tradeoffs.

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
view and 0.11 s → 0.057 s when zoomed in. That version used a temporary
peak-preserving preview and restored individual bars on release. The density
correction above now keeps a consistent pixel envelope on screen; exports
continue to retain every original bar.

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

The panning benchmark also measures Plot series through real label clicks in
all four views, recording first selection, repeated selection, median/tail
latency, retained axes and main/ruler draw counts. To isolate selection work,
use `--selection-only`; `--rows 150000 --graphs 12` changes the synthetic load,
`--pixel-ratio 2` checks the second display scale, and `--with-controls` includes
the limits panel and a selected timepoint. Run identical settings before and
after an optimization. First-selection timings are reported separately from
repeated clicks; hardware timings remain diagnostic, not strict CI limits.
`--results path/to/saved-run.json --selection-only` measures actual exported or
saved results, including gait metrics without individual timestamps. Reports
also include the bounded cache's retained-geometry accounting after each click.

Use `--first-creation-only --repeats 3` to measure fresh graph selections in
each view, followed by a label click on a previously unseen metric. Each sample
uses a fresh window; prepared tables and the initialized workspace are outside
the timers, and display caches are cleared before the first selection. The
unseen metric can reuse preparation shared by the other metrics in its dataset.
The same rows/graphs, saved-results, display-scale and controls options apply.
`--allocations` adds peak traced Python allocations in a separate diagnostic
run; it changes timings and does not measure all native Qt/renderer memory.

| Report | Measures |
| --- | --- |
| `performance.json` | Fresh packaged launches, first paint, import boundaries and bundle component sizes |
| `ui-performance.json` | Synthetic input switching, settings, series selection in all four Results graph views, visible table controls, exports and history |
| `pan-performance.json` | Results time scrolling, interval selection, shared-axis owner changes in all four views, raw toolbar drags and queued painting |
| `creation-performance.json` | Fresh selections and unseen metric clicks at double display scale, first-view/metric latency, layout/paint counts and retained caches |
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
first graph opening and checks canvas reuse through 120 page changes. It accepts
`--repeats 3` for independent subprocess
samples and `--pixel-ratio 2` for the second scale. It reports workspace opening
and the first explicit scaled draw separately from populated-metric creation.
The processing probe uses temporary synthetic files, including a 24-hour TSDF recording, and the
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
