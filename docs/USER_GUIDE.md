# Using ParaDigMa Studio

See the [README](../README.md) for downloading the Windows app and the basic workflow.
The sidebar has Data, Analyze, Results and Runs pages and expands on hover.

**About** at the bottom of the sidebar (or **F1**) has **Overview**, **Citations**
and **Licences** tabs. **Copy BibTeX**, in Citations, copies the 2026 JOSS paper
reference; pipeline methods and validation publications are listed below it.
Licences shows the complete Studio and ParaDigMa licences under separate headings.

## Input and analysis settings

The app uses the official ParaDigMa loaders and processing functions, with an
Empatica IMU import adapter and TSDF metadata scaling. TSDF's per-channel
`scale_factors` are applied once on loading, for both display and analysis;
absent or empty factors leave stored values unchanged. Analyze units describe
these scaled physical values. ParaDigMa's preparation then performs unit conversion.
**Open sensor files** accepts one or more recordings
for the same subject. For several files, the Data recording selector inspects
one original file at a time; Analyze reports the complete selection and sample
count. One set of units, mappings, watch side and preparation settings applies
to every file, so select files with compatible sensor conventions.

Data's time-column format controls both its time statistics and graphs.
With `difference_s` or `difference_ms`, graphs reconstruct cumulative elapsed
seconds from the complete increment column before display sampling. Tables retain
the original increments. Missing increments use sample positions rather than
inventing elapsed times. Changing Data's selection does not change Analyze settings.

Each recording is validated and prepared separately. Feature windows and
filtering never cross file boundaries. Multiple recordings can run in up to two
workers when CPU and available RAM permit; a single recording always uses one
worker, including its gap sections. The processing log reports the selected worker
count and any fallback reason. Resource decisions show detected CPU count, free
RAM after loading, largest recording size and estimated RAM per worker; installed
RAM alone does not determine the worker count. Stop terminates every owned worker
and removes temporary processing files. Classification and quantification tables
are combined in input order with unique gait segments across files;
aggregates are computed from the combined quantifications using ParaDigMa's own
aggregation functions. They are not averages of per-file aggregate percentages.
Detailed tables and CSV exports retain `file_key`; Runs and JSON exports retain
the mapping from file identifiers to original paths. Exports protect every
selected source file from overwriting. A load/preparation failure names the
affected recording; processing errors retain available partial pipeline outputs.

Choose any combination of gait, tremor and pulse rate in **Analysis modules**.
Set processing options in **Analysis parameters**. Each field's **i** button opens
guidance below the parameters with a reference to the official ParaDigMa documentation.
Only one explanation is shown at a time; opening another replaces it without
moving the fields.
Signal columns includes ParaDigMa's original reference figure and a direct link to its
Coordinate System guide. The example explains source-axis selection and inversion.
Signal columns appear on the left and parameter settings on the right; narrow
windows stack the two sections.
Analyze prefills time and sensor units when supported metadata agrees across
all applicable recordings. TSDF supplies per-channel units after physical scaling;
Axivity CWA and Empatica imports supply their decoded output conventions (`g`,
`deg/s` where gyroscope is present, and `relative_s`). Plain CSV, Parquet and
pickle tables do not establish units merely through their format or values.
Only supported, explicit time representations are accepted: a declaration of
seconds alone does not distinguish relative, absolute or difference-based time.

