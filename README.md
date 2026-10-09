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

1. **Data:** Open one or more recordings for the same subject (Ctrl/Shift-select
   in the file picker). Use the recording
   selector to inspect each file's sensor/time statistics, overlay selected
   channels in Graphs, or view original samples in Tables.
2. **Analyze:** Select any combination of gait, tremor and pulse rate.
   Review units, time representation, watch side and channel mapping; use each
   field's **i** button for guidance below the parameters box. One explanation
   opens at a time. Then click **Run Analysis**.
3. **Results:** Overview shows gait quantity (duration and segment counts),
   range of motion and peak velocity charts, other module aggregates
   and metadata. Graphs compares
   selected metrics from multiple modules across recording time; Tables shows
   module tabs with each module's classification, quantification and aggregation tables.
   Choose metrics in **Plot series**; zoom to inspect a time interval.
   Switch **View** between Detailed and 30-minute epochs (binary percentages
   and continuous medians). Gait range of motion / peak velocity and tremor
   power require at least 90 seconds of the corresponding presence per epoch.
   Tables and exports retain the original outputs.
   Use **Graph settings** or the toolbar to adjust, zoom or save figures.
   **Recording & preparation** shows the recording's start/end, prepared-data
   coverage in hours and percent of the timespan, and interruptions between
   prepared intervals. Modules with identical prepared inputs share these figures.
4. **Runs:** Review parameters, warnings, logs and export locations. Ctrl/Shift-select
   runs and use **Delete Run(s)** or the Delete key, or **Clear all** to remove every
   run, after confirmation. Original sensor files are preserved.

Multiple files share the selected analysis settings. ParaDigMa processes them
independently, combines their detailed outputs with file identifiers, and computes
subject-level aggregates over the combined results.

**Check your recording's units before running.** Defaults are acceleration in **g**,
gyroscope in **deg/s**, time in **relative seconds**, and **x/y/z** orientation.
Keep preparation enabled for raw recordings. Missing-sample exclusion is a desktop
option enabled by default. Gap splitting defaults to off, matching ParaDigMa;
its thresholds are 1.5 seconds, with **Default** buttons to restore them.

Use **Export…** on any Results tab to choose tables, metadata and **JSON** or
**CSV**. Multiple CSV tables are packaged in a ZIP.
Export JSON to reopen results after restarting. Run history alone does not save
full result tables. [See the workspace screenshots](docs/WORKSPACE.md).

Continuous results use bars; missing values leave gaps. Gait bar positions are
marked as estimates within recorded segments. A prepared-input availability track
shows recording coverage. Set **Time origin** in Analyze to display calendar dates;
the default is derived from the file when available. **Stop Analysis** cancels a run.

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
- [Development and building](docs/DEVELOPMENT.md), [codebase audit](docs/CODEBASE_AUDIT.md), [performance review](docs/PERFORMANCE.md), and [security](SECURITY.md).

## Acknowledgement and citation

Scientific processing is provided by **ParaDigMa**, developed by its authors and
contributors and licensed under [Apache 2.0](src/paradigma_desktop/data/notices/LICENSE-paradigma.txt).
For research, cite Post et al. (2024), *ParaDigMa: Parkinson's disease Digital Markers*,
[doi:10.5281/zenodo.13838392](https://doi.org/10.5281/zenodo.13838392), and relevant
pipeline publications. **About** in the app provides credits, the
licence and a copyable BibTeX citation. [Full acknowledgement and citation files](src/paradigma_desktop/data/notices/ACKNOWLEDGEMENTS.md)
are also included beside the Windows executable.

Version **0.5.23**. Scientific processing uses the pinned official toolbox; the app's
regression tests check equivalent outputs for representative workflows.
