# Performance review

The app now opens before importing the scientific pipelines, reuses fonts between
portable-app launches, and ships fewer unused Arrow files. Analysis algorithms,
classifiers, supported sensor formats, parameters and exports remain unchanged.

## Startup and bundle measurements (0.2.2)

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

## Recording switching in 0.5.1

Switching the inspected file now reuses its loaded sensor/time descriptives,
preserves the selected Data tab and channels, and leaves the batch's analysis
clock unchanged. Batch alignment runs when analysis settings change rather
than on every inspection switch. Graph rebuilding is deferred until Graphs is
opened when Overview or Tables is active; channel discovery reads dtypes without
copying sensor arrays.

A Linux profile with three 300,000-sample recordings measured one Overview switch
at 112 ms before these changes and 39 ms afterward. These measurements include
profiling overhead and exclude rendering a newly selected Graphs view. A regression
test checks that inspection switching does not call batch alignment or recalculate
descriptives, and that displayed samples remain identical to the source frames.

Version 0.5.1 passed 257 source tests, including all 31 scientific-equivalence
cases, with one Windows-only signing check skipped on Linux. The rebuilt Linux
bundle passed its analysis, graph, export and startup checks.

## Graph interaction in 0.5.2

A profile of a synthetic 20,000-row tremor result found unnecessary redraws of
hidden graphs and bars outside the visible time range. Graphs now defer painting
while Overview, Tables or another page is open. Changing the active table retains
existing graph axes, zoom and presentation settings when the selected plot series
remain the same; new results or changed series still rebuild the figure.

Continuous bars and presence intervals send only rectangles intersecting the
visible time range to the renderer. Every original rectangle, value and timestamp
remains available for inspection and export, including intervals crossing a view
boundary. This does not sample or average the data. Automatic Y scaling retains
all visible extrema, caches repeated requests, and updates on pan release rather
than repeatedly changing the transform during a drag. The pinned time ruler
redraws only when its position, range, label or selection changes.

Single profiled Linux/offscreen samples with the same dependencies and a
1,450 × 920 window measured a zoomed graph redraw at **274 ms before** and
**84 ms after**. A full-range redraw measured 306 ms before and 259 ms after;
it still renders every visible bar. Processing the queued UI events on Overview
fell from 321 ms to 5 ms because its hidden graph no longer paints. The first
Graphs visit performs that deferred paint. These measurements include profiling
overhead and do not establish native Windows performance or analysis speed.

Regression checks cover rendering work, unchanged original values and intervals,
restoration after a failed render, PDF/PNG exports, hidden/visible Qt transitions,
graph reuse and fresh results, and ruler synchronization. The existing scientific
equivalence tests continue to check the analysis against official ParaDigMa.

Version 0.5.2 passed 263 source tests, including all 31 scientific-equivalence
cases, with one Windows-only signing check skipped on Linux. The rebuilt Linux
bundle passed its runtime and startup checks. Native Windows validation runs in
GitHub Actions.

## Analyze controls and Data statistics in 0.5.3

Changing Analyze settings previously recalculated full recording-clock alignment
on the UI thread. Accelerometer/gyroscope-unit and split-recording changes also
triggered the same clock calculation even when they could not affect the clock. Time-unit changes updated
Data statistics synchronously. The alignment helpers additionally copied every
sensor column when renaming columns for a time-channel lookup.

Clock, sensor-descriptive and time-descriptive previews now run in background
workers. Each preview keeps one running calculation and the latest pending
request, debounces rapid changes, and caches up to 16 settings combinations.
Only results matching the latest recording and settings are displayed. Loading
new input invalidates the caches; custom origins are preserved; closing a window
does not wait for a preview. The relevant readout is disabled while its new value
is calculated. Other controls and Run Analysis remain available. Automatic run
timing continues to derive from the actual run's inputs and settings, independently
of these previews.

Clock alignment still calls the existing helpers and official ParaDigMa time
conversion. Column-name lookups now share the source data instead of copying all
sensor columns; those lookups are read-only. Data statistics retain the same
formulas and source samples. Hidden Data graphs are rebuilt when opened rather
than when a descriptive selection changes.

A Linux/offscreen profile used three recordings with 750,000 samples each, six
sensor channels, numeric time and datetime columns. Each measurement applied six
control changes synchronously, excluding painting and deferred calculations:

| UI handlers for six changes | Before | After |
| --- | ---: | ---: |
| Accelerometer units | 2.25 s | 0.31 ms |
| Split recordings | 2.83 s | 0.31 ms |
| Selected modules | 2.29 s | 0.40 ms |
| Time units | 4.13 s | 0.62 ms |