A small **From file** label beneath the parameter name identifies detected units
and automatic time origins.
In Signal columns, each automatically matched signal has its own label.
Hover over it, or open the field's existing **i** explanation, to see the source.
Defaults remain unmarked. Editing a value removes its label and keeps the manual
choice for the current loaded recording or batch. The field's **Default** button
restores the detected value; one **Default** button restores the whole Signal columns table.
Time origin's **Default** button restores its automatic value. For absolute time,
that value comes from the selected **Time** column. For relative or difference
time, it comes from recording-start metadata when available (including TSDF,
Axivity CWA and Empatica imports). Other date columns, including `time_dt`,
`datetime` and `timestamp`, do not supply an origin. Without an available origin,
the field stays empty and results use elapsed time.
**Use parameters** keeps restored units explicit, including
values equal to the current defaults. Unit detection follows the selected source
columns. A single message summarizes conflicting or incomplete unit declarations
across recordings, without listing filenames; normalize differing inputs or
analyze them separately. Watch side, axis directions, Already prepared and gap
and missing-sample policies remain user choices.
Successfully loading a new recording or batch resets Analyze to its initial
settings, including the default Gait module, automatic column matching,
axis directions, preparation options, thresholds and automatic time origin.
The new input's supported metadata then fills the relevant fields. Help and
mapping details collapse. Switching the inspected recording within an already
loaded batch preserves the shared settings. Cancelling a file selection or a
failed load preserves the current input and settings.
The page preserves comfortable spacing. Parameters fit together at normal window
sizes; smaller windows and expanded guidance can scroll. **Run Analysis** stays
visible below the settings.

When pulse rate is selected alongside gait or tremor, the desktop runs the
official orchestrator twice in the background and combines their returned outputs.
The workflows retain independent sensor requirements and missing-sample exclusions.
If one fails, the other workflow's successful outputs remain available, and failed workflows appear under **Errors** in Runs.

Pulse rate accepts `time` and `green` (raw PPG), with or without accelerometer
channels. Keep preparation enabled to convert raw timestamps. In ParaDigMa 1.1.2,
the high-level pulse-rate pipeline assesses quality using PPG features only;
its `pred_sqa_proba` does not include an accelerometer motion assessment.
Complete optional accelerometer channels retain their existing unit conversion
and missing-sample checks during preparation.

- Check acceleration units, gyroscope units and time representation against the
  recording. Acceleration is displayed as **g** or **m/s²**. Numeric time supports
  relative, absolute or difference-based values
  in seconds or milliseconds. CSV date strings need conversion to a supported
  numeric representation before analysis.
- Set the actual wrist as watch side.
  Watch-side inversion happens separately in official pipeline preprocessing.
- Scrolling over dropdowns, numeric fields or date/time fields moves their
  surrounding page without changing their values, including when a field has
  focus. This applies throughout the app. Use typing, keyboard arrows or the
  field's buttons to edit a value. An opened dropdown list can still scroll.
- In **Signal columns**, choose a source column from the dropdown for each
  required signal. Columns already named `time`, `green`, `accelerometer_x`, etc.
  are recognized automatically and shown by their actual names. The dropdown
  selections determine the signal inputs used in processing. Selecting a different
  source replaces the standard-name source; an unselected standard-name column
  does not fill a missing selection. Select **Not included** to leave any signal
  unassigned, even if its standard-name column exists. This choice persists within
  the current loaded recording or batch until you select a source or use **Default**.
  Loading new files starts a fresh mapping. Missing signals required
  by a selected module still show a warning. Automatic matching on load uses names shared
  by every loaded recording. Exact ParaDigMa names take precedence, followed by
  unambiguous familiar names such as `timestamp`, `gyr_x` and `ppg`.
  The table's single **Default** button restores these matches for all signals, including
  optional ones. It replaces manual selections and clears assignments without a confident match;
  ambiguous names need a manual selection afterwards. Axis inversions are kept.
  A **From file** label appears beneath each automatically matched signal name.
  Manually selected values are not marked as file-derived.
  **Show optional signals** exposes other channels;
  **Show details** also explains whether column assignments came from exact names,
  recognized aliases, manual selections or explicit saved mappings.
  Selecting another module preserves all choices.
  For axis swaps, choose the source column that should become each toolbox axis.
  For example, select the device's Y column for **Accelerometer X** and its X column
  for **Accelerometer Y**. Tick **Invert axis** to reverse the selected signal's
  direction (multiply by −1). Accelerometer and gyroscope directions can be set
  independently. There is no separate Device axes field.
  One mapping and set of inversions applies to every loaded recording.
  The compatibility summary covers every loaded recording. **Show details**
  groups missing signals and conflicting names into messages shared across the
  recordings, without listing filenames. Counts identify issues affecting only
  some recordings. Warning icons beside affected dropdowns explain reused source
  columns and how many recordings are missing a selected column.
  Click a warning icon to read its full message, or focus it and press Space.
  Valid rows need no status indicator. Existing per-recording and
  per-module analysis validation still determines which workflows can run.
  Source-column options list only columns present
  in the loaded recordings; a missing saved choice shows the selection prompt and its warning
  names the missing column so it can be corrected. **Use parameters** restores
  saved mappings, including additional legacy mappings shown in Details.
  Older saved global axis permutations are
  translated into equivalent column choices and inversions. Saved runs and exports
  retain the source-to-toolbox mapping dictionary and record inverted target channels
  separately; no JSON editing is needed in the app.
