# Using ParaDigMa Studio

See the [README](../README.md) for downloading the Windows app and the basic workflow.

**About** at the bottom of the sidebar (or **F1**) has **Overview**, **Citations**
and **Licences** tabs. **Copy BibTeX**, in Citations, copies the 2026 JOSS paper
reference; pipeline methods and validation publications are listed below it.
Licences shows the complete Studio and ParaDigMa licences under separate headings.

## Input and analysis settings

The app uses the official ParaDigMa loaders and processing functions, with an
Empatica IMU import adapter. **Open sensor files** accepts one or more recordings
for the same subject. For several files, the Data recording selector inspects
one original file at a time; Analyze reports the complete selection and sample
count. One set of units, mappings, watch side and preparation settings applies
to every file, so select files with compatible sensor conventions.

Each recording is validated and prepared separately. Feature windows and
filtering never cross file boundaries. Classification and quantification tables
are combined; the official orchestrator assigns unique gait segments across files;
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
Device axes includes ParaDigMa's original reference figure and a direct link to its
Coordinate System guide. The example explains each signed mapping; column-mapping
examples rename your file's columns to the required toolbox names.
The page preserves comfortable spacing. Parameters fit together at normal window
sizes; smaller windows and expanded guidance can scroll. **Run Analysis** stays
visible below the settings.

When pulse rate is selected alongside gait or tremor, the desktop runs the
official orchestrator twice in the background and combines their returned outputs.
The workflows retain independent sensor requirements and missing-sample exclusions.
If one fails, the other workflow's successful outputs remain available, and failed workflows appear under **Errors** in Runs.

- Check acceleration units, gyroscope units and time representation against the
  recording. Numeric time supports relative, absolute or difference-based values
  in seconds or milliseconds. CSV date strings need conversion to a supported
  numeric representation before analysis.
- Set the actual wrist as watch side. Device axes are signed source axes in the
  order of toolbox X, Y, Z: `-y,x,z` gives X = −sensor Y, Y = sensor X, Z = sensor Z.
  Watch-side inversion happens separately in official pipeline preprocessing.
- Map alternate names to official channel names, for example
  `{"timestamp": "time", "gyr_x": "gyroscope_x", "ppg": "green"}`.
  Map every required channel.
- Keep preparation enabled for raw data. Use **Already prepared** only for data
  already converted to ParaDigMa's units, orientation and sampling requirements.
  Mapping still applies in prepared mode.
- **Exclude missing sensor samples** removes rows with non-finite required sensor
  values from analysis. Counts are logged and recorded in exported metadata.
  Uncheck it for strict rejection. Non-finite relative or absolute timestamps
  can also be excluded. Missing time differences cannot be excluded, and retained
  timestamps must still be strictly increasing.
- **Split recordings at time gaps** runs continuous sections independently. The
  switch defaults to off, matching ParaDigMa. Maximum gap and minimum section
  duration both default to 1.5 seconds, matching its preparation defaults.
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

Data **Overview** separates sensor and time statistics:

- Sensor range is minimum–maximum; median and IQR (75th minus 25th percentile)
  use finite values. Missing and infinite values are counted separately.
- Estimated sampling rate is the inverse median positive time interval. Gaps
  are intervals longer than 1.5 times that median. Invalid timestamps are not
  bridged. Zero-length and backward intervals are reported separately.
- Numeric time units on Data affect inspection only. Set analysis units separately
  on Analyze. Native datetime values carry their own time representation.

Data **Graphs** overlays checked channels of the same modality with stable colors
and a legend. Each modality has its own value axis and shares the time axis.
Values retain their file units. Data **Tables** shows original samples.

Results **Overview** shows official aggregates and relevant pipeline metadata in
module cards. Recording summaries show the timespan, data coverage in days and
hours plus its percentage of the timespan, and gaps, without duplicating
identical workflows. Gait has **Quantity**, **Range of motion** and **Peak velocity**
charts, grouped by filtered/unfiltered gait and then duration category. Quantity
shows duration in minutes and integer segment counts; the count bins use original
unfiltered segment durations, with 20 seconds in the ≥20-second bin. Other bar
labels use one decimal, except CV ratios, which use two. Individual segment records
remain in the metadata export; display rounding does not change official values.

Results **Graphs** compares classifications and quantifications across modules.
Check metrics in **Plot series**. Aligned plots share one time axis, with time and
date on separate lines. Compact plot rows fit more graphs on screen. The axis
stays visible while scrolling and follows pan
and zoom. Dates come from the original recording when available. **Time origin**
in Analyze provides a calendar and clock for overriding analysis time zero;
**Default** restores the derived value. Uncheck it to show elapsed seconds.
This setting affects presentation only and is saved with run parameters. Known
timezones, clock precision and daylight-saving offsets are retained.

Multiple recordings use actual clock offsets when all clocks are comparable.
Otherwise plots use a labeled **File-order timeline**, without inventing dates or
between-file gaps. Scientific timestamps remain unchanged. ParaDigMa's internal
`nr_valid_days` uses its own quantification timestamps, independently of the display clock.

