# Changelog

## Unreleased

- Keep Analyze's Time origin editable during clock refreshes. Derive clock-only
  previews without result alignment, reuse equivalent module selections and avoid
  copying full sensor matrices to check missing samples.
- Keep Results Y axes in a fixed column when changing the selected graphs.
- Open every Results graph view at its full time range, with the horizontal
  scrollbar hidden until zooming in; keep zoom when toggling series in that view.
- Speed up Results horizontal scrolling with peak-preserving previews and reused
  axis geometry; restore full graph detail when scrolling stops.
- Make Results interval shading follow the pointer without redrawing graph data.
  Allow selection to start between graphs and use a time-interval icon and label.
- Bound Results zoom to the full time range, hide the time scrollbar at full range,
  support horizontal trackpad gestures, shade drag selections continuously across
  graphs and their gaps, and add Zoom in/out buttons. Fit the first date without
  relocating later labels.
- Replace Results panning with a shared horizontal time scrollbar and restrict
  Results zoom selections to time; retain raw-data pan and zoom controls.
- Share the grouped date/time axis between Detailed and 30-minute graphs, retaining
  spaced midnight labels on multi-day ranges and precise times when zoomed in.
- Explain worker selection in the processing log, including detected CPU count,
  available RAM, recording-memory estimates and single-worker fallback reasons.
- Keep pandas and pyarrow deferred while opening the empty workspace, Runs and
  empty graph views; inspect sensor-context row values only when a row exists.
- Add a 24-hour profile averaging valid 30-minute summaries at each time of day
  across recordings' days. Give each day equal weight, retain existing presence
  thresholds, exclude missing epochs and preserve the recording timezone.
- Make days recognizable in 30-minute graphs with continuous midnight separators
  across plots and their gaps, and clock times above centered dates. Preserve
  the recording's timezone and existing bars.
  Keep ISO date/time limits working with the grouped date axes in every view.
- Center date labels beneath each day in Day graphs, adapting their spacing to
  the available width and zoom; retain the existing bars and background.
- Reduce raw-input loading overhead by reusing missing-value counts and avoiding
  redundant statistics/scaling arrays. Preserve exact samples and statistics;
  initial loading still completes every statistic before displaying recordings.
- Process multiple recordings in up to two reusable, CPU/RAM-limited workers.
  Preserve the official pipelines and pooled aggregates; single recordings,
  including their gap sections, still use one worker. Stop cleans up all workers.
- Automatically scale percentage graphs in 30-minute and Day views to the
  visible bars, with manual limits and Reset limits available as before.
- Order run-detail tabs as Recordings, Parameters, Warnings, Errors,
  Processing log, Saved run and Exports.
- Add Day graphs: calendar-day percentages and medians, requiring 864 seconds
  of valid data for each metric; preserve the existing 30-minute presence rules.
- Move the Runs filename list into a dedicated Recordings detail tab.
- Reconstruct elapsed seconds in Data graphs when `difference_s` or
  `difference_ms` is selected, and refresh the plot when its time format changes.
- Apply TSDF metadata `scale_factors` once during import, consistently for Data
  plots, sensor context and analysis. ParaDigMa 1.1.2's loader and preparation do
  not apply this decoding. Re-run analyses of TSDF inputs with non-unit factors
  created using earlier builds; existing saved results are not recalculated.

## 0.6.0a1 — 2026-10-13

First public preview of **ParaDigMa Studio**, a Windows workspace around the
official ParaDigMa 1.1.2 toolbox, for evaluation and feedback.

### Included

- Data, Analyze, Results and Runs workspaces; inspect sensor channels and recording quality.
- Gait, tremor and pulse-rate analysis, including combinations of all three modules,
  multiple recordings of the same subject, and cancellation.
- Aggregate summaries and linked graphs/tables across recording time. Detailed
  tremor-power graphs use `log10(power + 1)`; 30-minute epochs use the median of
  transformed power. Raw scientific tables and data exports retain original values.
- Sensor-context inspection, local saved runs, configurable JSON/CSV exports,
  figure exports at 600 DPI, and run management.
- Scientific-equivalence tests against official ParaDigMa workflows, Windows
  executable smoke checks, dependency auditing and packaged build provenance.
- Apache 2.0 licensing, ParaDigMa acknowledgements and research citations.

### Download and run

Download **ParaDigMaStudio-0.6.0a1-Windows-x64.zip**, extract the entire ZIP,
and open `ParaDigMaStudio/ParaDigMaStudio.exe`. Keep `_internal` and all accompanying
files beside the executable. **Python does not need to be installed.**

The separate `ParaDigMaStudio-0.6.0a1-SHA256SUMS.txt` verifies the ZIP's checksum.
The bundle also contains per-file checksums, the source commit, package versions
and the dependency-audit report. Checksums are not publisher signatures.

### Preview limitations

- This Windows x64 build is **unsigned**. Smart App Control may block it;
  publisher signing requires a verified signing identity. Keep Windows protections enabled.
- The tests cover representative recordings and workflows; evaluate results with
  your own data and consult the official methodology before research use.
- No analysis methods are newly introduced by Studio. ParaDigMa remains the source
  of the scientific processing; graph transformations and epoch summaries are presentation views.

[Getting started](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v0.6.0a1/README.md)
· [User guide](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v0.6.0a1/docs/USER_GUIDE.md)
· [Scientific checks](https://github.com/biomarkersParkinson/ParaDigMa-Studio/blob/v0.6.0a1/docs/SCIENTIFIC_TESTS.md)
· [Report an issue](https://github.com/biomarkersParkinson/ParaDigMa-Studio/issues)

For research, cite ParaDigMa's [2026 JOSS paper](https://doi.org/10.21105/joss.09502)
and relevant pipeline publications, as listed in About and the bundled acknowledgements.
