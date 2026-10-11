# ParaDigMa Studio

A Windows app for extracting digital biomarkers for Parkinson's disease from real-life wearable recordings,
based on the **official ParaDigMa 1.1.2 toolbox**. Inspect wrist-sensor recordings, run gait, tremor or pulse-rate analysis modules,
and explore results. Recordings and results stay on your computer.

## Download and launch

1. Open [GitHub Actions](https://github.com/lucevers1991/ParaDigMa-Studio/actions/workflows/windows.yml)
   and select the latest **successful Windows desktop** run for `main`.
2. Under **Artifacts**, download **ParaDigMaStudio-Windows**.
3. Extract the **entire ZIP** into a new folder, keeping `_internal` beside the executable.
4. Open **ParaDigMaStudio.exe**.

Performance measurements are in the separate **ParaDigMaStudio-build-reports**
artifact; you do not need that download to run the app. Keep `_internal`, the
licence/citation files, and the security/checksum files with the executable.

The ordinary Windows build is **unsigned**. If Smart App Control blocks it, temporarily disable it
or see the [signing guide](SIGNING.md) and [source installation](docs/DEVELOPMENT.md).
A verified signing identity must be configured before the signed workflow can produce a trusted build.

## Your first analysis

1. **Data:** Open one or more wrist sensor recordings for the same subject (Ctrl/Shift-select
   in the file picker). Use the recording selector to inspect each file's sensor and time statistics,
   overlay selected channels in Graphs, or view original samples in Tables.
3. **Analyze:** Run any combination of gait, tremor and pulse rate analysis modules.
   Review units, time representation, watch side and channel mapping; use each
   field's **i** button for guidance. Then click **Run Analysis**.
4. **Results:** Overview shows module aggregates and metadata. Graphs compare
   selected metrics from multiple modules across recording time; Tables includes each module's
   classification, quantification and aggregation tables.
   Choose metrics in **Plot series**; zoom to inspect a time interval.
   Switch **View** between Detailed and 30-minute epochs (binary percentages
   and continuous medians). Gait range of motion / peak velocity and tremor
   power require at least 90 seconds of the corresponding presence per epoch.
   Tables and exports retain the original outputs.
6. **Runs:** Review parameters, warnings, logs and export locations. Ctrl/Shift-select
   runs and use **Delete Run(s)** or the Delete key, or **Clear all** to remove every
   run, after confirmation. Original sensor files are preserved.

**Check your recording's units before running.** Defaults are acceleration in **g**,
gyroscope in **deg/s**, time in **relative seconds**, and **x/y/z** orientation.
Keep preparation enabled for raw recordings. Missing-sample exclusion is a desktop
option enabled by default. Gap splitting defaults to off, matching ParaDigMa;
its thresholds are 1.5 seconds, with **Default** buttons to restore them.

Use **Export…** on any Results tab to choose tables, metadata and **JSON** or
**CSV**. Multiple CSV tables are packaged in a ZIP.
Click **Save results** to store the complete current run locally and reopen it
from **Runs** after restarting. Closing warns about any unsaved runs, with options
to save them, discard them or cancel. [See the workspace screenshots](docs/WORKSPACE.md).

## Supported input

CSV, Parquet, trusted pickle (`.pkl` / `.pickle`), TSDF `*_meta.json`,
Axivity `.cwa`, and supported Empatica `.avro` recordings.
Keep TSDF binary companion files beside the metadata JSON.
Pickle files can execute code: open only trusted files.

| Analysis | Required channels |
| --- | --- |
| Tremor | `time`, `gyroscope_x`, `gyroscope_y`, `gyroscope_z` |
| Gait | `time`, `gyroscope_x`, `gyroscope_y`, `gyroscope_z`, `accelerometer_x`, `accelerometer_y`, `accelerometer_z` |
| Pulse rate | `time`, `green`; raw PPG preparation also requires accelerometer channels |

## More information

- [User guide](docs/USER_GUIDE.md): units, preparation, statistics, exports and common issues.
- [Official ParaDigMa documentation](https://biomarkersparkinson.github.io/paradigma/): scientific methods and device requirements.
- [Output verification](docs/SCIENTIFIC_TESTS.md): comparisons with the official analysis modules from the **official ParaDigMa 1.1.2 toolbox**.
- [Development and building](docs/DEVELOPMENT.md), [codebase audit](docs/CODEBASE_AUDIT.md), [performance review](docs/PERFORMANCE.md), and [security](SECURITY.md).

## License

ParaDigMa Studio is licensed under the [Apache License 2.0](LICENSE).
Copyright 2026 ParaDigMa Studio contributors. Dependencies and third-party
assets retain their own licences and attribution notices.

## Acknowledgement and citation

Scientific processing is provided by **ParaDigMa**, developed by its authors and
contributors and licensed under [Apache 2.0](src/paradigma_studio/data/notices/LICENSE-paradigma.txt).
For research, cite Post et al. (2024), *ParaDigMa: Parkinson's disease Digital Markers*,
[doi:10.5281/zenodo.13838392](https://doi.org/10.5281/zenodo.13838392), and relevant
pipeline publications. **About** in the app provides credits, the
licence and a copyable BibTeX citation. [Full acknowledgement and citation files](src/paradigma_studio/data/notices/ACKNOWLEDGEMENTS.md)
are also included beside the Windows executable.

Version **0.5.32**. Scientific processing uses the pinned official toolbox; the app's
regression tests check equivalent outputs for representative workflows.