- Keep preparation enabled for raw data. Use **Already prepared** only for data
  already converted to ParaDigMa's units, orientation and sampling requirements.
  Mapping still applies in prepared mode. Inversion controls are disabled and
  inversions are skipped; unchecking Already prepared restores your selections.
- **Exclude missing sensor samples** removes rows with non-finite required sensor
  values from analysis. Counts are logged and recorded in exported metadata.
  It defaults to on; uncheck it for strict rejection. Non-finite relative or
  absolute timestamps can also be excluded. Missing time differences cannot be
  excluded, and retained timestamps must still be strictly increasing.
- **Split recordings at time gaps** runs continuous sections independently. The
  switch defaults to on. Maximum gap and minimum section duration both default
  to 1.5 seconds, matching ParaDigMa's preparation defaults.
  Each **Default** button restores its field even when splitting or conversion
  is disabled. Maximum gap is an interval between samples, not a feature window.
  Outputs identify multiple sections using `file_key`.

The source recording remains unchanged. Difference-based time preserves elapsed
time before missing sensor rows are excluded. The Python `analyze` API requires
explicit `drop_missing_samples=True` to enable exclusion.

The wrapper calls official preparation and orientation functions before
`run_paradigma` with prepared data. This applies the selected units and axes
consistently and avoids interpolation across separate recordings. It also supplies
gap settings required by ParaDigMa 1.1.2. Scientific configuration and algorithms
remain those of the official package. See [scientific tests](SCIENTIFIC_TESTS.md).

## Inspecting data and results

### Data

Data **Overview** separates sensor and time statistics:

- Sensor range is minimum–maximum; median and IQR (75th minus 25th percentile)
  use finite values. Missing and infinite values are counted separately.
- Estimated sampling rate is the inverse median positive time interval. Gaps
  are intervals longer than 1.5 times that median. Invalid timestamps are not
  bridged. Zero-length and backward intervals are reported separately.
- The numeric time format on Data applies to all loaded recordings and affects
  inspection only. Switching recordings keeps the selected format for statistics
  and graphs. Set analysis units separately on Analyze. Native datetime values
  carry their own time representation.

Data **Graphs** overlays checked channels of the same modality with stable colors
and a legend. Each modality has its own value axis and shares the time axis.
Values retain their file units. Data **Tables** shows original samples.
Zoom in to inspect individual samples at their original timestamps. Wide views
retain signal peaks; zooming restores the full detail in the visible time range.

### Results overview

Results **Overview** shows official aggregates and relevant pipeline metadata in
module cards. Recording summaries show the timespan, data coverage in days and
hours plus its percentage of the timespan, and gaps, without duplicating
identical workflows. Gait has **Quantity**, **Range of motion** and **Peak velocity**
charts, grouped by filtered/unfiltered gait and then duration category. Quantity
shows duration in minutes and integer segment counts; the count bins use original
unfiltered segment durations, with 20 seconds in the ≥20-second bin. Other bar
labels use one decimal, except CV ratios, which use two. Individual segment records
remain in the metadata export; display rounding does not change official values.

Pulse rate places its individual measures directly beneath the module heading,
without Aggregates/Metadata subheadings. **Pulse-rate estimate availability (%)**
replaces the raw `nr_pr_est` count in Overview. It is the number of returned
estimates divided by the number of complete 2-second epochs in the full
**Recording timespan**, multiplied by 100. The timespan includes gaps and
excluded edges, including between-file gaps; no quality or pipeline-boundary
deductions are made. A final partial epoch is not counted. Hover over the value
for both counts. This measures estimate availability, not the proportion of
high-quality PPG samples. Unknown timing/counts or a timespan under two seconds
show an unavailable value. The original metadata count remains in saved results
and exports, and the overview percentage survives reopening without sensor files.

