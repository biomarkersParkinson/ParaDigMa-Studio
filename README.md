# ParaDigMa Desktop

A native Windows desktop wrapper around the **official ParaDigMa 1.1.2 toolbox**. Open a wrist-sensor recording, select gait, tremor, gait + tremor, or pulse-rate analysis, run `paradigma.orchestrator.run_paradigma`, and explore the returned tables and plots. Processing runs in a background thread. Data stays on your machine; the application does not upload recordings.

## Run on Windows

Install 64-bit Python 3.12 and Git, then run these commands in PowerShell from this repository. Git installs the pinned official Open Movement reader revision:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2,<27"
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\paradigma-desktop.exe
```

## Build a Windows executable

Run on Windows from the repository directory:

```powershell
.\.venv\Scripts\python.exe scripts/build_desktop.py
.\.venv\Scripts\python.exe scripts/check_frozen.py dist/ParaDigMaDesktop/ParaDigMaDesktop.exe
```

Launch `dist\ParaDigMaDesktop\ParaDigMaDesktop.exe`. Distribute the **entire ParaDigMaDesktop folder**, including `_internal`; the executable depends on it. This is an unsigned portable application, not an installer. The build explicitly includes scikit-learn's native runtime libraries, including Windows `vcomp140.dll` and `msvcp140.dll`. The GitHub Actions Windows desktop workflow runs tests, builds this folder, and launches the packaged executable before uploading an artifact. The executable check loads all four bundled classifiers, extracts real tremor output from synthetic sensor samples, renders a Qt plot and exports results. A Windows binary must be built and tested on Windows; Linux builds cannot generate Windows executables.

Version 0.1.3 fixes `OverflowError: Python integer 65536 out of bounds for uint16` when opening CWA recordings with fractional timestamps. The app pins the official Open Movement reader to commit `087ac7b5a80b866c400d8021b7a2716d247fc034`, which widens timestamp arithmetic for NumPy 2. The older PyPI release also calls itself 0.0.1, so an existing source installation needs this explicit replacement before reinstalling the app:

```powershell
.\.venv\Scripts\python.exe -m pip install --force-reinstall --no-deps "openmovement @ git+https://github.com/digitalinteraction/openmovement-python.git@087ac7b5a80b866c400d8021b7a2716d247fc034"
```

For the downloaded executable, download and extract the entire new successful Windows artifact into a fresh folder. No Python or Git installation is needed to run it. The packaged executable check now also loads the official CWA recording, runs gait analysis and renders its output plot.

## Open and analyze a recording

1. Open a CSV, Parquet, trusted pickle (`.pkl`/`.pickle`), TSDF `*_meta.json`, Empatica `.avro`, or Axivity `.cwa` file. Keep TSDF binary companions beside the JSON metadata. These formats use the toolbox's own loaders. Selecting one file does not analyze unrelated files in its directory.
2. Select the pipeline, watch side, input units, numeric time representation, and device axis orientation. Defaults are relative seconds, acceleration in g, gyroscope in deg/s, and x/y/z orientation. **These defaults may not match your recording.** Signed axes such as `-y,x,z` are supported. Use the column mapping JSON field for alternate channel names: `{"timestamp": "time", "gyr_x": "gyroscope_x", "ppg": "green"}`. Map all required channels.
3. Keep preparation enabled for raw data. Only select “Already prepared” for data already converted to ParaDigMa's units, orientation and sampling requirements. Conversion controls are disabled in prepared mode; column mapping still applies. Optionally split recordings at gaps using the defaults of 1.5 seconds for the gap and minimum segment duration. Segments run independently, and multi-segment output includes `file_key` identifiers such as `segment_1` and `segment_2`.
4. Run ParaDigMa. The processing log displays pipeline progress. Returned processing errors are reported explicitly; partial results remain available for inspection.
5. Choose a result dataset and numeric X/Y columns to plot. The plot toolbar supports zoom, pan and saving the figure. Tables and exports retain every row; plots sample recordings longer than 20,000 rows for responsiveness. Gait filtered/unfiltered results are kept separate.
6. Export the selected table as CSV, or all results with source/version/settings as JSON.

Required channels:

| Pipeline | Columns |
| --- | --- |
| Tremor | `time`, `gyroscope_x`, `gyroscope_y`, `gyroscope_z` |
| Gait | Tremor columns plus `accelerometer_x`, `accelerometer_y`, `accelerometer_z` |
| Pulse rate | `time`, `green` (accelerometer optional) |

Default toolbox diagnostic files use a unique temporary directory and are deleted after analysis; the processing log remains visible in the application. CSV exports neutralize formula-like text, while JSON preserves original text. Exports cannot overwrite the currently loaded sensor file.

The wrapper performs preparation explicitly with the official ParaDigMa functions before calling `run_paradigma` with prepared data. This ensures that selected acceleration units and orientation apply to each pipeline, avoids missing gap defaults in ParaDigMa 1.1.2, and prevents preprocessing from interpolating between separate recordings. Logged tremor/pulse-rate failures omitted from the toolbox's returned error list are added to the wrapper's result errors. Empty quantified output remains distinct from a processing failure.

The wrapper requires numeric, finite sensor samples and increasing timestamps, except when using difference-based time. CSV date strings need conversion to one of the supported numeric time units before import. Pulse rate runs separately from gait/tremor. In ParaDigMa 1.1.2, raw PPG preparation also requires accelerometer channels; PPG-only input must already be prepared. Sensor rate, recording duration, device compatibility and scientific interpretation remain governed by the [official toolbox documentation](https://biomarkersparkinson.github.io/paradigma/). Not every file with a supported extension necessarily contains compatible sensor data. Pickle files can execute code; open only files from trusted sources.

## Development and validation

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade 'pip>=26.2,<27'
.venv/bin/python -m pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/paradigma-mpl .venv/bin/python -m pytest -q
.venv/bin/paradigma-desktop
```

