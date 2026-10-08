# Using ParaDigMa Desktop

See the [README](../README.md) for downloading the Windows app and the basic workflow.

**About** at the bottom of the sidebar (or **F1**) opens the ParaDigMa acknowledgement, official
software citation, pipeline publication links and full Apache 2.0 licence.
**Copy software citation** copies the upstream BibTeX entry for research use.

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
Set processing options in **Analysis parameters**. Each field's **i** button expands
inline guidance with a reference to the official ParaDigMa documentation.
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
  Uncheck it for strict rejection. Invalid timestamps still require correction.
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

Data **Graphs** overlays checked channels with stable colors and a legend.
Values retain their file units. Data **Tables** shows original samples.

Results **Overview** shows official aggregates and relevant pipeline metadata in
module cards. **Recording & preparation** groups recording information and input
preparation counts without duplicating identical workflows. Gait segment metadata
is summarized by counts and duration distributions; individual segment records
remain in the metadata export.

Results **Graphs** compares classifications and quantifications across modules.
Check metrics in **Plot series**. Aligned plots share one time axis, with time and
date on separate lines. The axis stays visible while scrolling and follows pan
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
Tremor's duplicate arm-rest and checked-tremor
predictors appear only under Classification in Plot series.

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
percentages. Plots are grouped by module, following Plot series order, and long
series names wrap in full. Gait and filtered gait share one observed-time denominator, so filtered
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
selected time. Gait measurements open the complete official segment rather than
treating their estimated positions as observed event timestamps. Sensor context
requires the original recording to remain available in the session.

Each graph has one inline **Graph settings** panel for title, axis labels, limits,
grid and legend. Date limits accept ISO timestamps. Click a graph to edit its
vertical settings; horizontal limits apply to all aligned plots. Pan, zoom, reset
and figure saving remain on the toolbar. Saved figures include the time axis.
Raw sensor plots retain continuous signal lines and limit display to 20,000 samples
per channel; result bars and binary indicators retain every output.

## Exports and run history

**Export…** appears on every Results tab. Choose a format and check which original
tables or metadata groups to include:

- **JSON:** one structured file containing selected outputs and analysis provenance.
  Non-finite values become null. Full JSON exports reopen after restarting without
  loading the sensor recording. Select all outputs/metadata to preserve all drill-down
  timing information.
- **CSV:** one table exports as CSV. Multiple tables or metadata selections export as
  a ZIP containing separate CSV files, selected metadata JSON and analysis provenance.
  Scientific tables retain their original columns; formula-like text is neutralized.
- **Runs:** stores status, parameters, separate warnings and errors, logs and export
  locations in `%LOCALAPPDATA%\ParaDigMaDesktop\runs` on Windows. Full results remain
  in memory until exported; original recordings are not copied there.

**Stop Analysis** remains available below Analyze settings while a run is active.
Cancellation stops the owned analysis process, removes its temporary files and records
**Cancelled** in Runs without treating cancellation as an analysis error.

Select a completed or cancelled run and choose **Delete Run…**, or press **Delete**
while the run list has focus. A confirmation lists the associated exports to be
permanently removed with the history entry. Original sensor files, TSDF companions
and exports referenced by another run are protected. Running jobs cannot be deleted.
Reused parameters apply to the currently selected input; check it before running.

Shortcuts: **Ctrl+O** opens recordings, **Ctrl+Enter** runs analysis, **Alt+1–4** switches
pages, **Delete** deletes a selected run after confirmation, and **F1** opens About.

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
