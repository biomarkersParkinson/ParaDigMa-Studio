# ParaDigMa scientific workspace

These screenshots show the native Qt development build using the public Axivity CWA example bundled with ParaDigMa. Windows executables are built and checked by the repository's GitHub Actions workflow.

## Data

Overview shows sample counts and separates sensor-channel descriptives from time-channel statistics. Sensor ranges, medians and IQRs use finite original samples. Sampling rate is estimated from the median positive time interval; the displayed gap threshold is 1.5 times that interval. Numeric time units are explicit, and invalid timestamps are not bridged. The recording metadata box has been removed. The panels stack in compact windows.

![Data workspace](screenshots/data.png)

Graphs supports checkboxes for multiple channels, Select all/Clear, stable distinct colors and a legend. Values remain in their original file units; no normalization is applied. Display sampling remains limited to 20,000 points per selected channel while Tables and exports retain all samples.

![Original sensor graphs](screenshots/data-graphs.png)

Each graph has one inline **Graph settings** panel for title, axis labels,
grid and legend. Expand **Axis limits** for manual bounds. Pan, zoom, reset
view and figure saving stay on the toolbar; the two generic figure dialogs
have been removed.

![Integrated graph settings](screenshots/graph-settings.png)

![Original sensor tables](screenshots/data-tables.png)

## Analyze

Select gait and tremor independently or together, or pulse rate on its own. All settings are in one Analysis parameters panel. The Run Analysis button remains visible when the page scrolls.

![Analysis workspace](screenshots/analyze.png)

## Results

Metric and axis controls are on the page; expand Filters for text/numeric bounds. Overview, Graphs and Tables share the selected rows. Metadata is available within Overview.

![Result overview](screenshots/results.png)

![Interactive result graphs](screenshots/graphs.png)

Sensor context opens in a full-size tab. In this example, explicit gait-segment metadata links a derived arm-swing result to original sensor samples; individual arm-swing timestamps are not inferred.

![Original sensor context](screenshots/sensor-context.png)

## Runs

Select a run to review status and its Parameters, Warnings, Outputs and Processing log tabs below the history list. Session results and explicitly exported JSON can be reopened here.

![Run history](screenshots/runs.png)

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
