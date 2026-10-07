# Using ParaDigMa Desktop

See the [README](../README.md) for downloading the Windows app and the basic workflow.

**About** at the bottom of the sidebar (or **F1**) opens the ParaDigMa acknowledgement, official
software citation, pipeline publication links and full Apache 2.0 licence.
**Copy software citation** copies the upstream BibTeX entry for research use.

## Input and analysis settings

The app uses the official ParaDigMa loaders and processing functions, with an
Empatica IMU import adapter. Opening a file loads that recording only.

Choose any combination of gait, tremor and pulse rate in **Analysis modules**.
Set processing options in **Analysis parameters**. Each field's **i** button expands
inline guidance with a reference to the official ParaDigMa documentation.
The axes example explains the direction of each signed mapping; column-mapping
examples rename your file's columns to the required toolbox names.

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
  default maximum gap and minimum section duration are both 1.5 seconds.
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

Results **Overview** shows all returned official aggregates and relevant metadata
in module cards. Gait metadata is summarized by branch: segment count and total,
median, IQR and range of segment durations. Individual segment records stay out
of Overview. Detail filters do not recompute or alter official aggregates.

Results **Graphs** and **Tables** contain only classifications and quantifications.
Check **Plot series** to compare metrics from several modules on vertically aligned
plots with a shared time axis. Different quantities keep their own vertical scales.
The Plot series tree is the graph selector; choose a detailed output separately
on Tables for its table and CSV export. Only the shared From/Until time range
and Time origin appear in Filters. Mouse-wheel and touchpad scrolling work while
the pointer is over result graphs.

Absolute dates come from the source recording's datetime channel, absolute numeric
timestamps or start metadata, aligned to the analysis timeline. Known timezones
are preserved; unzoned timestamps are marked **timezone unspecified**. Relative-only
recordings display elapsed seconds. To display dates, enable **Time origin** in
Filters and use the calendar and clock to set the date/time corresponding to
timeline second zero. This is recorded as user supplied and changes presentation
only. From/Until uses calendar and clock selectors when a recording clock is
available, and seconds otherwise. Each checkbox enables or clears that field.
Known timezones and daylight-saving offsets are retained; unzoned recordings
remain unzoned. Removing the origin preserves the selected range in seconds.
Time fields wrap according to their actual size, including native Windows font
metrics. Each Results view scrolls vertically while Overview, Graphs and Tables stay in place. Export and Filters are alongside the tabs.

Combined workflows can have different internal time origins after excluding
missing samples. The display aligns each workflow to the same source clock.
**Analysis time (s)** retains the original module time; **Timeline time (s)** appears
when alignment offsets are needed. CSV includes these display annotations, and
JSON preserves the offsets so reopened results use the same dates.

Gait arm-swing measurements lack individual timestamps. Their display positions
are evenly spaced bin midpoints within each official segment's start/end interval,
computed before filtering. They are labeled **Estimated within gait segment** and
drawn as points. Tables show their time basis and segment boundaries. Missing or
invalid segment metadata leaves timing unavailable; sample positions are not used
as invented time labels. Scientific outputs and aggregate calculations are unchanged.

The app retains the toolbox's official classification Parquet exports because
ParaDigMa 1.1.2 omits these tables from its orchestrator return value. Classification
is not rerun and predictions are not reconstructed from quantified measurements.

All graphs share one inline **Graph settings** panel for title, axis labels and
limits, grid and legend. Expand **Axis limits** to set automatic or explicit bounds; date axes
accept ISO timestamps. **Apply** changes presentation; **Reset** restores the
current graph's labels and automatic limits. Choosing a different metric or
channel refreshes labels and limits. Grid and legend preferences persist.
For multiple result plots, click the graph whose labels or vertical limits you
want to edit. Shared horizontal limits, grid and legend settings apply across
plots. The toolbar retains reset view, back/forward, pan, zoom and figure saving.

Continuous plots display at most 20,000 samples per series for responsiveness.
Binary indicators use separate **Present · 1** and **Absent · 0** rows, with square
marks at every observed output timestamp. Missing states stay blank; no durations
or transitions are inferred. These indicators are not subsampled, so isolated
detections remain visible. Tables and exports retain all selected rows.
Result lines do not join separate sections;
multiple participants display as points. Filtered and unfiltered gait outputs
remain separate datasets.

Select a result row or click a time-based graph point to inspect original samples
in **Sensor context**. Gait outputs without timestamps can open explicit
start/end intervals supplied by the toolbox. This requires the original data
retained in the same session and usable timing metadata.

## Exports and run history

- **CSV:** exports selected rows with their displayed timing annotations, including
  the estimated gait time basis; formula-like text is neutralized.
- **JSON:** exports all outputs, source, toolbox version and settings, independently
  of exploration filters. Scientific tables keep their original columns; display
  clock metadata is saved with the analysis provenance. JSON converts non-finite
  scalars to null. Absolute plots can be restored without reopening the recording.
- **Runs:** saves status, parameters, separate warnings and errors, log and export locations in
  `%LOCALAPPDATA%\ParaDigMaDesktop\runs` on Windows. Recordings are not copied there.
  Full result tables remain in memory until exported.

Export JSON to reopen results after restarting. Reopening JSON does not reload
the sensor file. Loading another recording leaves previous results available.
Reused parameters apply to the currently selected input; check it before running.
Exports protect source files and TSDF companion binaries from overwriting.

Default toolbox diagnostic files use a temporary directory deleted after analysis;
the processing log remains in local history.

Shortcuts: **Ctrl+O** opens a recording, **Ctrl+Enter** runs from Analyze,
and **Alt+1–4** switches pages.

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
