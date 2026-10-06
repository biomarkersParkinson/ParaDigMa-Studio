# ParaDigMa scientific workspace

These screenshots show the native Qt development build using the public Axivity CWA example bundled with ParaDigMa. Windows executables are built and checked by the repository's GitHub Actions workflow.

## Data

Overview shows sample counts, channel details, missing values and metadata. Graphs and Tables show the original sensor data.

![Data workspace](screenshots/data.png)

![Original sensor graphs](screenshots/data-graphs.png)

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
including when the operating system uses a dark palette.

![Dropdown popup](screenshots/dropdown.png)

See the [README](../README.md) for file formats, input-unit requirements, local-history storage and executable download instructions.