Tests exercise CSV/Parquet/pickle loading, the official Axivity CWA example (36,400 samples) and its gait output, real tremor, gait and pulse-rate pipeline execution, including tremor preparation and export, invalid input handling, nested gait result traversal, Qt result rendering/plotting, and background-worker error delivery. Fractional CWA timestamp checks cover large fractions and negative offsets at 100 and 3,200 Hz. Synthetic gait input can yield no detected gait bouts, and the pulse-rate quality classifier rejects the synthetic sine signal (no estimates); physiological pulse-rate output still requires representative recordings. Device-specific Avro/TSDF loading uses upstream implementations; representative recordings are needed to validate those devices. A Windows CI build is provided but must run before claiming Windows packaging has been verified. The bundled public CWA fixture and its license/provenance are in `src/paradigma_desktop/data/`.

On the CWA example, ParaDigMa 1.1.2 returns tremor window measurements but can report an aggregation error (`dataset input should have multiple elements`) when too few detected tremor windows are available for its modal statistic. The application retains the window results and reports this upstream limitation; the CWA import fix does not change scientific aggregation rules.

Regression checks also cover mapped/prepared numeric text, short-recording failures, separate gap segments at different sensor rates, units/orientation, custom time indexes, missing samples, numeric plot column names, background UI recovery, JSON float precision, and protecting TSDF companion binaries during export.

## Security

See [SECURITY.md](SECURITY.md) for the review findings, dependency-audit exception, remaining risks, and a Windows Sandbox configuration for a first run. Use a normal user account without administrator elevation. Pickle import requires explicit trust confirmation; prefer CSV/Parquet for exchanged recordings.

Windows builds audit installed Python dependencies and include package versions, the source commit, the audit report and `SHA256SUMS.txt` in the artifact. These checks do not constitute a security guarantee or a digital signature.
