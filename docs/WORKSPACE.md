# ParaDigMa scientific workspace

These screenshots show the native Qt development build using the public Axivity CWA example bundled with ParaDigMa. Windows executables are built and checked by the repository's GitHub Actions workflow.

## Data

Overview shows sample counts and separates sensor-channel descriptives from time-channel statistics. Sensor ranges, medians and IQRs use finite original samples. Sampling rate is estimated from the median positive time interval; the displayed gap threshold is 1.5 times that interval. Numeric time units are explicit, and invalid timestamps are not bridged. The recording metadata box has been removed. The panels stack in compact windows.

![Data workspace](screenshots/data.png)

Graphs supports checkboxes for multiple channels, Select all/Clear, stable distinct colors and a legend. Values remain in their original file units; no normalization is applied. Continuous displays are limited to 20,000 points per channel; binary indicators retain every timestamp in separate presence/absence rows. Tables and exports retain all samples.

![Original sensor graphs](screenshots/data-graphs.png)

Each graph has one inline **Graph settings** panel for title, axis labels,
grid and legend. Expand **Axis limits** for manual bounds. Pan, zoom, reset
view and figure saving stay on the toolbar; the two generic figure dialogs
have been removed.

![Integrated graph settings](screenshots/graph-settings.png)

![Original sensor tables](screenshots/data-tables.png)

## Analyze

Select any combination of gait, tremor and pulse rate. All settings are in one Analysis parameters panel, with an **i** button beside each field for inline documented guidance. Axis and column-mapping examples make the mapping direction explicit. The Run Analysis button remains visible when the page scrolls. Combined IMU/pulse selections run two official workflows in the background and retain successful outputs if another workflow fails.

![Analysis workspace](screenshots/analyze.png)

![Inline guidance for device axes and column mapping](screenshots/analyze-help.png)

## Results

Overview shows official aggregate values and relevant metadata grouped into module
cards. Gait segment metadata is summarized by counts and duration distributions;
individual segment records are reserved for detailed inspection. Detail filters
do not replace the official aggregate values with selection statistics.

![Result overview](screenshots/results.png)

Graphs and Tables contain classifications and quantifications only. The Plot
series tree supports multiple modules and metrics simultaneously, with vertically
aligned plots sharing recording date/time. Dates come from source timestamps or
metadata; files with only elapsed time can use a user-supplied time origin.
Gait points are estimated within explicit segment boundaries and labeled as estimates.
Plot series is the sole graph selector. Graphs use a consistent palette, subtle
grids and shared bottom time labels; scrolling works over the graph canvas.
Binary outputs use presence/absence marks at their observed timestamps.

Filters contains only Time origin and From/Until. Calendar and clock selectors
use the recording timezone when known. Recordings without dates use elapsed
seconds until a time origin is supplied.

![Interactive result graphs](screenshots/graphs.png)

![Calendar and time filters](screenshots/results-filters.png)

The [calendar popup](screenshots/calendar.png) has readable day headings. In
[compact windows](screenshots/results-filters-compact.png), the time fields wrap
onto two rows, or one field per row when wider native controls require it.
The Results workspace scrolls when its controls and graphs exceed the window height.

Tables retain official values alongside recording timestamps and gait timing annotations.

![Detailed result tables](screenshots/results-tables.png)

Sensor context opens in a full-size tab. In this example, explicit gait-segment
metadata links a derived arm-swing result to original sensor samples. Drill-down
uses the entire recorded segment, rather than treating an estimated point as an
observed arm-swing timestamp. The CWA example can return a tremor aggregation
error when too few tremor windows are detected; available detail remains visible.

![Original sensor context](screenshots/sensor-context.png)

## Runs

Select a run to review status and its Parameters, Warnings, Outputs and Processing log tabs below the history list. Session results and explicitly exported JSON can be reopened here.

![Run history](screenshots/runs.png)

## Acknowledgement and citation

**About & citations**, available on every page, credits the official ParaDigMa
authors and provides research references, a copyable BibTeX entry and the complete
upstream licence. Attribution files also accompany the executable.

![ParaDigMa acknowledgement and research citations](screenshots/acknowledgements.png)

## Compact layout

Collapse the sidebar for more room. Controls are integrated into each page, and settings persist while navigating.

![Compact analysis layout](screenshots/compact.png)

Dropdowns use dark text on white and white text on blue for the selected item,
including when the operating system uses a dark palette. The outer popup also
uses a white background, without dark strips above or below the list. Parameter
checkboxes use explicit borders and checkmarks. All table headings align left
and keep their full text, with horizontal scrolling for wider tables.

![Dropdown popup](screenshots/dropdown.png)

See the [README](../README.md) for file formats, input-unit requirements, local-history storage and executable download instructions.
