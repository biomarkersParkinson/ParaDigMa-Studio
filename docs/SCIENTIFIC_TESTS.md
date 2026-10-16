# Scientific equivalence tests

`tests/test_scientific_equivalence.py` and `tests/test_parallel_scientific.py`
compare the wrapper with an independent official ParaDigMa 1.1.2 workflow using
identical inputs and settings. These regression and integration tests check
wrapper equivalence; they do not establish clinical accuracy or validate new
scientific algorithms.

## Basis in the official automated tests

The reference is the official [ParaDigMa test suite at commit
4735d6d](https://github.com/biomarkersParkinson/paradigma/tree/4735d6d21b2a62b764a0bc7e0f677577e6ce1668/tests):

| Upstream basis | Desktop coverage |
| --- | --- |
| `test_gait_analysis.py`, `test_tremor_analysis.py`, `test_pulse_rate_analysis.py`: synthetic pipeline/orchestrator checks | Adapted signals with a fixed random seed, executed through both the app and a direct official workflow |
| `test_prepare_data.py`: units, preparation and interrupted recordings | Numeric comparisons after mapping, g/m/s² and deg/s/rad/s conversion, signed axis permutation and all six supported numeric time encodings |
| `conftest.py` and stored TSDF fixtures: reference comparisons | Recorded IMU/PPG inputs decoded from `tests/data/1.prepared_data`; comparison of intermediate signals, features, classifications and derived outputs |
| `test_orchestrator.py` and gait tests: orchestration and multiple input frames | Gait + tremor, all three modules via independent IMU/PPG calls, both watch sides, filtered/unfiltered branches, independent sections, identifiers, segment timing metadata and aggregation |

The app's existing public Axivity CWA and Physilog Parquet fixtures add raw-import
and missing-sample coverage. Source attribution, selections and checksums are in
[`tests/data/paradigma/README.md`](../tests/data/paradigma/README.md) and the bundled
example recordings' provenance file.

## Independent reference workflow

The expected path calls the official `prepare_raw_data`,
`correct_watch_orientation` and `run_paradigma` functions directly. It does not
call the desktop analysis or preparation helpers to generate expected outputs.
The actual path calls the real desktop `analyze` function. Both paths receive
fresh configuration objects because upstream preprocessing updates sampling
frequency settings during a run. Inputs must remain unchanged.

TSDF import tests use real binary streams and an independent reference multiplication
of each channel by its metadata `scale_factors`, following the
[TSDF pandas tutorial](https://biomarkersparkinson.github.io/tsdf/basic_reading_and_writing_pandas.html).
ParaDigMa 1.1.2's loader returns unscaled stored values; its preparation converts
units but does not decode these scale factors. Studio decodes them before display
and preparation. Tests compare every real tremor stage and output with a directly
scaled official workflow, with preparation both enabled and skipped, and verify
that Data graphs show the physical values and source files remain unchanged.

For missing data, the Physilog reference uses independently known source row
intervals: missing gyroscope samples are rows `[2000,2010)`, and time gaps occur
at rows 6010 and 8010. Each retained interval is passed to the official
orchestrator as a separate frame. A 30-second minimum-duration case independently
omits the two 20-second sections. The difference-time case reconstructs elapsed
time before excluding sensor rows. This avoids using the app's own boundary
detection to construct its expected output.

The direct orchestrator runs with explicit prepared inputs because its 1.1.2 raw
preparation has known parameter-forwarding limitations documented in the
[user guide](USER_GUIDE.md#input-and-analysis-settings).
Comparing a raw default orchestrator call with the app's explicit missing-sample
exclusion, unit conversion or independent gap processing would compare different
workflows.

ParaDigMa 1.1.2 does not forward classification tables from its pipelines into the
final orchestrator result, and its gait pipeline does not return its merged
classification labels. Test observers therefore record real stage inputs and
outputs, including quantification inputs containing those labels. Observers call
the original functions and return their results unchanged; they do not replace
models, probabilities or signal processing. Both paths must actually execute
the scientific stages and finish without processing errors.

Both workflows now also request the official classification exports. The desktop
retains those files in its results, and the independent reference reads its own
files to compare every classification value, timestamp, column and section key.
Saving classifications changes output retention, not the pipeline's computations.

## Assertions and tolerances

Comparisons cover:

- Prepared inputs, resampled/filtered signals and extracted features.
- Classification probabilities and discrete labels, including gait filtering.
- All quantification rows/columns, both gait branches and tremor power.
- Every returned official aggregation and scientific metadata value.
- Exact row counts, order, column names, timestamps and missing-value masks.
- Real-result Qt zoom, scientific table values and plotted measurements, plus
  independently derived gait display positions and unchanged official aggregate cards.
- Checked-tremor interval starts at exactly the positive official timestamps,
  extending at the official output update cadence without joining recording gaps; plotted
  counts and checked/resting-window ratios reconcile with the official percentage.
  Tremor overview rounding is display-only; arm-at-rest percentage agrees with
  the independent official resting/total window counts.
  Raw classification/quantification tables preserve all original columns; aggregate
  tables retain full-run values when the detailed time selection changes or users switch module tabs.
- Gait display-only window indicators match the saved probabilities compared with
  each bundled model's threshold, including equality at the threshold and missing
  values. Filtered-positive display intervals are independently intersected with
  threshold-positive detected gait in the recorded fixtures. Recorded-output
  plots, zoom and clicks preserve the raw tables.
  These indicators are distinct from the pipeline's merged sample-level labels.
- JSON export/reopening and CSV exports, including missing tremor measurements.

Discrete labels, identifiers and time columns must match exactly. Other floating
values use `rtol=1e-10`, `atol=1e-12`; NaNs must occur at the same locations. This
is intentionally tighter than upstream's historical `rtol=1e-5`, `atol=1e-6`
stored-reference helper because both sides execute the same pinned library in
one process. No length differences, reordered records or overlapping prefixes
are accepted. Numeric dtypes may differ without changing values, for example
when validated integer sensor channels become floats in the app.

JSON converts non-finite scalars to null and dictionary keys to strings, as
documented by the export format. Comparisons account for that representation
while checking the restored scientific values. CSV is read with pandas'
`float_precision="round_trip"` to avoid parser rounding.

The wrapper adds missing-sample provenance under
`metadata.desktop_preparation`. It is checked separately against the known
excluded sample count, analyzed sample count and section count. Recording identifiers
and prepared-input coverage are also desktop metadata, tested separately from official
scientific metadata. Coverage is checked against the exact prepared frames received
by the orchestrator, including missing rows and discarded short sections. Complete
JSON round trips check both scientific and desktop metadata. Overview retains official
aggregates regardless of plot zoom. Gait-segment summaries and display-only
time estimates do not modify the scientific tables.

The combined three-module test compares every scientific stage, classification,
quantification, aggregate and metadata value against two independent official
workflows. Additional UI tests check absolute-time alignment when IMU and PPG
missing-sample exclusions create different analysis origins, including JSON reopening.

Multiple recordings of one subject are also compared against a direct official
dictionary-of-recordings workflow. The recorded IMU cases have unequal lengths;
classifications, both gait branches, unique gait-segment metadata and pooled
tremor aggregates must match. UI tests cover original-file inspection, shared
settings, per-file dates, shared plot limits, source-correct sensor context, JSON
reopening, file-order fallbacks and protection of all source files during export.

## Positive and empty-output cases

The recorded IMU tests require actual gait measurements and multiple positive
tremor windows with finite power, plus nonempty aggregations. The right-watch
case also requires nonempty filtered gait measurements and aggregations.
Empty synthetic gait or default pulse-rate output is allowed where the official
pipeline produces it, rather than being mistaken for evidence of positive
scientific output.

The recorded PPG fixture yields no estimates with ParaDigMa's default
configuration. That behavior and all its quality probabilities are compared.
A separate positive-output case passes the official
`PulseRateConfig(ppg_sampling_frequency=100, min_window_length_s=10)` to both
paths, matching the preprocessed rate and selecting an explicit 10-second
minimum estimation window. It requires finite pulse-rate estimates and
aggregations without bypassing quality classification or changing its threshold.
This exercises the wrapper's configuration API; it does not change the GUI
defaults or imply that the same recording produces estimates in the default GUI.

## Running and maintaining the tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -m scientific -q
```

The normal `python -m pytest` command also includes these tests. Both Windows
build workflows run them before packaging and publish JUnit and coverage reports
in `ParaDigMaStudio-test-results`, including reports from failed tests.
The committed fixtures make the suite self-contained: no upstream checkout,
fixture download or patient recording is required. Install `.[dev]` for the
[CI coverage check](DEVELOPMENT.md#branch-coverage).

The [test suite guide](TEST_SUITE.md) describes the feature-based organization
and shared UI helpers. The scientific cases, their independent references and
numerical tolerances are maintained separately from the
[historical test cleanup](archive/test-suite-cleanup.md).

These are comparisons with a live independent reference workflow, not frozen
golden outputs. They detect wrapper differences from the installed official
version, but cannot detect a change that affects both paths identically.
The fixture manifest requires ParaDigMa 1.1.2; upgrading the toolbox requires
explicit review of these references and settings. They cover representative
recordings and supported preparation choices, not every device or recording.

Presentation tests cover aligned multi-module bar charts, midnight and daylight-saving
transitions, named timezones in exported provenance, classifications/quantifications,
bar clicks and clearly labeled gait estimates. Original values and missingness are
checked against the official output; no lines interpolate across missing estimates.
Estimated gait positions stay within their official segments and are never inserted
into scientific result tables. Plot zoom leaves the complete raw tables unchanged.
Daily presentation tests independently check the 864-second valid-data minimum
per metric, zero predictions, missing values, overlapping intervals, recording gaps,
calendar-midnight boundaries and 23/25-hour daylight-saving days. Daily medians and
percentages preserve the original scientific tables and the separate 30-minute
presence rule. Gait metric coverage uses the estimated within-segment support of
finite outcomes; missing swing values contribute no coverage.
Binary tests verify positive spans, actual timestamps, gaps, missing states and
isolated detections. `tests/test_gait_presence.py` checks the common observed-time
percentage denominator, conditional filtering, unequal cadences, gaps and missing
filter predictions, overlapping recordings, and recording/participant isolation.
Filtered gait cannot exceed gait presence in any epoch; unknown time is excluded
from both denominators. Prepared-input availability comes from the exact pipeline inputs.
`test_parallel_scientific.py` compares real spawned recording workers with the
independent official batch workflow, including unequal recorded IMU inputs, both
watch sides, all module groups, missing-sample and difference-time preparation,
gap sections, custom duration categories/statistics, empty gait outcomes and
partial failures. Gait segment IDs and metadata are reconciled in input order;
official aggregation functions consume pooled quantifications. Original samples,
classifications, quantifications, aggregates and metadata must remain equivalent.
The frozen smoke probe forces a small two-worker batch to verify spawned imports
and private transfers in the executable. See the [test suite map](TEST_SUITE.md#regression-coverage-map)
for separate worker-policy, cancellation, security and UI/layout regressions.

Upstream's historical IMU preprocessing reference test is currently skipped
because its stored output needs regeneration. This suite does not copy that
skip, accept outdated outputs, or silently relax comparisons to make them pass;
it executes the current pinned official processing independently on both paths.