### Results graphs

Results **Graphs** compares classifications and quantifications across modules.
Check metrics in **Plot series**. Aligned plots share one time axis, with time and
date on separate lines. Compact plot rows fit more graphs on screen. The axis
stays visible while scrolling through graphs and follows the visible time range.
Dates use the selected absolute Time column or declared recording-start metadata.
**Time origin**
in Analyze provides a calendar and clock for overriding analysis time zero;
**Default** restores the derived value. Uncheck it to show elapsed seconds.
This setting affects presentation only and is saved with run parameters. Known
timezones, clock precision and daylight-saving offsets are retained.
Pulse-rate series use **Pulse rate** and **High-quality PPG (probability)**;
original column names remain unchanged in tables and exports.
In Detailed view, pulse-rate estimates occupy 2-second intervals, while PPG
quality probabilities occupy 1-second intervals. Missing outputs remain blank.

Multiple recordings use actual clock offsets when all clocks are comparable.
Otherwise plots use a labeled **File-order timeline**, without inventing dates or
between-file gaps. Scientific timestamps remain unchanged. ParaDigMa's internal
`nr_valid_days` uses its own quantification timestamps, independently of the display clock.

Continuous outputs use individual bars at the output update cadence, with gaps for
missing or non-finite measurements. Actual zero values remain visible at the baseline.
No interpolation connects values across missing outputs or recording sections.
When many bars fit inside one screen pixel, the plot combines their extents to
keep peaks and density visible both while scrolling and at rest. Zoom in to
resolve individual bars. Original tables and exports retain all values and intervals.
Gait arm-swing positions are evenly spaced bin midpoints within the official segment
start/end, with bars confined to those bins. Timing details and sensor context identify them as **Estimated**;
unknown segment boundaries leave timing unavailable. Values and aggregates stay exact.

Binary predictors show slim filled spans only when present. Spans run to the next
output update, capped at the module's cadence (4 seconds for default tremor), rather
than the full overlapping feature-window length. Zero and missing states remain blank;
all output rows remain in tables. The overview retains the official tremor aggregates;
graphs omit statistics text. `perc_windows_tremor` uses the resting-window denominator.
The tremor overview shows percentage tremor during rest, official power measures
and percentage arm at rest with two decimal places, without subcategory labels.
Arm-at-rest percentage uses resting windows divided by all quantified windows.
Original tables, metadata and exports keep their full precision.
Tremor's arm-rest and checked-tremor predictors each appear once in Plot series;
the original tables retain the duplicate output columns.

**Data coverage** tracks show coverage of the actual prepared samples handed to
the pipelines, reflecting excluded rows and discarded sections. Identical workflows
share a track; differing IMU and PPG coverage is shown separately. A sample is displayed
for one nominal sample interval; gaps exceeding 1.5 times the median positive interval
stay blank. An isolated sample with unknown cadence appears as a tick. These tracks
are display metadata, not classifications or inferred physiological states.

Gait Classification offers **Gait presence (prediction)** and **Filtered gait presence
(prediction)** alongside probabilities, using the bundled models' `probability ≥ threshold`.
Filtered-positive intervals are restricted to detected gait. These describe individual
windows; ParaDigMa's final sample segmentation additionally averages overlapping
probabilities. Raw tables retain the official probability columns.

#### Graph views

Graph summaries affect presentation only; tables, data exports and official
aggregates retain their original values.

