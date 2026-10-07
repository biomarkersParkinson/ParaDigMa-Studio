# ParaDigMa Desktop

A Windows app for the **official ParaDigMa 1.1.2 toolbox**. Inspect wrist-sensor
recordings, run gait, tremor or pulse-rate analysis, and explore graphs and tables.
Recordings and results stay on your computer.

## Download and launch

1. Open [GitHub Actions](https://github.com/lucevers1991/ParaDigMa4DBS/actions/workflows/windows.yml)
   and select the latest **successful Windows desktop** run for `main`.
2. Under **Artifacts**, download **ParaDigMaDesktop-Windows**.
3. Extract the **entire ZIP** into a new folder, keeping `_internal` beside the executable.
4. Open **ParaDigMaDesktop.exe**. Python and Git are not required.

The ordinary Windows build is **unsigned**. If Smart App Control blocks it,
see the [signing guide](SIGNING.md) and [source installation](docs/DEVELOPMENT.md).
A verified signing identity must be configured before the signed workflow can produce a trusted build.

## Your first analysis

1. **Data:** Open a recording. Inspect sensor/time statistics, overlay selected
   channels in Graphs, or view original samples in Tables.
2. **Analyze:** Select any combination of gait, tremor and pulse rate.
   Review units, time representation, watch side and channel mapping; use each
   field's **i** button for guidance, then click **Run Analysis**.
3. **Results:** Overview shows module aggregates and metadata. Graphs compares
   selected metrics from multiple modules across recording time; Tables shows
   module tabs with each module's classification, quantification and aggregation tables.
   Choose metrics in **Plot series** and dates/times in **Filters**.
   Use **Graph settings** or the toolbar to adjust, zoom or save figures.
4. **Runs:** Review parameters, warnings, logs and export locations.

**Check your recording's units before running.** Defaults are acceleration in **g**,
gyroscope in **deg/s**, time in **relative seconds**, and **x/y/z** orientation.
Keep preparation enabled for raw recordings. Missing-sample exclusion is a desktop
option enabled by default. Gap splitting defaults to off, matching ParaDigMa;
its thresholds are 1.5 seconds, with **Default** buttons to restore them.

Export the visible table as **CSV**, or all results and analysis settings as **JSON**.
Export JSON to reopen results after restarting. Run history alone does not save
full result tables. [See the workspace screenshots](docs/WORKSPACE.md).

Gait points use clearly marked estimated positions within recorded segment boundaries.
Files without recording dates use elapsed time until you supply a time origin.

## Supported input

CSV, Parquet, trusted pickle (`.pkl` / `.pickle`), TSDF `*_meta.json`,
Axivity `.cwa`, and supported Empatica `.avro` recordings.
Keep TSDF binary companion files beside the metadata JSON.
Pickle files can execute code: open only trusted files.

| Analysis | Required channels |
| --- | --- |
| Tremor | `time`, `gyroscope_x`, `gyroscope_y`, `gyroscope_z` |
| Gait | Tremor channels plus `accelerometer_x`, `accelerometer_y`, `accelerometer_z` |
| Pulse rate | `time`, `green`; raw PPG preparation also requires accelerometer channels |

A supported file format may still lack channels needed for an analysis. The
Empatica example imports accelerometer data for inspection; its BVP stream is
not raw green PPG, and its gyroscope stream is empty.

## More information

- [User guide](docs/USER_GUIDE.md): units, preparation, statistics, exports and common issues.
- [Official ParaDigMa documentation](https://biomarkersparkinson.github.io/paradigma/): scientific methods and device requirements.
- [Scientific validation](docs/SCIENTIFIC_TESTS.md): comparisons with the official processing workflow.
- [Development and building](docs/DEVELOPMENT.md), [performance review](docs/PERFORMANCE.md), and [security](SECURITY.md).

## Acknowledgement and citation

Scientific processing is provided by **ParaDigMa**, developed by its authors and
contributors and licensed under [Apache 2.0](src/paradigma_desktop/data/notices/LICENSE-paradigma.txt).
For research, cite Post et al. (2024), *ParaDigMa: Parkinson's disease Digital Markers*,
[doi:10.5281/zenodo.13838392](https://doi.org/10.5281/zenodo.13838392), and relevant
pipeline publications. **About** in the app provides credits, the
licence and a copyable BibTeX citation. [Full acknowledgement and citation files](src/paradigma_desktop/data/notices/ACKNOWLEDGEMENTS.md)
are also included beside the Windows executable.

Version **0.3.9**. Scientific processing uses the pinned official toolbox; the app's
regression tests check equivalent outputs for representative workflows.
