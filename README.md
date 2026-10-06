# ParaDigMa Desktop

A native Windows desktop wrapper around the **official ParaDigMa 1.1.2 toolbox**. Open a wrist-sensor recording, select gait, tremor, gait + tremor, or pulse-rate analysis, run `paradigma.orchestrator.run_paradigma`, and explore the returned tables and plots. Processing runs in a background thread. Data stays on your machine; the application does not upload recordings.

## Scientific workspace

Version **0.2.2** separates analysis configuration from result exploration, using four pages in a collapsible sidebar:

See the [workspace screenshots](docs/WORKSPACE.md) for the redesigned layout and sensor drill-down.

| Page | Workflow |
| --- | --- |
| **Data** | Overview shows sample/channel/missing-value counts, channel details and metadata. Graphs previews original signals; Tables shows original samples. |
| **Analyze** | Select modules directly: gait and tremor independently or together, or pulse rate on its own. Set units, axes, mapping, preparation and gap thresholds in one integrated parameter panel. |
| **Results** | Overview, Graphs and Tables share the same selection. Choose metrics and axes directly on the page; expand Filters for text/numeric bounds. Participant and section controls appear when those fields exist. |
| **Runs** | Select a run and review its parameters, warnings, outputs and processing log below the history list. Reopen results or reuse parameters. |

All controls live on their main pages. Collapse the sidebar for more space. Use **Ctrl+O** to open a recording, **Ctrl+Enter** to run from Analyze, and **Alt+1–4** to switch sections. Supported analyses remain those of the installed toolbox.

Results show descriptive summaries of selected rows; official aggregations remain separate datasets. Participant filtering is available only when the actual output includes a participant identifier. Select a result row or click a time-based plot point to inspect nearby original samples in a full-size **Sensor context** tab. Gait outputs without individual timestamps can open their recorded gait-segment interval when the toolbox supplies explicit start/end metadata. Context controls state when timing or the original recording is unavailable; no timing or sensor data is fabricated.

Run metadata and logs are saved in `%LOCALAPPDATA%\ParaDigMaDesktop\runs` on Windows (the corresponding local data directory on other systems). Original recordings are not copied there, and full result tables are kept in memory until you export them. Export JSON to reopen results after restarting; sensor drill-down requires the source frame retained in the same session. Loading another input does not replace previous results. Reopening exported results reads JSON only and does not automatically reopen sensor files, including pickle files. Parameters reused from an older run apply to the currently selected input, which should be checked before running.

## Run on Windows