**View**, at the right of the figure toolbar, switches all graphs between Detailed,
30-minute epochs, Day and 24-hour profile. Continuous epoch values show the median; binary predictions show
percentages. Tremor-power graphs use `log10(power + 1)`, matching ParaDigMa's
aggregate transformation; epoch medians are calculated after this transformation.
The y-axis labels identify the log scale. Tables and data exports retain raw power.
Bar graphs use automatic y-axis limits based on the visible values, including
prediction and data-coverage percentages; they are not fixed to 0–100%.
Manual Y limits stay fixed while scrolling or zooming, until Automatic or Reset
limits is selected.
Detailed and 30-minute views share a time-axis layout: thin vertical separators
mark midnight continuously across the graphs and their gaps, with clock times
above dates. Dates stay centered beneath their days. The first date aligns left
if it no longer fits centered, then disappears if there is too little space; later
dates keep their regular positions. The recording's timezone is retained (or left
unspecified when the original data has none). Labels adapt to width and zoom,
keeping midnight times visible across multiple days and spacing them out on longer ranges. Zooming
in reveals hours, minutes, seconds and fractions of a second as needed. Without a
calendar clock, elapsed Day 1, Day 2 and clock-style times are shown instead.
Saved figures retain both rows.
Epochs align to calendar half-hours when a recording clock is known,
or elapsed half-hours otherwise. Gait range of motion and peak velocity require
at least 90 seconds of the corresponding filtered or unfiltered gait presence
per epoch; tremor power requires at least 90 seconds of checked tremor presence.
Overlapping presence intervals count once. The same threshold applies to partial
epochs, and unknown presence leaves the median blank. For older saved results
without gait classifications, known gait-segment boundaries provide the fallback.
Data coverage instead shows covered time as a percentage of the recording span
within each epoch, including partial edge epochs.

**Day** groups outputs by calendar day, from midnight to midnight in the recording's
display timezone, including daylight-saving changes. Without an absolute clock,
it uses elapsed 24-hour blocks from the recording's time origin. The shared axis
centers a date beneath each day, with the year on a second line. Dates appear for
every day when they fit; a longer range or narrower window spaces them out, and
zooming in restores the individual dates. Without an absolute clock, the labels
use Day 1, Day 2, and so on. Figure exports retain these labels. Each metric needs
at least **864 seconds (14 minutes 24 seconds)** of valid data in a day—1% of a
24-hour period. This fixed minimum also applies to partial and daylight-saving days.
Both zero and one predictions count as available binary data; missing or non-finite
outcomes do not count. Overlapping intervals count once, and recording gaps are
preserved. Gait metrics use their estimated within-segment intervals; missing swing
values contribute no coverage. Gait and filtered gait percentages share observed
time. Data coverage shows prepared time as a percentage of the full calendar day.
This daily availability rule is separate from the 30-minute presence rule above.

**24-hour profile** combines matching half-hour slots across all available days
into 48 bars from 00:00 to 24:00. Each bar is the arithmetic mean of the valid
30-minute summaries: percentages for indicators and coverage, and epoch medians
for continuous outcomes. Tremor power retains the log transformation. The existing
90-second presence rules apply to each day's epoch before averaging; the Day
view's 1% threshold does not apply. Each day contributes equally, regardless of
sample count. Missing or insufficient epochs are excluded, while valid zeros
remain included. A slot with no qualifying days stays blank.

Slots use the recording's original timezone, with no assumed timezone when it is
unspecified. A repeated half-hour during a daylight-saving fallback contributes
its mean once for that day; skipped spring-forward slots are missing. Without a
recording clock, slots use elapsed 24-hour periods starting at analysis zero.
Clicking a bar selects its half-hour slot and displays the contributing-day count;
it does not select one dated sample. Use Tables or another graph view for sensor
context. Profile X limits accept HH:MM or seconds since midnight; Reset limits and
Home restore the full 24-hour range.

Plots are grouped by module, following Plot series order, and long
series names wrap in full. The default selection is gait presence (prediction),
filtered gait range of motion and tremor presence (prediction), when available.
Gait and filtered gait share one observed-time denominator, so filtered
gait cannot have a higher percentage. Gait-positive time without filtering results
is excluded from both denominators. Other binary outcomes use finite observations.
Missing outputs stay blank. Click module titles to expand or collapse Plot series;
tremor offers checked presence, arm-at-rest predictions and tremor power.

### Results tables

Results **Tables** uses module-colored Gait, Tremor and Pulse rate tabs. Select the
classification, quantification or aggregation table using **Output table**. Original
columns and values are the default. **Timing details** adds display-only clock and
gait annotations. Aggregation dictionaries are ordered measure/value tables.
Zooming never filters table rows or recalculates aggregates.