Continuous outputs use individual bars at the output update cadence, with gaps for
missing or non-finite measurements. Actual zero values remain visible at the baseline.
No interpolation connects values across missing outputs or recording sections.
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

**View**, at the right of the figure toolbar, switches all graphs between Detailed
and 30-minute epochs. Continuous values show the median; binary predictions show
percentages. Tremor-power graphs use `log10(power + 1)`, matching ParaDigMa's
aggregate transformation; epoch medians are calculated after this transformation.
The y-axis labels identify the log scale. Tables and data exports retain raw power.
Epochs align to calendar half-hours when a recording clock is known,
or elapsed half-hours otherwise. Gait range of motion and peak velocity require
at least 90 seconds of the corresponding filtered or unfiltered gait presence
per epoch; tremor power requires at least 90 seconds of checked tremor presence.
Overlapping presence intervals count once. The same threshold applies to partial
epochs, and unknown presence leaves the median blank. For older saved results
without gait classifications, known gait-segment boundaries provide the fallback.
Data coverage instead shows covered time as a percentage of the recording span
within each epoch, including partial edge epochs. These summaries affect graphs
only; tables, exports and official aggregates remain unchanged.

Plots are grouped by module, following Plot series order, and long
series names wrap in full. The default selection is gait presence (prediction),
filtered gait range of motion and tremor presence (prediction), when available.
Gait and filtered gait share one observed-time denominator, so filtered
gait cannot have a higher percentage. Gait-positive time without filtering results
is excluded from both denominators. Other binary outcomes use finite observations.
Missing outputs stay blank. Click module titles to expand or collapse Plot series;
tremor offers checked presence, arm-at-rest predictions and tremor power.

Results **Tables** uses module-colored Gait, Tremor and Pulse rate tabs. Select the
classification, quantification or aggregation table using **Output table**. Original
columns and values are the default. **Timing details** adds display-only clock and
gait annotations. Aggregation dictionaries are ordered measure/value tables.
Zooming never filters table rows or recalculates aggregates.
Automatic vertical limits follow the visible result bars, including any extreme
values in that time interval. Manual limits remain fixed when panning or zooming.

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

Results graphs have three cursor modes: **Select timepoint** (default), **Pan** and
**Zoom**. Click a plotted timepoint to mark it; its date and time appear above
the time axis. Choose Pan to move the view or Zoom to draw a zoom rectangle,
and Select timepoint to resume selection. Data and sensor-context graphs have
Pan (default) and Zoom. Sensor context retains the time selected in Results.

**Axis limits** opens the only graph settings panel. Click the graph you want
to adjust, uncheck **Automatic** for X or Y, enter the minimum and maximum,
and press Enter or leave the field to update the graph. Calendar limits accept
ISO date/time with a time zone.
X limits apply to linked plots; Y limits apply to the clicked plot.
The selected graph is shaded while editing. **Reset limits** restores automatic
ranges. In sensor context it returns to the original context window, like Home.
**Close** dismisses the panel. Home, Back, Forward and figure
saving remain on the toolbar. Images are saved at **600 DPI**; saved results
figures include the time axis.
Raw sensor plots retain continuous signal lines and limit display to 20,000 samples
per channel; result bars and binary indicators retain every output.

## Exports and run history

**Export…** appears on every Results tab. Choose a format and check which original
tables or metadata groups to include:

- **JSON:** one structured file containing selected outputs and analysis provenance.
  Non-finite values become null. Full JSON exports can reopen after restarting without
  loading the sensor recording. Select all outputs/metadata to preserve all drill-down
  timing information.
- **CSV:** one table exports as CSV. Multiple tables or metadata selections export as
  a ZIP containing separate CSV files, selected metadata JSON and analysis provenance.
  Scientific tables retain their original columns; formula-like text is neutralized.
- **Save results:** stores all outputs, metadata and analysis provenance in
  `%LOCALAPPDATA%\ParaDigMaStudio\runs\results` on new Windows installations. Use **Open results** in
  Runs to restore them after restarting. Saving runs in the background; original
  recordings are not copied. The button appears on every Results tab.
- **Runs:** stores status, parameters, separate warnings and errors, logs and saved
  result/export locations in `%LOCALAPPDATA%\ParaDigMaStudio\runs` on new Windows installations.
  **Saved** reports whether a local result snapshot is available; **Exports** counts
  separate user exports. Their locations appear in the **Saved run** and **Exports** tabs.
  Closing with unsaved results offers **Save**, **Discard** or **Cancel**. Save
  stores all unsaved runs before closing. Exporting, including complete JSON,
  does not mark a run as saved locally or clear that warning. Complete legacy
  exports can still reopen through **Open exported results**; local saves take precedence.

Existing installations continue using their earlier `ParaDigMaDesktop` history
folder when a Studio history folder does not yet exist. Saved result files stay
at their original paths and remain available through Runs.

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
retained. Raw pulse-rate preparation requires accelerometer channels even though
prepared PPG-only input can be analyzed. The default PPG quality classifier may
reject a recording's windows, producing no estimates.

Device compatibility, sample rate, recording duration and scientific interpretation
follow the [official documentation](https://biomarkersparkinson.github.io/paradigma/).
