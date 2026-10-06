# Using ParaDigMa Desktop

See the [README](../README.md) for downloading the Windows app and the basic workflow.

## Input and analysis settings

The app uses the official ParaDigMa loaders and processing functions, with an
Empatica IMU import adapter. Opening a file loads that recording only.

Choose **Analysis modules** on Analyze: gait and tremor independently or together,
or pulse rate on its own. Set all processing options in **Analysis parameters**.

- Check acceleration units, gyroscope units and time representation against the
  recording. Numeric time supports relative, absolute or difference-based values
  in seconds or milliseconds. CSV date strings need conversion to a supported
  numeric representation before analysis.
- Set watch side and device axes. Signed orientations such as `-y,x,z` are supported.
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

Results **Overview**, **Graphs** and **Tables** share the selected output and
filters. Select metrics, horizontal axes and, when available, participants and
sections. Overview summaries describe selected rows; official aggregations remain
separate outputs.

All graphs share one inline **Graph settings** panel for title, axis labels and
limits, grid and legend. Expand **Axis limits** to set automatic or explicit bounds; date axes
accept ISO timestamps. **Apply** changes presentation; **Reset** restores the
current graph's labels and automatic limits. Choosing a different metric or
channel refreshes labels and limits. Grid and legend preferences persist.
The toolbar retains reset view, back/forward, pan, zoom and figure saving.

Plots display at most 20,000 samples per series for responsiveness. Tables and
exports retain all selected rows. Result lines do not join separate sections;
multiple participants display as points. Filtered and unfiltered gait outputs
remain separate datasets.

Select a result row or click a time-based graph point to inspect original samples
in **Sensor context**. Gait outputs without timestamps can open explicit
start/end intervals supplied by the toolbox. This requires the original data
retained in the same session and usable timing metadata.

## Exports and run history

- **CSV:** exports selected rows; formula-like text is neutralized.
- **JSON:** exports all outputs, source, toolbox version and settings, independently
  of exploration filters. JSON converts non-finite scalars to null.
- **Runs:** saves status, parameters, warnings, log and export locations in
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
