# ParaDigMa Desktop

A native Windows desktop wrapper around the **official ParaDigMa 1.1.2 toolbox**. Open a wrist-sensor recording, select gait, tremor, gait + tremor, or pulse-rate analysis, run `paradigma.orchestrator.run_paradigma`, and explore the returned tables and plots. Processing runs in a background thread. Data stays on your machine; the application does not upload recordings.

## Run on Windows

Install 64-bit Python 3.12, then run these commands in PowerShell from this repository:

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

## Open and analyze a recording

1. Open a CSV, Parquet, trusted pickle (`.pkl`/`.pickle`), TSDF `*_meta.json`, Empatica `.avro`, or Axivity `.cwa` file. Keep TSDF binary companions beside the JSON metadata. These formats use the toolbox's own loaders. Selecting one file does not analyze unrelated files in its directory.
2. Select the pipeline, watch side, input units, numeric time representation, and device axis orientation. Defaults are relative seconds, acceleration in g, gyroscope in deg/s, and x/y/z orientation. **These defaults may not match your recording.** Signed axes such as `-y,x,z` are supported. Use the column mapping JSON field for alternate channel names: `{"timestamp": "time", "gyr_x": "gyroscope_x", "ppg": "green"}`. Map all required channels.
3. Keep preparation enabled for raw data. Only select “Already prepared” for data already converted to ParaDigMa's units, orientation and sampling requirements. Optionally split recordings at gaps using the toolbox defaults.
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

The wrapper requires numeric, finite sensor samples and increasing timestamps, except when using difference-based time. CSV date strings need conversion to one of the supported numeric time units before import. Pulse rate runs separately from gait/tremor. In ParaDigMa 1.1.2, raw PPG preparation also requires accelerometer channels; PPG-only input must already be prepared. Sensor rate, recording duration, device compatibility and scientific interpretation remain governed by the [official toolbox documentation](https://biomarkersparkinson.github.io/paradigma/). Not every file with a supported extension necessarily contains compatible sensor data. Pickle files can execute code; open only files from trusted sources.

## Development and validation

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade 'pip>=26.2,<27'
.venv/bin/python -m pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/paradigma-mpl .venv/bin/python -m pytest -q
.venv/bin/paradigma-desktop
```

Tests exercise CSV/Parquet/pickle loading, real tremor, gait and pulse-rate pipeline execution, including tremor preparation and export, invalid input handling, nested gait result traversal, Qt result rendering/plotting, and background-worker error delivery. Synthetic gait input can yield no detected gait bouts, and the pulse-rate quality classifier rejects the synthetic sine signal (no estimates); physiological gait/pulse-rate output still requires representative real recordings. Device-specific Avro/CWA/TSDF loading uses upstream implementations; representative recordings are needed to validate those devices. A Windows CI build is provided but must run before claiming Windows packaging has been verified.

## Security

See [SECURITY.md](SECURITY.md) for the review findings, dependency-audit exception, remaining risks, and a Windows Sandbox configuration for a first run. Use a normal user account without administrator elevation. Pickle import requires explicit trust confirmation; prefer CSV/Parquet for exchanged recordings.

Windows builds audit installed Python dependencies and include package versions, the source commit, the audit report and `SHA256SUMS.txt` in the artifact. These checks do not constitute a security guarantee or a digital signature.