Install 64-bit Python 3.12 and Git, then run these commands in PowerShell from this repository. Git installs the pinned official Open Movement reader revision:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2,<27"
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe desktop.py
```

## Build a Windows executable

Run on Windows from the repository directory:

```powershell
.\.venv\Scripts\python.exe scripts/build_desktop.py
.\.venv\Scripts\python.exe scripts/check_frozen.py dist/ParaDigMaDesktop/ParaDigMaDesktop.exe
```

Launch `dist\ParaDigMaDesktop\ParaDigMaDesktop.exe`. Distribute the **entire ParaDigMaDesktop folder**, including `_internal`; the executable depends on it. This is an unsigned portable application, not an installer. The build explicitly includes scikit-learn's native runtime libraries, including Windows `vcomp140.dll` and `msvcp140.dll`. The GitHub Actions Windows desktop workflow runs tests, builds this folder, and launches the packaged executable before uploading an artifact. The executable check loads all four bundled classifiers, extracts real tremor output from synthetic sensor samples, renders a Qt plot and exports results. A Windows binary must be built and tested on Windows; Linux builds cannot generate Windows executables.

Version 0.1.6 adds the supplied orange smartwatch icon to the executable and application window. The transparent Windows icon contains sizes from 16 to 256 pixels, and the packaged-app check verifies that the window icon renders.

Version 0.1.3 fixes `OverflowError: Python integer 65536 out of bounds for uint16` when opening CWA recordings with fractional timestamps. The app pins the official Open Movement reader to commit `087ac7b5a80b866c400d8021b7a2716d247fc034`, which widens timestamp arithmetic for NumPy 2. The older PyPI release also calls itself 0.0.1, so an existing source installation needs this explicit replacement before reinstalling the app:

```powershell
.\.venv\Scripts\python.exe -m pip install --force-reinstall --no-deps "openmovement @ git+https://github.com/digitalinteraction/openmovement-python.git@087ac7b5a80b866c400d8021b7a2716d247fc034"
```

For the downloaded executable, download and extract the entire new successful Windows artifact into a fresh folder. No Python or Git installation is needed to run it. The packaged executable check now also loads the official CWA recording, runs gait analysis and renders its output plot.

Version 0.1.4 fixes Empatica imports failing with `Gyroscope data not found in Empatica file`. The official example contains 115,904 accelerometer samples and an empty gyroscope stream. The wrapper follows the official device-loading tutorial to import these samples without requiring gyroscope data, and applies each IMU sensor's own conversion parameters when gyroscope data is present.

**Import support does not imply that every pipeline can analyze the recording.** Gait and tremor require gyroscope samples. Pulse rate requires raw green PPG; the example's processed BVP signal is not imported as green PPG. The example therefore opens for accelerometer inspection, with its analysis requirements shown in the app. No missing sensor channels are fabricated. Empatica import currently supports one Avro record with accelerometer samples and optional gyroscope samples on the same timeline. Multi-record files or IMU streams with different timestamps/rates need splitting or alignment before import. Other Avro streams such as BVP, EDA and temperature are not imported by this IMU adapter.

## Performance

Version 0.2.2 defers analysis imports until the background file-loading/analysis worker needs them, keeps a persistent font cache for the portable build, and omits unused Arrow query modules and development headers. It also avoids duplicate missing-value scans and recalculating the Results summary when only the graph metric changes. Scientific processing and supported formats remain unchanged.

The first file load pays the one-time toolbox import cost; the first launch builds the font cache. Later launches reuse fonts. Windows caches live below `%LOCALAPPDATA%\ParaDigMaDesktop\matplotlib`, with separate caches after moving the bundle or updating Matplotlib. If caching is unavailable, the app uses a temporary cache.

See the [performance review](docs/PERFORMANCE.md) for measurements and limits. Windows build artifacts include `performance.json` with launch samples and component sizes. To measure your own portable build:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_desktop.py dist/ParaDigMaDesktop/ParaDigMaDesktop.exe --report performance.json
```

## Smart App Control blocks the executable

A separate manual **Windows signed desktop** workflow is now available. Follow [SIGNING.md](SIGNING.md) to create and verify a Microsoft Artifact Signing publisher account and configure GitHub OIDC. The ordinary **Windows desktop** artifact remains unsigned; signing cannot run successfully until the account is configured and publisher verification is complete.

The current GitHub Actions artifact is unsigned. If Windows reports that its publisher cannot be verified, downloading another unsigned build will not establish publisher trust. The dependency audit, test results and SHA-256 manifest do not replace a publisher signature.

A signed distribution requires a trusted Windows code-signing certificate or a signing service with publisher identity verification. No signing identity is configured in this repository. A locally generated self-signed certificate does not establish trust for an ordinary recipient's Windows installation. Signing also needs to account for bundled executable code and dependencies; signing only the launcher does not guarantee that Smart App Control will accept the complete application.

For development, download this repository's source and use the Python installation commands above. Launch from the repository directory with the verified Python interpreter directly:

```powershell
.\.venv\Scripts\python.exe desktop.py
```

This avoids the generated unsigned desktop launcher. It is an alternative way to run the application, not a guarantee of Smart App Control compatibility: Windows may still block a native dependency. For isolated testing, see the disposable VM/Windows Sandbox instructions in [SECURITY.md](SECURITY.md). Keep the host's security protections enabled. Do not assume a SmartScreen “Run anyway” instruction or removing a download's blocked flag resolves a Smart App Control publisher block.

## Open and analyze a recording