These single measurements demonstrate removal of blocking work, not a change
in scientific processing speed or native Windows timings. Background calculations
still take time. Regression tests check GUI event delivery during a blocked
preview, execution outside the GUI thread, stale-result suppression, cache
invalidation, resets, custom run parameters, failures and nonblocking close.

Version 0.5.3 passed 270 source tests, including all 31 scientific-equivalence
cases, with one Windows-only signing check skipped locally. The rebuilt Linux
bundle passed its runtime and startup checks; Windows validation runs in GitHub
Actions.

## Verification and Windows measurements

For the 0.2.2 startup changes, **139 tests passed**, with one Windows-only test skipped locally. This included
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

## Whole-app review (0.5.4)

The review covered startup and bundle contents, input inspection and recording
switching, Analyze options, navigation, Results construction and interactions,
exports, and run history. The scientific pipeline is still ParaDigMa 1.1.2 with
the same inputs and defaults; no algorithm or result precision was changed.

The remaining major UI bottleneck was repeated full rendering of Results bars
when selecting a row, clicking a graph, switching the active table, or toggling
timing columns. Selection markers now reuse the static plot image. Actual changes
to limits, styles or data trigger a normal redraw. Cached highlights match full
rendering pixel for pixel in regression tests, and image exports retain markers.
The image cache has a 32 MiB limit and falls back to regular drawing for larger
figures. Every original bar and interval remains available, including after zoom.

Table views now share read-only native columns and retain at most four prepared
views. Individual cells reuse their column arrays instead of repeatedly indexing
the DataFrame. New results and model changes invalidate these caches. Unchanged
clock requests and Results layouts also avoid repeated widget updates, and hidden
Data/context graphs defer painting until shown.

JSON export uses the fast standard encoder in 5,000-row batches, reducing temporary
row objects and file size. The schema, numbers, timestamps and missing-value
representation remain unchanged; whitespace is now compact. Exports still write
a temporary file and replace the destination only on success. The export chooser
uses a background worker, allowing navigation and result exploration while writing.

