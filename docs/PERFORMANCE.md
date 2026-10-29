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
- Large multi-recording loads calculate exact initial statistics for up to two
  recordings concurrently using shared, read-only frames. One CPU and a GiB of
  RAM are reserved; each statistics worker budgets eight double-precision arrays
  for the longest recording. Unknown/insufficient RAM, fewer than three available
  CPUs, a single recording or batches whose longest recording has fewer than
  100,000 rows use the existing sequential path. Reading, TSDF scaling and
  pipeline steps are unchanged.
- Continuous raw plots keep the original samples and select their drawing path
  from the current visible range. Up to 20,000 visible samples render in full;
  wider views retain first/last samples, extrema and missing-data boundaries,
  using the physical plot width to bound drawing work. Each channel retains at
  most three summary levels within 4 MiB. Time-coordinate conversion/range lookup
  is shared across channels, and narrow views avoid scanning the full recording.
  Figure exports render every visible original sample. This applies to Data and
  sensor context; pipeline inputs and statistical calculations are unchanged.
- Saved runs decode and prepare clocks, timing and coverage in the background.
  JSON files of at least 8 MiB use one owned spawned reader process, avoiding
  long JSON-decoder calls holding the GUI interpreter lock. Small files and
  in-memory snapshots use the existing worker directly. Only parent-created
  private transfer files use pickle; user files remain JSON. Opening installs
  Overview first and leaves full graph construction until Graphs is selected.
- Results reuse prepared graph data and existing plots where possible. Hidden
  graphs defer painting, and rendering excludes bars outside the visible range.
  Compatible selections reuse bounded layout/text measurements. Recently removed
  bar plots retain original geometry in a four-entry, 128 MiB cache, cleared on
  result, view or display-clock changes. Detailed metrics share converted time
  coordinates per dataset/row selection/clock; up to four coordinate entries
  use at most 32 MiB within the same 128 MiB total budget. Source references are
  weak, and changed inputs invalidate reuse. The cache owns no detached axes. Exports
  always solve their complete layout, and unsupported screen layouts fall back
  to the native solver. Rapid toggles coalesce paints without delaying selection
  signals; the pinned time ruler paints after the final graph draw.
  Fresh layouts skip detailed cache-key measurement when no stored shape can
  match. Within a native screen-layout solve, safe tick updates are reused until
  limits or row/locator geometry changes. The adapter is removed before painting
  and on errors; figure exports retain the unmodified native solver.
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
  including when the figure exceeds the timepoint overlay's memory budget.
  Raw and Results graphs share time-interval selection and horizontal scrolling;
  Results keeps its renderer-specific optimizations. Dense full-recording plots
  still cost more than zoomed views.
- Sensor context indexes source timestamps and loads the visible window using
  the source-rate rendering above, while preserving the initial
  context, selected time and navigation history. Sensor tables build and size
  columns only when Tables is selected; time scrolling in Graphs skips that work.
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

These cache and worker budgets do not bound total session memory. Saved inactive
runs can retain original source frames and complete result tables for reopening
and sensor context. Repeated analyses of different long recordings therefore need
representative memory testing; saving a run does not necessarily release its
in-memory data.

The portable bundle includes Python, Qt, Arrow and the scientific libraries.
These native dependencies account for most of its size. Collection hooks retain
models, readers, package metadata, licences and required DLLs while excluding
redundant loose Python source copies and unused Arrow development components.
Builds clear their app output and work directories before packaging.

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
Raw cases use a zoomed interval and the shared horizontal scrollbar, reported as
`data_scroll_3_modalities` and `context_scroll_3_modalities`. Historical raw-pan
measurements describe a different interaction.
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
| `pan-performance.json` | Results time scrolling, interval selection, shared-axis owner changes in all four views, raw time-scrollbar drags and queued painting |
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

The sensor-context probe also checks 20-second raw Data zooms against every
original timestamp/value and reports `raw_zoom_seconds`, `raw_visible_samples`
and the full retained-input checksum. `--samples 8640000` exercises one day at
100 Hz. The checksum and equality checks run outside its action timers.

Use `--loading-only --recordings 7` with `benchmark_processing.py` to isolate
multi-recording loading. `--samples 8640000` (the default) represents one day at
100 Hz per recording. It reports batch decoding, sequential and automatic exact
statistics, and complete load-plus-statistics timings separately. Complete
frame/statistic digests and source-file checks run outside the timers; no values
are sampled or approximated. `--repeats 3` controls the repetitions.

Compare measurements with the same dependencies, inputs, window dimensions and
cache state. Linux offscreen timings do not predict local Windows performance,
cold startup or antivirus overhead. CI checks import boundaries, retained values,
cache reuse and redraw behavior rather than imposing hardware-specific timing
limits. See the [test guide](TEST_SUITE.md) and
[scientific methodology](SCIENTIFIC_TESTS.md) before changing these boundaries.

## Historical evidence

- [October 2026 runtime comparisons](archive/performance/runtime-measurements-2026-10.md):
  source rendering, reopening, loading, graph creation/selection, saving and component extraction.
- [Component extraction evidence, 16 October](archive/performance/component-review-2026-10-16.json):
  full samples, unchanged-output checks and platform qualifications.
- [Earlier performance history](archive/performance/REVIEW_HISTORY.md):
  version-specific comparisons and their original JSON reports.

These measurements describe their stated commits, workloads and cache conditions.
Current CI reports describe the commit they tested. The
[archived codebase audit](archive/codebase-audit-0.5.23.md) records the earlier
structural refactor.
