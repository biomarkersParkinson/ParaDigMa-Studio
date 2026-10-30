# Scientific equivalence tests

These tests check that Studio preserves the behavior and outputs of **official
ParaDigMa 1.1.2** for the same inputs and settings. They cover preparation,
scientific processing, spawned workers, presentation and exports. They establish
wrapper equivalence, not clinical accuracy or validation of new algorithms.

This guide describes the tests on `main`. Use the [test suite guide](TEST_SUITE.md)
for the broader regression map, shared helpers and coverage policy, and
[Development](DEVELOPMENT.md) for environment setup and complete CI checks.

- [Run the checks](#running-and-maintaining-the-tests)
- [Coverage map](#coverage-map)
- [Upstream basis and fixtures](#basis-in-the-official-automated-tests)
- [Independent reference workflow](#independent-reference-workflow)
- [Assertions and tolerances](#assertions-and-tolerances)
- [Positive and empty-output cases](#positive-and-empty-output-cases)
- [Presentation and export checks](#presentation-and-export-checks)
- [Maintenance and limits](#maintenance-and-limits)

## Running and maintaining the tests

From the repository root, install the locked environment and run the marked
scientific tests. These commands work in PowerShell and Bash:

```sh
uv sync --locked --all-groups
uv run --locked --all-groups python -m pytest -m scientific -q
```

The tests configure offscreen Qt and its virtual screen as described in
[Test setup](TEST_SUITE.md#test-setup-and-scientific-checks). For headless Linux
with an explicit writable Matplotlib cache:

```bash
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/paradigma-mpl uv run --locked --all-groups python -m pytest -m scientific -q
```

To inspect the current selection without running analyses:

```sh
uv run --locked --all-groups python -m pytest -m scientific --collect-only -q
```

The normal full suite includes these tests and the related presentation,
validation and lifecycle regressions below. Both
[Windows](../.github/workflows/windows.yml) and
[signed Windows](../.github/workflows/windows-signed.yml) workflows run the full
suite before packaging. JUnit and coverage reports are retained in
`ParaDigMaStudio-test-results`, including available reports when tests fail.
See [branch coverage](TEST_SUITE.md#branch-coverage) for the measured scope and
report paths.

## Coverage map

The `scientific` marker selects the following groups. Some compare directly
with official ParaDigMa; others check that an execution feature preserves
Studio's already-tested sequential behavior.

| Test module | Comparison and purpose |
| --- | --- |
| [test_scientific_equivalence.py](../tests/test_scientific_equivalence.py) | Independent official workflows for synthetic and recorded inputs, preparation, intermediate stages, classifications, quantifications, aggregates and metadata; real-result plots and exports |
| [test_column_mapping.py](../tests/test_column_mapping.py) — marked case | GUI-selected columns, axis swaps and independent sensor inversions against official preparation and real gait, tremor and pulse processing |
| [test_pulse_input.py](../tests/test_pulse_input.py) — marked case | Raw PPG-only inputs, mapped numeric text and all six numeric time encodings against an independent official workflow |
| [test_parallel_scientific.py](../tests/test_parallel_scientific.py) | Real spawned workers against official recorded batch workflows and sequential Studio results, including preparation, empty outputs and partial failures |
| [test_analysis_progress.py](../tests/test_analysis_progress.py) — marked case | Real processing with and without progress reporting must return equivalent results and preserve source samples |

Other cases in these modules and the [presentation and export checks](#presentation-and-export-checks)
run with the full suite; the marker does not select every test related to
scientific data. Worker selection, cancellation, security and UI/layout checks
are mapped separately in the [regression coverage map](TEST_SUITE.md#regression-coverage-map).

## Basis in the official automated tests

### Upstream reference

The reference is the official [ParaDigMa test suite at commit
4735d6d](https://github.com/biomarkersParkinson/paradigma/tree/4735d6d21b2a62b764a0bc7e0f677577e6ce1668/tests).

| Upstream basis | Studio coverage |
| --- | --- |
| Gait, tremor and pulse-rate pipeline tests | Adapted synthetic signals with a fixed random seed, run through Studio and a direct official workflow |
| Preparation tests | Column mapping, g/m/s² and deg/s/rad/s conversions, signed axis permutations, missing samples, interrupted recordings and all six numeric time encodings |
| Stored TSDF fixtures and reference helpers | Recorded IMU/PPG comparisons across intermediate signals, features, classifications and derived outputs |
| Orchestrator and gait batch tests | Both watch sides, filtered/unfiltered gait, independent sections, recording identifiers, segment timing metadata and pooled aggregation; all three modules through separate IMU/PPG calls |

At that upstream revision, the historical IMU preprocessing reference test is
skipped because its stored output needs regeneration. Studio instead executes
the pinned official processing independently on both paths.

### Committed fixtures

The suite needs no upstream checkout, fixture download or private recording.

| Input | Selection and role | Provenance |
| --- | --- | --- |
| Recorded IMU | All 72,947 upstream prepared rows; real gait and tremor output, both watch sides and unequal-length recording batches | [Fixture README](../tests/data/paradigma/README.md) and [manifest](../tests/data/paradigma/manifest.json) |
| Recorded PPG | First 18,000 upstream prepared rows; quality classification, default empty estimates and explicitly configured positive estimates | Same fixture README and manifest |
| Public Axivity CWA | Raw-import, preparation and gait comparisons | [Bundled recording provenance](../src/paradigma_studio/data/README.txt) |
| Public Physilog excerpt | Missing samples, known recording gaps and minimum-section rules | Same bundled recording provenance |
| Generated TSDF streams | Real binary time/value streams with explicit scale factors, written independently of Studio's decoder | [Shared fixture writer](../tests/conftest.py) and [TSDF tests](../tests/test_tsdf_input.py) |

The upstream IMU/PPG binaries were decoded to compressed Parquet without changing
the selected channel values or timestamps. The manifest records the source
revision, source hashes, selections and converted-file hashes. Tests verify the
installed ParaDigMa version, committed Parquet hashes and row counts. These two
fixtures are source-test data and are not bundled in the app. Attribution,
licensing and conversion instructions remain in the fixture README.

## Independent reference workflow

### Separate official and Studio paths

The expected path calls official `prepare_raw_data`,
`correct_watch_orientation` and `run_paradigma` functions directly. It does not
use Studio's analysis or preparation helpers to generate expected outputs.
The actual path calls Studio's real `core.analyze` function.

Each path receives fresh configuration objects because upstream preprocessing
updates sampling-frequency settings during a run. The comparison also verifies
that source frames remain unchanged.

The official orchestrator receives explicitly prepared frames with
`skip_preparation=True` and `split_by_gaps=False`. This avoids its 1.1.2
parameter-forwarding limitations and ensures that both paths process the same
prepared samples and sections. A default raw orchestrator call would not apply
Studio's selected missing-sample, unit and gap policies equivalently. See the
[preparation contract](PYTHON_API.md#python-service-apis).

### Preparation references

| Case | How the expected input is constructed independently |
| --- | --- |
| Signal columns and axes | Explicit source renaming and official orientation calls for each sensor; manual GUI choices must override standard-name decoy columns |
| TSDF scaling | Multiply each decoded channel by its metadata scale factor, following the [TSDF pandas tutorial](https://biomarkersparkinson.github.io/tsdf/basic_reading_and_writing_pandas.html) |
| Physilog missing samples and gaps | Use known source-row intervals rather than Studio's boundary detection |
| PPG-only inputs | Convert mapped text to numbers and use official time preparation before the unchanged pulse pipeline; no accelerometer channels are synthesized |

ParaDigMa 1.1.2's TSDF loader returns stored values; its unit preparation does
not decode metadata scale factors. Studio decodes those factors before display
and preparation. Tests compare every real tremor stage with the independently
scaled reference, with preparation enabled and bypassed, guarding against
double scaling. Related import tests check displayed physical values and
unchanged source files.

For Physilog, missing gyroscope rows are `[2000, 2010)`, and time gaps occur at
rows 6010 and 8010. Each retained interval enters the official orchestrator as
a separate frame. A 30-second minimum independently excludes the two 20-second
sections. Difference-time inputs reconstruct elapsed time before sensor-row
exclusion, preserving the original clock.

Related [GUI preparation tests](../tests/test_analysis_preparation.py) inspect
the orchestrator boundary: native-unit inputs match exactly, converted units
and independent inversions match numerically, and selected gap/duration rules
are honored. They stub the orchestration boundary rather than running pipelines;
the marked comparisons above exercise real scientific processing. GUI runs
always use normal preparation. Saved-setting checks reject retired global axis
permutations and GUI preparation bypass without changing current fields; the
Python API's explicit bypass remains covered separately.

### Intermediate stages and classification retention

ParaDigMa 1.1.2 does not forward pipeline classification tables into its final
orchestrator result, and its gait pipeline does not return merged sample-level
classification labels. Test observers record real stage inputs and outputs,
including quantification inputs containing those labels. Each observer calls
the original function and returns its output unchanged. Models, probabilities
and signal processing execute normally.

Both paths also request official classification exports. Studio retains those
files in its results; the reference independently reads its own files. The
comparison checks values, timestamps, columns and section identifiers. Retaining
classifications changes output retention, not scientific computations.

Successful reference comparisons require both workflows to finish without
processing errors and the scientific stages to execute. Matching failures or
unexecuted stages do not count as equivalence.

### Multiple recordings and spawned workers

Recorded batch comparisons use the official dictionary-of-recordings workflow,
including unequal IMU lengths. They check classifications, both gait branches,
unique segment identifiers, segment metadata and pooled tremor aggregates.
Combined-module cases compare Studio with separate official IMU and PPG runs.

Spawned-worker tests compare recorded IMU batches and custom gait duration
categories/statistics with that official reference. Other cases compare spawned
and sequential Studio results for difference-time preparation, missing samples,
gap sections, all module groups, empty gait outcomes and partial failures.
These checks protect execution and merging semantics; they do not construct
an additional independent preparation reference for every worker case.

Gait identifiers and metadata must reconcile in input order, and official
aggregation functions consume pooled quantifications. The
[packaged smoke probe](../src/paradigma_studio/smoke.py) additionally forces a
small two-worker batch to verify spawned imports and private transfers in the
executable.

## Assertions and tolerances

The shared `assert_equivalent` helper in
[test_scientific_equivalence.py](../tests/test_scientific_equivalence.py) compares
the full result tree and observed stages.

| Compared data | Requirement |
| --- | --- |
| Structure | Matching keys, array shapes, table row counts, index/order and column names; no prefix-only comparisons |
| Discrete values | Exact labels, identifiers and table `time` columns |
| Other floating values | `rtol=1e-10`, `atol=1e-12` |
| Missing values | Identical missing-value masks; NaNs at the same locations |
| Numeric dtypes | May differ when values remain equivalent, such as integer sensor channels converted to floats |
| Source inputs | Remain unchanged after processing |

These tolerances are tighter than upstream's historical stored-reference helper
(`rtol=1e-5`, `atol=1e-6`): the comparisons execute the same pinned library and
numerical stack. They cover prepared inputs, resampled/filtered signals,
features, probabilities, labels, every quantification row and column, both gait
branches, tremor power, returned aggregates and official scientific metadata.

Studio-specific metadata is checked separately:

- **`desktop_preparation`:** known excluded/analyzed sample and section counts.
- **`desktop_recordings`:** recording identities and section ownership.
- **`desktop_availability`:** coverage from the exact prepared frames handed to
  the orchestrator, including missing rows and discarded short sections.

Complete JSON round trips check both official and Studio metadata. JSON converts
non-finite scalars to null and dictionary keys to strings; comparisons account
for that representation while checking restored values. CSV comparisons use
pandas' `float_precision="round_trip"` to avoid parser rounding. The persistence
contract is documented under [saved-run formats](PYTHON_API.md#saved-run-contract).

Plot-coordinate tolerances are separate from scientific-value comparisons.
Calendar-axis checks use absolute tolerances with zero relative tolerance;
see the [test suite conventions](TEST_SUITE.md#regression-coverage-map).

## Positive and empty-output cases

An empty official result can be correct. Positive-output cases are required
separately so agreement on empty tables cannot mask a broken processing path.

| Case | Required official outcome |
| --- | --- |
| Recorded IMU, both watch sides | Actual unfiltered gait measurements, multiple checked tremor windows with finite power, and nonempty aggregates |
| Recorded IMU, right watch | Nonempty filtered gait measurements and aggregates as well |
| Synthetic inputs | Empty gait or default pulse estimates are accepted when the official pipeline produces them |
| Recorded PPG, default configuration | No pulse estimates or aggregates; quality probabilities still compared |
| Recorded PPG, explicit configuration | Finite pulse estimates and nonempty aggregates, with quality classification and its threshold unchanged |

The positive PPG case passes
`PulseRateConfig(ppg_sampling_frequency=100, min_window_length_s=10)` to both
paths. It matches the preprocessed rate and explicitly chooses a 10-second
minimum estimation window. This tests Python configuration support; it does not
change GUI defaults or imply that the fixture produces estimates in the default GUI.

Raw PPG-only comparisons use that positive configuration across all six numeric
time encodings and mapped text columns. They check each real pulse stage,
quality probability, estimate and aggregate. Studio validates required PPG/time
values before official preparation, disabling its IMU-specific generic validator
when no complete IMU stream is present. Additional tests preserve source-clock
alignment and enforce gait/tremor IMU requirements.

## Presentation and export checks

Real official results anchor plot, table and export checks in the marked suite.
Related tests use small constructed cases to check presentation boundaries.
Display estimates and summaries must preserve the original scientific tables
and full-run official aggregates.

| Area | Protected behavior and related tests |
| --- | --- |
| Detailed graphs and Overview | Correct measured values, checked-tremor intervals/cadence and gaps; tremor percentage matches checked/resting-window counts, and arm-at-rest percentage matches resting/total counts. Rounding is display-only. [Results view](../tests/test_results_view.py), [gait overview](../tests/test_gait_overview.py) |
| Gait window indicators | Saved probabilities compared with bundled model thresholds, including equality and missing values; filtered-positive spans intersect detected gait. These display indicators differ from merged sample-level pipeline labels. [Graph workspace](../tests/test_graph_workspace.py), [gait presence](../tests/test_gait_presence.py) |
| Clocks and recording alignment | IMU/PPG origins after independent missing-row exclusion, per-file dates, midnight, daylight-saving transitions and named timezone provenance survive reopening; unknown/incomparable clocks use explicit file order. [Results view](../tests/test_results_view.py), [recordings](../tests/test_recordings.py) |
| Navigation and tables | Zoom, clicks, selections and module switches preserve raw classification/quantification columns and full-run aggregates; estimated gait positions remain within their official segments. [Results view](../tests/test_results_view.py), [result navigation](../tests/test_result_navigation.py) |
| Binary and epoch summaries | Correct positive spans, actual timestamps, isolated detections, gaps, missing states and separate 30-minute presence rules. [Epochs](../tests/test_epochs.py), [presence thresholds](../tests/test_epoch_presence_threshold.py) |
| Daily summaries | Per-metric 864-second valid-data minimum, medians/percentages, zero predictions, overlaps, missing values, gaps, local midnight and 23/25-hour days. Finite estimated gait support determines coverage; missing swing values add none. [Daily tests](../tests/test_daily.py) |
| Exports and sensor context | JSON reopening and CSV values retain missing measurements; context uses the correct original recording, shared limits and settings, with every source file protected during export. [Result exports](../tests/test_result_exports.py), [recordings](../tests/test_recordings.py) |

Gait presence and filtered gait share an observed-time denominator. Tests cover
unequal cadences, missing filter predictions, overlapping recordings and
recording/participant isolation. Filtered gait cannot exceed gait presence in
an epoch; unknown time contributes to neither denominator. Prepared-input
availability comes from the exact pipeline inputs.

Presentation checks also require aligned multi-module bars, missing-estimate
gaps without interpolation, and clearly labeled gait time estimates. Those
estimates are never inserted into scientific result tables.

## Maintenance and limits

When preparation, processing, dependencies or result handling change:

1. Run the relevant feature tests and marked scientific comparisons. Use the
   full suite for the related presentation and boundary cases, and the
   [packaged executable check](DEVELOPMENT.md#build-and-verify-a-windows-executable)
   for packaging changes.
2. Investigate the first differing stage, including settings, source selection,
   units, clocks, retained rows and section identities. Keep expected inputs
   independent of the Studio logic being tested.
3. For a ParaDigMa upgrade, explicitly review reference calls, mutable
   configuration defaults, retained outputs and fixture version expectations.
   Follow the [dependency update procedure](DEPENDENCIES.md#update-deliberately).
4. Review any intentional fixture replacement against decoded source values
   before updating hashes. Parquet bytes can vary with writer versions; the
   fixture README documents conversion and provenance requirements.
5. Report the tested commit and relevant results. Do not relax comparisons,
   copy upstream skips or accept stale outputs to make a failure pass.

These are comparisons against a live reference, not frozen golden outputs.
They detect Studio differences from the installed official library, but cannot
detect a change that affects both paths identically. The manifest enforces
ParaDigMa 1.1.2; an upgrade therefore requires deliberate review. The fixtures
cover representative recordings and preparation choices, not every device or
recording.

Current conventions belong in this guide and the [test suite guide](TEST_SUITE.md).
The [historical test cleanup](archive/test-suite-cleanup.md) retains evidence and
decisions for its own revision.
