# ParaDigMa scientific workspace

These screenshots show the native Qt development build using the public Axivity CWA example bundled with ParaDigMa. Windows executables are built and checked by the repository's GitHub Actions workflow.

## Data

Open a recording, inspect channel metadata and preview the original signals.

![Data workspace](screenshots/data.png)

## Analyze

Choose supported analysis modules and review preprocessing before running. Advanced parameters stay in the right-hand inspector. The Run Analysis button remains visible when the configuration area scrolls.

![Analysis workspace](screenshots/analyze.png)

## Results

Overview, Graphs and Tables share the same selected rows. Descriptive summaries use actual measurements; identifiers remain available in the table and metric selector.

![Result overview](screenshots/results.png)

![Interactive result graphs](screenshots/graphs.png)

Sensor context opens in a full-size tab. In this example, explicit gait-segment metadata links a derived arm-swing result to original sensor samples; individual arm-swing timestamps are not inferred.

![Original sensor context](screenshots/sensor-context.png)

## Runs

Review status, settings, warnings, logs and export locations. Metadata persists locally. Session results and explicitly exported JSON can be reopened from this page.

![Run history](screenshots/runs.png)

## Compact layout

Collapse the sidebar or hide the inspector to give the workspace more room. Settings remain available while navigating between pages.

![Compact analysis layout](screenshots/compact.png)

See the [README](../README.md) for file formats, input-unit requirements, local-history storage and executable download instructions.