A reproducible synthetic benchmark is provided in `scripts/benchmark_workflows.py`.
Both Windows workflows include its report as `ui-performance.json`, alongside the
existing packaged startup and bundle report. It runs the source app with native
Qt, rather than the packaged executable, and uses only temporary test files and
history. Timing is reported without hardware-dependent pass/fail limits.

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_workflows.py --report ui-performance.json
```

Large full-range graphs still need to render their original bars when adding
series or changing limits. Initial scientific imports, parsing large recordings,
and official analysis remain real work; these run outside the GUI thread.
Cancellation retains its isolated analysis process. Required native Qt, Arrow,
SciPy and classifier libraries remain in the portable bundle: removing them would
compromise supported formats or scientific processing. No dependency was removed
or added by this review.

### Before/after measurements

Compared commit `38a2e2e` (0.5.3) with 0.5.4 on the same Linux environment,
Python 3.12 and pinned dependencies, using Qt offscreen/Fusion at 1450 × 920.
Scientific imports and OS caches were warm. Each value is the median of three
workflow repetitions and includes queued Qt painting. Data had 250,000 sensor
samples per recording and 30,000 rows per output table. These are **not native
Windows timings**.

| Workflow (total duration of the stated actions) | Before | After |
| --- | ---: | ---: |
| Input inspection UI, 250,000 samples | 0.095 s | 0.045 s |
| Analyze options, 10 iterations | 0.011 s | 0.006 s |
| Navigation, 12 switches | 0.068 s | 0.063 s |
| Recording selection, 12 switches / 3 recordings | 0.469 s | 0.398 s |
| Data channels, 4 changes | 0.267 s | 0.257 s |
| Results load, 2 × 30,000 rows | 0.366 s | 0.250 s |
| Show Graphs | 0.331 s | 0.316 s |
| Select 3 plot series | 2.862 s | 1.832 s |
| Select 10 result rows | 5.032 s | 0.227 s |
| 10 graph clicks | 5.033 s | 0.238 s |
| Toggle timing columns 4 times | 2.131 s | 0.159 s |
| Switch active table 10 times | 5.040 s | 0.166 s |
| Export 2 tables to JSON | 0.741 s | 0.247 s |
| Export 2 tables to CSV ZIP | 0.145 s | 0.144 s |
| Read 200 saved run records | 0.005 s | 0.004 s |
| Refresh 200-run table | 0.026 s | 0.024 s |
| Select 10 runs | 0.057 s | 0.050 s |

Row selection and graph clicks improved by about 95%, active-table switching by
97%, timing toggles by 93%, and JSON writing by 67%. Unchanged CSV/history
operations and small navigation differences indicate normal measurement variation
as well as shared table-painting improvements; they are not separate algorithm
optimizations. Full-range initial rendering remains more expensive than selection.
[Raw samples and environment details](performance-review-0.5.4.json) are retained
for reproducibility.

Version 0.5.4 passed **276 source tests**, including all **31 scientific-equivalence
cases**; one Windows-only Authenticode check was skipped on Linux. The rebuilt
portable app passed its runtime smoke checks. Five fresh-process startup checks
reported a median first paint of 0.975 s and launch-to-report of 1.186 s, with
scientific imports still deferred. The Linux bundle is 539.4 MiB in regular files;
startup and size remain broadly consistent with the previous optimized build.
Windows CI supplies the native platform validation and measurements.

## Availability graph view stability (0.5.5)

Toggling input availability previously rebuilt the shared time axis and reset the
viewport, making unchanged outcomes look different. Coverage toggles now preserve
the time range, zoom and manual Y limits of existing plots; automatic Y ranges
are fitted after the shared time range settles. Home still exposes the full range.
Regression checks confirm identical outcome values and bar timestamps across
repeated toggles, with both absolute and elapsed time. The source suite passed
282 tests, including 31 scientific-equivalence cases; one Windows-only check was
skipped locally.

## Plot-series selection (0.5.15)

Adding a result series previously rebuilt every selected axis and its full set
of data rectangles. Existing plots now retain their axes, original paths and
settings when another series is added. Module order and the shared time axis
remain consistent; current zoom is retained and Home still exposes the full
extent. New results, a changed time view or removal of the shared master rebuild
the plots as needed. Collection bounds are calculated from the source arrays,
avoiding Matplotlib's duplicate scan of every rectangle.

Opaque presence tracks draw touching/overlapping positive intervals as their
exact union. This improves long resting/gait tracks without filling missing or
negative intervals. Every original interval remains available for inspection.
Regression checks compare the union rendering with the original rendering pixel
for pixel, retain the complete path arrays, and verify raster/vector exports.
Continuous bars retain every original value and interval; no downsampling was
introduced. Very large full-range plots still require rendering those bars.

The same workflow benchmark compares 0.5.14 (`f50bed4`) with 0.5.15 on Linux,
Qt offscreen/Fusion at 1450 × 920, pinned dependencies and warm caches. Each
value is the median of three repetitions including queued Qt painting, with
30,000 rows per output table. Baseline and updated runs were sequential, without
concurrent tests/builds. These are **not native Windows timings**.

| Workflow | 0.5.14 | 0.5.15 | Less time |
| --- | ---: | ---: | ---: |
| Add 3 series, Detailed | 2.055 s | 1.220 s | 41% |
| Add 3 series, 30-minute epochs | 0.673 s | 0.587 s | 13% |

[Raw samples and environment details](performance-review-0.5.15.json) include the
other workflows; small changes there reflect ordinary measurement variation.
The Windows build workflow records both graph-view measurements as well.

Analysis actions now share a stable-height footer with status text. Help changes
reserve the parameter card's real minimum and update explanations in one paint
batch, preserving spacing and avoiding transient clipping of lower fields.
The 90-second presence rule affects the half-hour metric graphs only; official
pipeline calculations, raw tables, aggregate outputs and data exports retain
their original values.

The updated source suite passed **359 tests**, including the official-toolbox
scientific-equivalence checks; one Windows-only signature check was skipped
locally. The rebuilt portable app passed its runtime smoke checks with the
bundled CWA, Empatica and Physilog examples. Native Windows validation remains
part of the GitHub Actions build.

## Analysis help spacing (0.5.17)

Windows CI exposed compressed spacing and overlap below the parameter card
when Device axes help opened in a 960 × 650 window. Version 0.5.16 synchronized
growing forms' layout rectangles, but the outer stack's `AlignTop` still capped
the usable rectangle at its preferred height instead of its wrapped height.
Version 0.5.17 removes that redundant alignment: the stack already reserves its
exact required height. Smaller windows scroll while preserving the 16-pixel gap
and the positions of labels and controls.

The help tests require the full configured gap as well as stable field
positions. Additional larger-font cases reproduce the compressed gap locally
on 0.5.16 and pass with this correction; the original Windows control-size
cases remain in the suite. Scientific processing and graph calculations are
unaffected. Native Windows validation runs in GitHub Actions.

Local validation: **362 tests passed**, with one Windows-only signature check
skipped. The rebuilt app passed its packaged runtime checks on Linux.

## Parameter columns at larger font sizes (0.5.18)

Windows passed the original spacing cases in 0.5.17, but the larger-font test
exposed horizontal clipping: the combined minimum widths of both parameter
columns exceeded the viewport. The columns now stack vertically when their
minimum widths cannot fit side by side, retaining the same spacing and allowing
vertical scrolling. Wider windows keep the two-column layout. Help stays below
the parameter card and does not affect the arrangement.

A regression reproduces the reported 404-pixel editor width locally and checks
all ancestor bounds and full editor visibility through narrow → wide → narrow
resizing. Existing native-control, font-size and stable-help checks remain
enabled. Analysis settings and scientific calculations are unchanged.

Local validation: **363 tests passed**, with one Windows-only signature check
skipped. The rebuilt app passed its packaged runtime checks on Linux; native
Windows confirmation remains part of the GitHub Actions build.

## Time-origin width constraints (0.5.19)

Windows CI still found horizontal clipping after the columns stacked in 0.5.18.
The time-origin row could force the entire form wider: its editor stack reserved
space for a hidden numeric control, and its label could not wrap above the field.
The origin field now reserves space for its calendar only, while retaining the
numeric control internally for existing value handling. A wider calendar wraps
below the label, with the same spacing as other parameter rows.

New regressions reproduce the overflow on 0.5.18 using a 620-pixel numeric hint
and calendars of 382 and 620 pixels. They check viewport width, complete control
visibility through resizing, and stable positions when help opens. Source-clock
precision, timezone handling, analysis settings and scientific calculations are
unchanged.

Local validation: **365 tests passed**, with one Windows-only signature check
skipped. The rebuilt app passed its packaged runtime checks on Linux. Native
Windows validation remains part of the GitHub Actions build.

## Wide-calendar action row (0.5.20)

Windows passed the original layout cases in 0.5.19. The remaining stress case
used a 620-pixel calendar: together with the Default button's native hint, the
compound field still exceeded the available width. The calendar and button now
use the same wrapping layout as the parameter columns. The editor fills the
available space on wider rows; on narrow rows, Default moves below it and stays
right aligned. The row reserves its full wrapped height and preserves spacing.

The regression now varies the action-button width independently of the calendar
width. The larger-button case fails on 0.5.19 and passes with this correction,
checking complete visibility, resizing and stable help positions. Calendar
precision, default-reset behavior and scientific processing are unchanged.

Local validation: **367 tests passed**, with one Windows-only signature check
skipped. The rebuilt app passed its packaged runtime checks on Linux. Native
Windows confirmation remains part of the GitHub Actions build.

## Help geometry before the first paint (0.5.21)

The remaining Windows failure caught a transient overlap during painting,
although the settled layout and width checks passed. Activating the layout
still used the help wrapper's old fixed height; a queued layout event corrected
that height later. Painting could resume before this correction. Inspecting
geometry immediately before painting resumed reproduced the overlap locally
with both Fusion and Windows Qt styles, even with ordinary control sizes.

Help changes now fit the wrapper to its new wrapped height synchronously, then
activate its layout and the surrounding body before re-enabling painting.
The parameter positions and the configured 16-pixel gap are preserved.

Eight new cases check this exact transition without waiting for queued events,
then force an immediate paint. They cover two window sizes, both Qt styles,
ordinary and enlarged controls, and both paced and rapid help changes. All
eight fail on 0.5.20 and pass with the correction. Existing layout, visibility
and paint-event assertions remain enabled. Scientific processing is unchanged.

Local validation: **375 tests passed**, including all 31 scientific-equivalence
tests, with one Windows-only signature check skipped. The rebuilt app passed
its packaged runtime checks on Linux. Native Windows confirmation remains part
of the GitHub Actions build.

## Fitted multi-channel sensor context (0.5.22)

Sensor context now shares the Data page's channel checklist and raw-signal
renderer. It overlays selected continuous channels in distinct, stable colors,
retains binary tracks and time alignment, and preserves selections between
drill-downs. Select all and Clear update the graph once per action.

The canvas and its tabs use the available height rather than a preferred fixed
height. The one-word channel heading does not request wrapping: an unnecessary
height-for-width hint otherwise made Qt reserve the list's preferred height and
scroll the page. The context information sits above the Graphs/Tables tabs,
leaving the graph visible in the same arrangement as Data.

New checks cover original values, channel colors and selection, mapped time
columns, calendar alignment, and full figure visibility without page scrolling
at 960 × 650 and 1450 × 920 with ordinary and enlarged fonts. Local validation:
**382 tests passed**, including all scientific-equivalence tests; one Windows-only
signature check was skipped. The rebuilt app passed its packaged runtime checks
on Linux. Native Windows validation runs in GitHub Actions.