### Sensor context

**Inspect sensor context**, alongside the recording-time label at the bottom right of Graphs, links a selected row or
clicked bar to original samples. A vertical marker and the pinned axis identify the
selected time. Inspection uses the original samples within 10 seconds before and
after the selected time, bounded by the available recording. Gait measurements
open the complete official segment rather than
treating their estimated positions as observed event timestamps. Sensor context
requires the original recording to remain available in the session.
The context's **Graphs** tab uses the same left-hand channel checkboxes as Data:
select multiple channels to overlay their original values with distinct colors.
Channels of the same modality share a graph; selecting another modality adds a
separate graph with its own value axis and a shared recording-time axis. This
also applies on Data. Known sensor names and configured column mappings identify
modalities; unidentified scalar streams stay separate. Use **Select all** and
**Clear**. The complete figure resizes to fit the page;
the channel list and **Tables** can scroll independently. Channel selections are
retained when inspecting another result. Drag with **Pan** to move through the
original recording beyond the initial context, up to its boundaries. Sensor-context
axes use the accelerometer and gyroscope units stored in that run's Analyze settings.
New samples load as you move; gaps stay blank. **Close**, alongside the recording summary
at the top right, dismisses the sensor-context tab.
Adding or removing channels keeps the current time window. **Home** returns to
the original ±10-second context or complete gait segment, including after
channel changes; Back can return to the view before Home.
The selected result time is marked whenever it is in view.
Clicking either a checkbox or its label toggles a channel or plot series.

### Graph controls

Results graphs have **Select timepoint** (default), **Select time interval**, **Zoom in** and
**Zoom out**. Click a plotted timepoint to mark it; its date and time appear above
the time axis. Select time interval uses a shaded-band icon: drag within a graph
or in the gaps between graphs to zoom into the same time interval across all
linked graphs without selecting a Y range.
New results and switching between graph views start at the full time range with
the horizontal scrollbar hidden. Adding or removing graphs keeps the current zoom.
Results graphs use a fixed Y-axis column, so graph selections do not shift them sideways.
After zooming in, the horizontal scrollbar below the time axis moves through the
full time range while keeping the window duration. Its handle indicates how much
time is visible; it disappears when the full range is shown. Two-finger horizontal
trackpad gestures also scroll time over the graphs and time axis. Vertical gestures
still scroll through the graph list. Zoom never extends beyond the full X range.
Dense graphs preserve peaks, gaps and visual density at the display's pixel
resolution, both while scrolling and after release. Zooming resolves individual
bars; tables and exports retain every original value and interval.
The drag shades the selected interval continuously across all graphs and their
gaps. **Zoom in** and **Zoom out** buttons change the visible duration by a factor
of two. Home, Back and Forward include these navigation changes. Choose Select
timepoint to resume selection.
Data and sensor-context graphs retain Pan (default) and zooming in both axes.
Sensor context retains the time selected in Results.

**Axis limits** opens the only graph settings panel. Click the graph you want
to adjust, uncheck **Automatic** for X or Y, enter the minimum and maximum,
and press Enter or leave the field to update the graph. Calendar limits accept
ISO date/time with a time zone.
X limits apply to linked plots; Y limits apply to the clicked plot.
The fields follow navigation and zoom changes and show at most three decimal
places; unedited limits retain their full precision.
The selected graph is shaded while editing. **Reset limits** restores automatic
ranges. In sensor context it returns to the original context window, like Home.
**Close** dismisses the panel. Home, Back, Forward and figure
saving remain on the toolbar. Images are saved at **600 DPI**; saved results
figures include the time axis.
Raw sensor plots retain continuous signal lines and limit display to 20,000 samples
per channel; result bars and binary indicators retain every output.

## Exports and run history

### Exports

**Export…** appears on every Results tab. Choose a format and check which original
tables or metadata groups to include:

- **JSON:** one structured file containing selected outputs and analysis provenance.
  Non-finite values become null. Full JSON exports can reopen after restarting without
  loading the sensor recording. Select all outputs/metadata to preserve all drill-down
  timing information.