Version 0.1.5 handles the official Physilog Parquet example's ten missing gyroscope samples. **Exclude missing sensor samples** and **Split recordings at time gaps** are enabled by default in the desktop interface. The source recording remains unchanged; analysis excludes rows with non-finite values in required channels, logs the count, and records it under `metadata/desktop_preparation` and in JSON exports. Sections on either side of excluded rows run independently, with gap boundaries also preserved. Uncheck exclusion to retain strict rejection of missing values. The Python `analyze` API remains strict unless called with `drop_missing_samples=True`. Missing time differences still require a valid timeline; sensor-row exclusion preserves all elapsed time differences before removing rows.

The full official Physilog recording was checked: 876,535 input samples, 10 excluded samples, five continuous sections, and non-empty filtered/unfiltered gait output. Tests and executable checks use a documented 12,010-row excerpt containing the missing samples and a recording gap.

1. Open a CSV, Parquet, trusted pickle (`.pkl`/`.pickle`), TSDF `*_meta.json`, Empatica `.avro`, or Axivity `.cwa` file. Keep TSDF binary companions beside the JSON metadata. These formats use the toolbox's own loaders, with the Empatica compatibility adapter described above. Selecting one file does not analyze unrelated files in its directory.
2. Open **Analyze**, select **Analysis modules**, and review **Analysis parameters** for watch side, units, numeric time representation, axes and column mapping. Gait and tremor allow multi-selection. Selecting pulse rate clears the other modules because the toolbox runs it separately. Defaults are relative seconds, acceleration in g, gyroscope in deg/s, and x/y/z orientation. **These defaults may not match your recording.** Signed axes such as `-y,x,z` are supported. Use column mapping for alternate channel names: `{"timestamp": "time", "gyr_x": "gyroscope_x", "ppg": "green"}`. Map all required channels.
3. Keep preparation enabled for raw data. Only select “Already prepared” for data already converted to ParaDigMa's units, orientation and sampling requirements. Conversion controls are disabled in prepared mode; column mapping still applies. Gap splitting is enabled by default, using 1.5 seconds for the maximum gap and minimum section duration, set in the same parameter panel. Segments run independently, and multi-segment output includes `file_key` identifiers such as `segment_1` and `segment_2`.
4. Click **Run Analysis**. Follow progress and warnings in **Runs**. Completion opens **Results**; failures are reported inline and partial results remain available.
5. Choose an output dataset and metric in **Results**. Overview, Graphs and Tables share the active filter selection. The plot toolbar supports zoom, pan and saving the figure. Plots sample selections longer than 20,000 rows for responsiveness; tables retain every selected row. Multiple participants display as points and recording sections are not joined into one continuous line. Gait filtered/unfiltered outputs are kept separate.
6. Export the **selected rows** as CSV, or **all results** with source/version/settings as JSON. Export locations appear in **Runs**, where JSON results can be reopened later. JSON exports are not limited by current exploration filters.

Required channels:

| Pipeline | Columns |
| --- | --- |
| Tremor | `time`, `gyroscope_x`, `gyroscope_y`, `gyroscope_z` |
| Gait | Tremor columns plus `accelerometer_x`, `accelerometer_y`, `accelerometer_z` |
| Pulse rate | `time`, `green` (accelerometer optional) |

Default toolbox diagnostic files use a unique temporary directory and are deleted after analysis; the processing log is retained with local run metadata. CSV exports neutralize formula-like text, while JSON preserves original text. Exports protect both their source sensor file and the currently loaded input, including when these are different recordings.

The wrapper performs preparation explicitly with the official ParaDigMa functions before calling `run_paradigma` with prepared data. This ensures that selected acceleration units and orientation apply to each pipeline, avoids missing gap defaults in ParaDigMa 1.1.2, and prevents preprocessing from interpolating between separate recordings. Logged tremor/pulse-rate failures omitted from the toolbox's returned error list are added to the wrapper's result errors. Empty quantified output remains distinct from a processing failure.

