# User guide screenshots

These are native captures of the current source app, not the historical images
under `docs/archive/screenshots`. Each image is 1450 × 1000 pixels, using Qt's
Fusion style at scale factor 1. The captures were made on Linux; the Windows app
uses the same page controls, with platform-dependent fonts and window decoration.
The full set was regenerated and visually reviewed for **1.0.0rc1** on
26 October 2026; unchanged captures retain their existing files.

All seven images follow one real gait analysis of the public, unmodified Axivity
example `src/paradigma_studio/data/test_data.CWA` (36,400 original samples).
Source attribution and its SHA-256 checksum are in the bundled
[data notes](../../../src/paradigma_studio/data/README.txt).
The recording is distributed under ParaDigMa's Apache 2.0 licence; see the
[upstream notice](../../../src/paradigma_studio/data/notices/LICENSE-paradigma.txt).

The capture uses the GUI's gait configuration, file-derived units and clock,
left watch side, no axis inversions, and enabled missing-sample exclusion and
gap splitting. It runs the official analysis and saves the complete result
through the normal application services. The source example returns gait
quantifications, warnings and no errors. Warnings and absent filtered measures
are left visible; output values and run status are not invented or retouched.
The Results graph additionally selects unfiltered range of motion. Sensor context
opens the first unfiltered measurement's full official gait segment.

To refresh the images from a source checkout with development dependencies:

```sh
python scripts/capture_user_guide.py
```

Run from the repository root. The script configures offscreen Qt with the
repository's 1920 × 1080 test screen unless `QT_QPA_PLATFORM` is already set.
`--output PATH` selects another image directory. Input copies, history and saved
results use a temporary directory; no personal recordings or user history are read.
Regenerate the full set together and inspect all images before committing them.
Update the user guide's captions if the demonstrated controls or selections change.
