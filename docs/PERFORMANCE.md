# Performance and measurement

This guide describes runtime behavior on `main`, the available benchmarks, and
how to compare a performance change. Use [Development](DEVELOPMENT.md) for setup
and packaging, and [Architecture](ARCHITECTURE.md) for component ownership and
execution boundaries. Dated measurements are linked under
[Historical evidence](#historical-evidence).

- [Current runtime behavior](#current-runtime-behavior)
- [Cache and worker budgets](#cache-and-worker-budgets)
- [Reproduce measurements](#reproduce-measurements)
- [Investigate and compare results](#investigate-and-compare-results)
- [Historical evidence](#historical-evidence)

## Current runtime behavior

### Startup and first graph use

Startup defers pandas, Arrow and scientific pipeline imports until needed.
Matplotlib and the three graph workspaces initialize on first use. Opening
Analyze, Runs or an empty Results overview preserves that deferral; later graph
visits reuse their canvases and controls.

The portable app reuses a per-user Matplotlib font cache. A first graph opening
still pays deferred import and construction costs. Measure app startup, first
graph use and repeated graph interactions separately.

### Loading and configuration previews

Loading finishes exact initial statistics before displaying the recording.
Inspection counts missing values once per column and reuses those counts in the
summaries. Channel-wise validity checks avoid copying the complete sensor matrix;
finite channels avoid a filtered sample copy, and quantiles use their own
workspace. TSDF scaling casts and multiplies into one double-precision output
array, retaining the official reader and metadata validation.

Large batches can calculate statistics for two recordings concurrently using
shared, read-only frames. Decoding and TSDF scaling finish before statistics begin.
The [worker policy](#worker-selection) decides whether statistics run concurrently.

Statistics and clock previews use bounded background caches. Recording switches
reuse previews, and obsolete requests cannot replace the current selection.
Analyze module changes derive recording clocks without constructing result
alignments. Equivalent sensor requirements reuse their clock preview; manual
Time origin edits take precedence over pending previews.

### Raw graphs and sensor context

Raw graphs retain original samples and choose a drawing path for the visible
range. Up to **20,000 visible samples** render in full. Wider views preserve
first/last samples, extrema and missing-data boundaries, with drawing work based
on physical plot width. Channels share time-coordinate conversion and range
lookup; ordered timestamps allow narrow views to avoid scanning the full recording.
Figure exports render every visible original sample.

Sensor context indexes the source timestamps and loads the visible window while
preserving its initial context, selected time and navigation history. Sensor
tables build and size columns when Tables is selected; scrolling in Graphs skips
that work. Later table visits reuse the model until the samples change. Original
tables and exports retain all samples.

Raw and Results graphs share time-interval selection, horizontal scrolling and
hand dragging. Results adds the rendering optimizations below.

### Results graphs

Results reuse prepared graph data, converted time coordinates and existing plots
where possible. Removing the shared time-axis owner retains the remaining axes,
paths and per-graph settings. Hidden graphs defer painting, and rendering excludes
bars outside the visible time range.

The main rendering shortcuts are:

- **Series changes:** recently removed bar plots retain original geometry in a
  bounded cache. Compatible selections reuse layout/text measurements. Rapid
  toggles coalesce paints while selection signals remain immediate; the pinned
  time ruler paints after the final graph draw.
- **Horizontal navigation:** scrolling reuses settled axes, tick positions and
  measured date-label widths. Ordered intervals use indexed viewport lookup.
  Dense plots preserve pixel-column minima/maxima, gaps and long intervals both
  during movement and after release. Zooming resolves individual intervals.
- **Vertical scrolling:** the canvas adds newly exposed plots to its static image.
  Revisiting painted plots reuses that image while limits and layout are unchanged.
  Missing or invalid backgrounds fall back to a fresh viewport draw.
- **Selection overlays:** interval selection paints over the cached Qt image
  without redrawing graph data, including figures too large for the timepoint
  background cache.

Layout reuse is conditional: unmatched layouts use the native solver. Fresh
layouts skip cache-key measurement when no stored shape can match; within a
native screen-layout solve, safe tick updates are reused until limits or geometry
change. Temporary adapters are removed before painting and on errors.
Figure exports use the unmodified native solver, original bars and every graph.
Dense full-recording views still cost more than zoomed views.

### Analysis execution

A single recording uses one owned process. Multiple original recordings can use
two reusable processes, with one native computation thread per worker. Gap
sections stay inside their original recording's worker. Resource/configuration
fallbacks are described under [Worker selection](#worker-selection).

The processing log explains the chosen worker count and any fallback.
Resource-based decisions include CPU/RAM measurements and frame/worker size
estimates when known. Process startup and file transfers can outweigh parallel
gains for short recordings. Results merge in input order; official aggregation
runs on pooled quantifications, with consistent gait segment IDs. Stop terminates
and joins owned workers before their private temporary files are removed.

### Saving and reopening

Saving serializes a complete in-memory result snapshot to JSON in a background
worker, including tables, metadata and provenance. Analysis has already finished
and its temporary files have been removed. Large outputs and repeated saves can
therefore take time. Normalization reuses fresh string-keyed dictionaries in
1,000-row batches, with the standard JSON encoder, cooperative yields and atomic
file replacement.

Reopening saved runs decodes and prepares clocks, timing and coverage in the
background. JSON files of at least **8 MiB** use an owned spawned reader process
to keep long decoder calls away from the GUI interpreter lock. Small files and
in-memory snapshots use the worker directly. User files remain JSON;
parent-created private transfer files use pickle. Opening installs Overview first
and defers full graph construction until Graphs is selected.

### Portable bundle size

The bundle includes Python, Qt, Arrow and the scientific libraries. Native
dependencies account for most of its size. Collection hooks retain models,
readers, package metadata, licences and required DLLs while excluding redundant
loose Python source copies and unused Arrow development components. Builds clear
their app output and work directories before packaging.

## Cache and worker budgets

### Rendering caches

| Cache | Bound and scope |
| --- | --- |
| Raw channel summaries | At most three summary levels within 4 MiB per channel |
| Results bar geometry | At most four entries; shares a 128 MiB total with converted coordinates |
| Results time coordinates | At most four entries within 32 MiB, included in the shared 128 MiB total |
| Static plot background | 32 MiB for row-marker and Results viewport reuse; viewport reuse shares the existing image |

Results caches invalidate on result, view or display-clock changes. Source and
axis references are weak where retained for reuse; the geometry cache owns no
detached axes. Changed inputs invalidate their converted coordinates.
The implementing limits are in
[`raw_signals.py`](../src/paradigma_studio/raw_signals.py),
[`result_plot_cache.py`](../src/paradigma_studio/result_plot_cache.py),
[`plotting.py`](../src/paradigma_studio/plotting.py) and
[`result_canvas.py`](../src/paradigma_studio/result_canvas.py).

### Worker selection

Two-worker selection leaves one CPU and **1 GiB of available RAM** for the
interface and other work. Both policies are implemented in
[`analysis_limits.py`](../src/paradigma_studio/analysis_limits.py):

| Work | Conditions for two workers |
| --- | --- |
| Initial statistics | At least two recordings, a longest recording of at least 100,000 rows, at least three available CPUs, and known RAM sufficient for two statistics workers plus the reserve |
| Analysis | Multiple compatible original recordings, CPU/RAM headroom, and the ordinary complete processing path |

A statistics worker budgets eight double-precision arrays for the longest
recording, with a **64 MiB minimum**. An analysis worker budgets the larger of
**1 GiB** or **12 times the largest loaded frame**. Unknown or insufficient RAM
selects one worker. Custom mutable toolbox configurations, restricted `run_steps`
and ambiguous recording identifiers also keep analysis sequential.

These are conservative estimates, not hard memory limits. Individual cache
budgets do not bound total session memory either: inactive runs can retain source
frames and complete result tables for reopening and sensor context. Saving a run
does not necessarily release that data. Memory comparisons should cover repeated
analyses of representative long recordings.

## Reproduce measurements

### Choose a benchmark

| Task | Probe and report |
| --- | --- |
| App launch and bundle size | `benchmark_desktop.py` → `performance.json` |
| Common UI workflows | `benchmark_workflows.py` → `ui-performance.json` |
| Time scrolling, hand dragging, interval selection and series changes | `benchmark_pan.py` → `pan-performance.json` |
| Fresh populated views and unseen metrics | `benchmark_pan.py --first-creation-only` → `creation-performance.json` |
| Context opening and original-sample raw zooms | `benchmark_sensor_context.py` → `sensor-context-performance.json` |
| First empty graph workspace in a fresh process | `benchmark_first_use.py`; manual source probe |
| Loading/statistics, processing and saved-run round trips | `benchmark_processing.py`; manual service probe |

The desktop probe measures the built executable. UI probes run the source app;
the processing probe calls services directly. Benchmark scripts live under
[`scripts/`](../scripts/).

### Standard Windows reports

Install the [reviewed environment](DEPENDENCIES.md#install-and-verify) and
[build the Windows executable](DEVELOPMENT.md#build-and-verify-a-windows-executable).
Run from the repository root in PowerShell, keeping reports outside the portable
folder:

```powershell
New-Item -ItemType Directory -Force build-reports | Out-Null
uv run --locked --all-groups python scripts/benchmark_desktop.py dist/ParaDigMaStudio/ParaDigMaStudio.exe --report build-reports/performance.json
uv run --locked --all-groups python scripts/benchmark_workflows.py --report build-reports/ui-performance.json
uv run --locked --all-groups python scripts/benchmark_pan.py --report build-reports/pan-performance.json
uv run --locked --all-groups python scripts/benchmark_sensor_context.py --report build-reports/sensor-context-performance.json
uv run --locked --all-groups python scripts/benchmark_pan.py --first-creation-only --rows 150000 --pixel-ratio 2 --with-controls --report build-reports/creation-performance.json
```

Both [Windows](../.github/workflows/windows.yml) and
[signed Windows](../.github/workflows/windows-signed.yml) workflows publish these
five reports in the **ParaDigMaStudio-build-reports** artifact. UI probes use
offscreen Qt in CI. Reports are separate from the application download, which
retains its security provenance and checksums.

The startup report includes fresh-process launches, first paint, deferred-import
checks and bundle component sizes. It uses existing OS/font caches and empty run
history. Source UI probes report interaction timings with warm imports and
include queued Qt painting.

### Graph navigation, selection and creation

The navigation probe measures drag frames and release redraws separately. It
covers hand dragging in all four Results views and raw Data/context views.
Raw scrollbar cases are named `data_scroll_3_modalities` and
`context_scroll_3_modalities`; hand cases use `results_hand_*`,
`data_hand_3_modalities` and `context_hand_3_modalities`. Older raw-pan reports
measured a different interaction.

To isolate Plot series changes, use real label-click measurements:

```powershell
uv run --locked --all-groups python scripts/benchmark_pan.py --selection-only --rows 150000 --graphs 12 --pixel-ratio 2 --with-controls --report build-reports/series-selection.json
```

Reports separate first selection from repeated toggles in detailed, 30-minute,
day and 24-hour profile views. They include median/tail latency, retained axes,
main/ruler draw counts, layout solves and retained geometry/coordinate bytes.
Removing a series exercises the current shared-axis owner.

Creation mode uses a fresh window per sample. Prepared tables and the initialized
workspace are outside its timers; display caches are cleared before the first
view selection. A later label click adds a previously unseen metric, which can
reuse preparation shared by metrics in its dataset. `--repeats 3` is the default.

Both selection and creation modes accept `--results path/to/saved-run.json` to
measure actual saved/exported results, including metrics without individual
timestamps. Replace the example path with the file being investigated. The same
display-scale and controls options apply to both modes and input types.
`--rows` and `--graphs` size the synthetic input; a supplied results file provides
its own tables and metrics. The two modes are mutually exclusive. `--allocations`
is a creation-mode diagnostic for a separate run: it changes timings and measures
traced Python allocations, excluding some native Qt/renderer memory.

### First graph use

These manual probes start without plotting or scientific imports and measure the
first empty graph workspace. Run after creating `build-reports`:

```powershell
uv run --locked --all-groups python scripts/benchmark_first_use.py --graph data --repeats 3 --report build-reports/first-data-graph.json
uv run --locked --all-groups python scripts/benchmark_first_use.py --graph results --repeats 3 --report build-reports/first-results-graph.json
```

Each sample uses a fresh subprocess. The probe separates workspace opening from
its first explicit scaled draw and checks canvas reuse through 120 page changes.
Add `--pixel-ratio 2` for the second display scale. Populated-metric creation is
measured by the creation mode above. These probes retain warm OS/font caches and
are not generated by the Windows workflows.

### Loading, processing and saved results

The manual processing probe generates temporary synthetic files, including a
24-hour TSDF recording, and uses the recorded IMU fixture under
[`tests/data/paradigma`](../tests/data/paradigma/):

```powershell
uv run --locked --all-groups python scripts/benchmark_processing.py --report build-reports/processing-performance.json
uv run --locked --all-groups python scripts/benchmark_processing.py --loading-only --recordings 7 --repeats 3 --report build-reports/loading-performance.json
```

The full run measures loading/statistics, single/two-recording gait and tremor
processing, and a **600,000-row saved-run round trip**. Its two-worker comparison
requires sufficient CPU/RAM and fails explicitly if the automatic policy selects
one worker. `--loading-only` skips analysis and saving; with multiple recordings,
it reports batch decoding, sequential/automatic exact statistics, and complete
load-plus-statistics times separately.

`--samples` controls TSDF size. The default, **8,640,000 samples**, represents one
day at 100 Hz per recording; `--recordings` controls the batch count. Input/output
digests and source-file checks run outside the timers. The probe uses warm
imports/file caches, retains complete values, and is not generated by Windows CI.

For raw visual detail on the same scale, add `--samples 8640000` to the
sensor-context probe. It checks 20-second Data zooms against every original
visible timestamp/value and reports `raw_zoom_seconds`, `raw_visible_samples`
and the retained-input checksum. Equality/checksum checks run outside the action
timers.

## Investigate and compare results

### Capture the slow operation

Record the Studio version or commit, platform, dependency lock and input format,
size, duration, channel count and number of recordings. State whether the delay
occurs on first-ever use, the first load after restarting, the first graph visit,
or repeated actions in the same session. Identify the operation being timed:
opening a file, preparing statistics, creating a graph, processing or saving.

Choose the corresponding probe above. For analysis slowdowns, include the worker
selection details from the processing log. Keep source and packaged-app results
identified separately, along with the Qt backend/style, window dimensions,
visible time range, graph count and display scale.

### Compare equivalent runs

1. Use the same dependencies, inputs, native thread limits, available CPU/RAM,
   display settings and cache state before and after a change.
2. Repeat the workload and compare full samples, medians and tail timings where
   reported. Check draw/layout counts and retained-cache bytes alongside elapsed
   time to understand which work changed.
3. Keep profiling/allocation tracing in separate diagnostic runs. Retain the
   probes' unchanged-input and output-value checks outside the timed operations.
4. Run the relevant [regression tests](TEST_SUITE.md) and
   [scientific comparisons](SCIENTIFIC_TESTS.md) when changing data or processing
   boundaries.

Fresh-process launch probes reuse OS/font caches; a cold boot or first-ever load
has different conditions. Linux offscreen timings also do not predict local
Windows behavior or antivirus overhead. Use representative Windows recordings
when investigating a local report.

Elapsed times are diagnostic rather than hardware-specific CI thresholds. CI
checks deferred imports, retained values, cache reuse and redraw behavior. A
faster draw must preserve source data, scientific outputs and export fidelity.

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