Analysis requires numeric, finite retained sensor samples and increasing timestamps, except when using difference-based time. The selected exclusion option can remove rows with missing/non-finite required samples before analysis. CSV date strings need conversion to one of the supported numeric time units before import. Pulse rate runs separately from gait/tremor. In ParaDigMa 1.1.2, raw PPG preparation also requires accelerometer channels; PPG-only input must already be prepared. Sensor rate, recording duration, device compatibility and scientific interpretation remain governed by the [official toolbox documentation](https://biomarkersparkinson.github.io/paradigma/). Not every file with a supported extension necessarily contains compatible sensor data. Pickle files can execute code; open only files from trusted sources.

## Development and validation

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade 'pip>=26.2,<27'
.venv/bin/python -m pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/paradigma-mpl .venv/bin/python -m pytest -q
.venv/bin/paradigma-desktop
```

Tests exercise CSV/Parquet/pickle loading, the official Axivity CWA example (36,400 samples) and its gait output, real tremor, gait and pulse-rate pipeline execution, including tremor preparation and export, invalid input handling, nested gait result traversal, Qt result rendering/plotting, and background-worker error delivery. Fractional CWA timestamp checks cover large fractions and negative offsets at 100 and 3,200 Hz. Synthetic gait input can yield no detected gait bouts, and the pulse-rate quality classifier rejects the synthetic sine signal (no estimates). TSDF loading uses the upstream implementation; representative app imports are needed to validate that format. A Windows CI build is provided but must run before claiming Windows packaging has been verified. The bundled public fixtures and their license/provenance are in `src/paradigma_desktop/data/`.

Scientific equivalence tests adapted from the official ParaDigMa automated tests compare the app with an independent direct ParaDigMa 1.1.2 workflow. They check preprocessing, features, classification probabilities/labels, all derived measurements, both gait branches, aggregations, timestamps, missingness and scientific metadata, plus actual graph/table values and JSON/CSV exports. They cover recorded official IMU/PPG fixtures, Axivity CWA, Physilog missing samples/gaps, both watch sides, unit/orientation conversion and all six numeric time encodings. Run only these checks with `python -m pytest -m scientific -q`; normal tests and Windows CI include them automatically. The PPG fixture produces no estimates at default settings; a separate explicit 100 Hz/10-second configuration tests positive estimates without changing the GUI defaults. See [scientific test methodology and limitations](docs/SCIENTIFIC_TESTS.md). These tests establish equivalence on the tested workflows, not clinical validation or comprehensive device coverage.

On the CWA example, ParaDigMa 1.1.2 returns tremor window measurements but can report an aggregation error (`dataset input should have multiple elements`) when too few detected tremor windows are available for its modal statistic. The application retains the window results and reports this upstream limitation; the CWA import fix does not change scientific aggregation rules.

Regression checks also cover mapped/prepared numeric text, short-recording failures, separate gap segments at different sensor rates, units/orientation, custom time indexes, missing samples, numeric plot column names, background UI recovery, JSON float precision, and protecting TSDF companion binaries during export.

Workspace checks cover sidebar navigation, integrated controls, module multi-selection, exact parameter forwarding/reuse, readable dropdown popups under a dark system palette, original Data graph/table values, coordinated participant/section/numeric filters, selected-row CSV exports, explicit sensor-context alignment, gait segment metadata, nullable plotting values, persisted completed/failed runs, history write failures, and safe reopening of JSON results without sensor-file deserialization. The packaged executable exercises the redesigned navigation, shared filters, real CWA gait sensor context, and reopening exported results through a Qt background worker.

Empatica checks import the official Avro example in source tests and the packaged executable, verify Qt table display, cover absent/empty gyroscope streams and per-sensor conversion for both pre-6.5.0 and newer schemas, and reject malformed or unaligned samples instead of silently pairing them. The example's origin, hash and Apache license accompany the bundled fixture.

## Security

See [SECURITY.md](SECURITY.md) for the review findings, dependency-audit exception, remaining risks, and a Windows Sandbox configuration for a first run. Use a normal user account without administrator elevation. Pickle import requires explicit trust confirmation; prefer CSV/Parquet for exchanged recordings.

Windows builds audit installed Python dependencies and include package versions, the source commit, the audit report and `SHA256SUMS.txt` in the artifact. These checks do not constitute a security guarantee or a digital signature.
