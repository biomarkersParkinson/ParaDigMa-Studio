# ParaDigMa Studio

A Windows app for extracting digital biomarkers for Parkinson's disease from real-life wearable recordings,
based on the **official ParaDigMa 1.1.2 toolbox**. Inspect wrist sensor recordings, run gait, tremor and pulse-rate analysis modules,
and explore results. Recordings and results stay on your computer.

## Download and launch

1. Open the [latest preview release](https://github.com/biomarkersParkinson/ParaDigMa-Studio/releases/tag/v0.6.0a3).
2. Under **Assets**, download **ParaDigMaStudio-0.6.0a3-Windows-x64.zip**.
3. Extract the **entire ZIP** into a new folder.
4. Open **ParaDigMaStudio → ParaDigMaStudio.exe**, keeping `_internal` beside it.

This is a preview for evaluation and feedback. See the [release notes](CHANGELOG.md).

Development builds remain available under
[GitHub Actions](https://github.com/biomarkersParkinson/ParaDigMa-Studio/actions/workflows/windows.yml).
Performance measurements are in the separate **ParaDigMaStudio-build-reports**
artifact; you do not need that download to run the app. Keep `_internal`, the
licence/citation files, and the security/checksum files with the executable.

The ordinary Windows build is **unsigned**. Smart App Control may need to be temporarily disabled to run it, or alternatively, see
the [signing guide](SIGNING.md) and [source installation](docs/DEVELOPMENT.md).
A verified signing identity must be configured before the signed workflow can produce a trusted build.

## Your first analysis

1. **Data:** Open one or more wrist sensor recordings for the same subject (Ctrl/Shift-select
   in the file picker). Use the recording selector to inspect each file's sensor and time statistics,
   overlay selected channels in Graphs, or view original samples in Tables.
2. **Analyze:** Run any combination of gait, tremor and pulse rate analysis modules.
   Review units, time representation, watch side and channel mapping; use each
   field's **i** button for guidance. Then click **Run Analysis**.
3. **Results:** Overview shows module aggregates and metadata across the full recordings' timespan. Graphs compare
   selected metrics from multiple modules across recording time.
   Choose metrics in **Plot series**; zoom to inspect a time interval.
   Switch **View** between Detailed, 30-minute epochs, Day and a 24-hour profile
   averaging valid 30-minute summaries across days. The
   [user guide](docs/USER_GUIDE.md#inspecting-data-and-results) explains summaries,
   availability thresholds and graph controls.
   Tables and exports retain each module's original classification, quantification and aggregation outputs.
4. **Runs:** Review parameters, warnings, logs and export locations. Ctrl/Shift-select
   runs and use **Delete Run(s)** or the Delete key, or **Clear all** to remove every
   run, after confirmation. Original sensor files are preserved.

**Review the source recording configuration before running.** Carefully check the
signal columns, units, time representation, watch side and axis orientation against
your recordings, including values prefilled from file metadata.
When analyzing multiple recordings from the same subject, ensure their formatting
is consistent across files: column names, units, time representation and axis
conventions must match. One Analyze configuration applies to the entire batch.

Use **Export…** on any Results tab to choose tables, metadata and **JSON** or
**CSV**. Multiple CSV tables are packaged in a ZIP.
Click **Save results** to store the complete current run locally and reopen it
from **Runs** after restarting. See [saving and run history](docs/USER_GUIDE.md#exports-and-run-history).

## Supported input

CSV, Parquet, trusted pickle (`.pkl` / `.pickle`), TSDF `*_meta.json`,
Axivity `.cwa`, and supported Empatica `.avro` recordings.
Keep TSDF binary companion files beside the metadata JSON.
Pickle files can execute code: open only trusted files.

| Analysis | Required channels |
| --- | --- |
| Tremor | `time`, `gyroscope_x`, `gyroscope_y`, `gyroscope_z` |
| Gait | `time`, `gyroscope_x`, `gyroscope_y`, `gyroscope_z`, `accelerometer_x`, `accelerometer_y`, `accelerometer_z` |
| Pulse rate | `time`, `green` (raw PPG); accelerometer channels are optional |

Saved history and result JSON require Studio format version 1. Earlier unversioned
saved runs are unsupported and remain untouched; re-analyze the original recordings
to create current runs.

## More information

- [User guide](docs/USER_GUIDE.md): units, preparation, statistics, exports and common issues.
- [Official ParaDigMa documentation](https://biomarkersparkinson.github.io/paradigma/): scientific methods and device requirements.
- [Output verification](docs/SCIENTIFIC_TESTS.md): independent comparisons with official ParaDigMa outputs.
- [Documentation index](docs/README.md): development, architecture, tests, performance and historical reports.
- [Security](SECURITY.md) and [signing](SIGNING.md).

## License

ParaDigMa Studio is licensed under the [Apache License 2.0](LICENSE).
Copyright 2026 ParaDigMa Studio contributors. Dependencies and third-party
assets retain their own licences and attribution notices.

## Acknowledgement and citation

Scientific processing is provided by **ParaDigMa**, developed by its authors and
contributors and licensed under [Apache 2.0](src/paradigma_studio/data/notices/LICENSE-paradigma.txt).
For research, cite Post et al. (2026), *ParaDigMa: a Python toolbox for extracting Parkinson's disease digital biomarkers from daily life wrist sensor data*, [doi:10.21105/joss.09502](https://doi.org/10.21105/joss.09502), and relevant
pipeline publications. **About** in the app provides credits, the
licence and a copyable BibTeX citation. [Full acknowledgement and citation files](src/paradigma_studio/data/notices/ACKNOWLEDGEMENTS.md)
are also included beside the Windows executable.

OpenAI Codex was used to support the development, testing and documentation of ParaDigMa Studio.