- **CSV:** one table exports as CSV. Multiple tables or metadata selections export as
  a ZIP containing separate CSV files, selected metadata JSON and analysis provenance.
  Scientific tables retain their original columns; formula-like text is neutralized.

### Saved runs

**Save results** stores all outputs, metadata and analysis provenance in
`%LOCALAPPDATA%\ParaDigMaStudio\runs\results` on new Windows installations. Use
**Open results** in Runs to restore them after restarting. Saving runs in the
background; original recordings are not copied. The button appears on every Results tab.
Opening also runs in the background and returns to Overview. Graphs are prepared
when you open the Graphs tab.

**Runs** stores status, parameters, separate warnings and errors, logs and saved
result/export locations in `%LOCALAPPDATA%\ParaDigMaStudio\runs` on new Windows installations.
The **Recordings** tab lists the selected run's input filenames and paths.
Detail tabs are ordered Recordings, Parameters, Warnings, Errors,
Processing log, Saved run and Exports.
**Saved** reports whether a local result snapshot is available; **Exports** counts
separate user exports. Their locations appear in the **Saved run** and **Exports** tabs.
Closing with unsaved results offers **Save**, **Discard** or **Cancel**. Save
stores all unsaved runs before closing. Exporting, including complete JSON,
does not mark a run as saved locally or clear that warning. Complete JSON
exports can reopen through **Open exported results**; local saves take precedence.

Saved snapshots and JSON exports identify their owning run. Runs also records a
SHA-256 checksum of each file. Opening requires both the run ID and checksum to
match, so replacing or editing a result file prevents reopening it under the
original run. A failed open leaves the displayed results intact. Files without
this verification information, including older exports, cannot reopen through Runs.

Existing installations continue using their earlier `ParaDigMaDesktop` history
folder when a Studio history folder does not yet exist. Saved result files stay
at their original paths and follow the same verification requirements.

**Stop Analysis** remains available below Analyze settings while a run is active.
Cancellation stops the owned analysis process, removes its temporary files and records
**Cancelled** in Runs without treating cancellation as an analysis error.

Select one or more runs using Ctrl/Shift and choose **Delete Run(s)…**, or press
**Delete** while the run list has focus. **Clear all…** deletes all runs after confirmation.
A confirmation lists the associated saved results and exports to be
permanently removed with the history entry. Original sensor files, TSDF companions
and exports referenced by another run are protected. Running jobs cannot be deleted.
Reused parameters apply to the currently selected input; check it before running.

Shortcuts: **Ctrl+O** opens recordings, **Ctrl+S** saves results, **Ctrl+Enter** runs analysis, **Alt+1–4** switches
pages, **Delete** deletes selected runs after confirmation, and **F1** opens About.

## Common issues

**Incomplete extracted download:** Keep the entire app folder, including `_internal`.
For an update, extract the latest successful Windows artifact into a fresh folder.

**Windows blocks an unverified publisher:** The normal build is unsigned. See
[signing](../SIGNING.md) for the account and verification requirements and
[security](../SECURITY.md) for isolated testing. Keep Windows security protections enabled.

**Empatica gyroscope unavailable:** The bundled example contains accelerometer
samples but no gyroscope samples. Import support allows inspection; it cannot
supply absent channels required for gait/tremor. The IMU adapter supports one Avro
record with optional aligned gyroscope data, not BVP, EDA or temperature streams.
Multi-record or unaligned IMU streams need splitting or alignment before import.

**Physilog missing values:** The official example contains missing gyroscope
samples. Keep missing-sample exclusion and gap splitting enabled to analyze its
valid continuous sections. Exclusion counts are visible in the processing log
and `metadata.desktop_preparation`.

**Empty or partial results:** Empty quantified output is distinct from a failure.
Review warnings and errors in Runs. Some short recordings have too few detected
tremor windows for ParaDigMa's modal aggregation; available window outputs are
retained. Pulse rate accepts raw or prepared PPG-only input. The default PPG
quality classifier may reject a recording's windows, producing no estimates.

Device compatibility, sample rate, recording duration and scientific interpretation
follow the [official documentation](https://biomarkersparkinson.github.io/paradigma/).
