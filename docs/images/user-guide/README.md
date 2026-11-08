# User guide screenshots

These are native captures of the current source app, not the historical images
under `docs/archive/screenshots`. The seven workspace images are 1450 × 1000
pixels. All use Qt's Fusion style at scale factor 1. The captures were made on
Linux; the Windows app
uses the same page controls, with platform-dependent fonts and window decoration.
The full set was regenerated and visually reviewed for **1.0.0rc1** on
26 October 2026. Data graphs, Results graphs and sensor context were refreshed
on 28 October for the shared hand tool and navigation controls; see
[commit `1337c33`](https://github.com/biomarkersParkinson/ParaDigMa-Studio/commit/1337c33).
The full set was regenerated and reviewed on 5 November 2026 for the
**Open folder…** control in Data; the Data images and Runs capture were updated.
An earlier set was regenerated and reviewed on 5 November for the single
**Open recordings…** menu with **Files…** and **Folders…** choices. Selection
uses the standard Windows dialogs; those OS windows are not illustrated by
these Linux captures. The earlier custom-browser illustration was removed.
The latest refresh restores separate **Open files…** and **Open folders…**
buttons while retaining native multi-folder selection. Long dropdowns now use
the same light scrollbar design as the workspace.
The full set was regenerated and reviewed on 6 November 2026 for the
loading-created Runs workflow. Only the Runs image changed: it now shows
separate loading and analysis start times for the same saved example.
These images illustrate the current source. The
[tagged guide](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v1.0.0rc1/docs/USER_GUIDE.md)
retains the screenshots for the published candidate.

The full set was regenerated and reviewed on 8 November 2026 for the compact
run reference in Results. Overview, Graphs and Sensor context now identify the
same entry shown in Runs; the Runs capture also shows the compact duration
summary and the blue eye marking the displayed run. Data and Analyze captures
were unchanged.

The seven workspace images follow one real gait analysis of the public, unmodified Axivity
example `src/paradigma_studio/data/test_data.CWA` (36,400 original samples).
Source attribution and its SHA-256 checksum are in the bundled
[data notes](../../../src/paradigma_studio/data/README.txt).
The recording is distributed under ParaDigMa's Apache 2.0 licence; see the
[upstream notice](../../../src/paradigma_studio/data/notices/LICENSE-paradigma.txt).

The capture uses the GUI's gait configuration, file-derived units and clock,
left watch side, no axis inversions, and enabled missing-sample exclusion and
gap splitting. It runs the official analysis and saves the complete result
through the normal application services, beginning with a real background
import that creates the Runs entry. The source example returns gait
quantifications, warnings and no errors. Warnings and absent filtered measures
are left visible; output values and run status are not invented or retouched.
The Results graph additionally selects unfiltered range of motion. Sensor context
opens the first unfiltered measurement's full official gait segment.

To refresh the images from a source checkout with development dependencies:

```sh
uv run --locked --all-groups python scripts/capture_user_guide.py
```

Run from the repository root. The script configures offscreen Qt with the
repository's 1920 × 1080 test screen unless `QT_QPA_PLATFORM` is already set.
`--output PATH` selects another image directory. Input copies, history and saved
results use a temporary directory; no personal recordings or user history are read.
Regenerate the full set together and inspect all images before committing them.
Update the user guide's captions if the demonstrated controls or selections change.
