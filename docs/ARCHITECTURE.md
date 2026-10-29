# Application architecture

This guide explains the current source implementation. Start with the
[repository map](REPOSITORY.md) for module locations and
[Development](DEVELOPMENT.md) for setup and coding checks. Service entry points
and the on-disk contract live in the [API reference](PYTHON_API.md).

## Component ownership and lifecycle

`MainWindow` composes the page builders and controllers. Shared state belongs to
`workspace_state.py`; frozen views and explicit callbacks connect components.
Qt parents provide ownership and dialog APIs. Controllers use their declared
state, view and service ports. Graph construction stays deferred until first use.
See the [composition conventions](REPOSITORY.md#conventions-for-changes) for
thread affinity, signal ordering and the internal automation driver.

`ui/result_graphs.py` owns series rendering, axis reuse and viewport restoration.
`ui/result_graph_interactions.py` owns graph clicks, linked table selection,
selection markers and sensor-context availability. Both share the same explicit
view/state objects and `ResultPlotData`, including its existing cache. The renderer
keeps its callback entry points; interaction updates on an empty or unopened graph
must not initialize a canvas.

`ui/results_page.py` owns Results tabs, controls, its deferred result canvas and
frozen workspace/graph views, following the `DataPage`/`AnalysisPage` composition
pattern. `ResultsPageHost` supplies the parent, page layout and shared raw-channel
graph builder/accessor. `WorkspaceLayout` retains page composition and explicit
widget ports; it still builds the shared raw-data/sensor canvases. Constructing
the page or obtaining its views must leave both result and sensor canvases deferred.

`AnalysisPage` owns the info buttons and their non-modal `AnalysisHelpDialog`
windows. Opening one explanation closes the others without changing the form's
layout or scroll range. Dialogs reuse the existing explanation labels so
`FileDefaults` can update value sources while help is open. Long text and the
input-orientation figure scroll inside the window; Close, Escape and the native
close control dismiss it. New input and an accepted application close dismiss
open help; cancelling an application close preserves it. The controller view
exposes these windows for lifecycle cleanup rather than retaining inline-help
layout state or toggle callbacks.

## Preparation and input contracts

`preparation_contracts` defines supported signal names, signed axes, sensor units
and the six numeric time encodings. `PreparationSettings` describes preparation
keywords; the column mapping and missing-sample policy remain explicit `analyze`
arguments. The Analyze controller constructs these settings before adding the
open saved/display metadata. Qt combo values are narrowed at that boundary;
runtime column/axis/timestamp validation still handles external inputs.

`paradigma_api` provides typed lazy adapters for the pinned ParaDigMa 1.1.2 API.
`Unpack` constrains orchestrator and `analyze` keyword names and values without
injecting defaults into forwarded run options. Boundary casts account for
incomplete upstream annotations; they do not validate a recording's actual unit
or orientation. Adapter tests compare the pinned signatures/defaults and check
that supplied objects pass through unchanged. The normal mypy target also includes
`tests/typing/preparation_contracts.py`: valid calls must pass, and invalid units,
axes, signals and keywords must continue producing the expected type errors.
Scientific equivalence tests independently compare real preparation and pipeline
outputs with direct official calls. Raw/prepared frames and result schemas remain
unchanged.

The header-only `column_mapping` model and pure `axis_mapping` service are also
checked; the Qt editor is covered by the recursive UI target. Controllers supply
column-name schemas once per loaded batch and use the editor's explicit
mapping/module APIs and `changed` signal. Mapping validation never scans sensor
samples. Run settings retain the
source-to-target dictionary for the explicit supported signal choices.
Run settings also store `signal_columns`, the complete canonical-signal to
source-column dictionary, with `null` for unassigned signals. These selections are
authoritative for preparation, validation and clock previews: unselected canonical
signal columns cannot supply fallback inputs. Selection metadata is restored
with the rest of the Analyze settings under one signal guard and is not
forwarded to ParaDigMa. Normal editor changes still emit one `changed` signal.
Direct Python API calls without `signal_columns` retain literal renaming
semantics. Original frames remain available for raw-data inspection.
`axis_inversions` stores inverted canonical IMU target channels separately. The
preparation service passes independent signed `x,y,z` lists to the official
accelerometer and gyroscope orientation calls after renaming; permutations belong
only in column mapping. This desktop setting is removed before calling the official
orchestrator. The Python `device_orientation` API remains supported when
`axis_inversions` is absent. Saved GUI settings require explicit selections and
inversions; global permutations and the retired preparation bypass are rejected.
Restoration validates the full settings before changing widgets and installs them
under one signal guard. The editor no longer preserves arbitrary extra mappings,
duplicate targets or redundant identity mapping entries.
Inversion edits do not emit the mapping `changed` signal because they affect
neither clock previews nor original raw plots.

GUI runs always use Studio's normal preparation path with the selected input
conventions. New GUI settings do not contain `skip_preparation`. The Python API
retains that option for explicit callers and their result interpretation.
After Studio prepares inputs, its internal call to the official orchestrator
still sets `skip_preparation=True` to prevent a second preparation pass.

Studio calls official preparation and orientation functions explicitly before
`run_paradigma` with prepared inputs. ParaDigMa 1.1.2's raw orchestrator does not
forward all preparation options; explicit preparation preserves the chosen unit,
axis, missing-sample and gap policies without interpolating across recordings.

## Analyze configuration and shared time

Analyze separates file defaults, derived control state and origin-preview requests.
Its event handlers call the relevant operations directly:

| Event | Updates |
| --- | --- |
| Module selection | Required signals, watch-side relevance, run action and origin preview |
| Time-column edit on either page, other signal selection or Signal columns Default | File unit defaults, sensor-unit availability, origin preview and shared Data diagnostics/plots |
| Time-unit edit on either page or Time units Default | Shared value/provenance and origin preview; Data diagnostics/plots when the value changes |
| Acceleration/gyroscope unit edit or Default | Manual/file provenance; the input clock is unchanged |
| Gap-splitting switch | Availability of gap and minimum-section fields |
| Missing-sample policy | Origin preview |
| Input reset, saved parameters or job completion | One complete `AnalysisController.refresh` |

Input resets and saved-parameter restoration share a guarded settings operation.
It cancels superseded origin requests and blocks widget signals while modules,
units, mappings, policies and origins are installed. Named restoration helpers
apply each group; the controller refreshes once after the guard ends. Pending
preview results still follow the existing generation/key and manual-origin rules.

`AnalysisCallbacks.sync_input` publishes an immutable `TimeConfiguration` after
complete settings are available. It carries the selected source column, unit and
both fields' file/manual provenance. Data edits call the Analyze controller's
normal selection paths; Analyze remains the configuration owner. Both pages use
`FileDefaults.value_source` and `ColumnMappingEditor.value_source` for provenance.
Data applies snapshots under signal blockers so mirroring cannot feed back into
manual-edit handlers. Its last-rendered snapshot detects effective changes even
when a user has already changed the Data widget. Confirming an unchanged value
updates provenance without recomputing sampling statistics.

Data's time-column options match the batch's available signal columns and include
an explicit Not included option. Switching the viewed recording preserves the
shared choice, even if it is absent from that file; diagnostics then remain
unavailable. Cached initial descriptives are reused only for the same source
column and format. Time and sensor previews scan only the inspected recording and
reuse their existing caches. New input resets both pages and applies the new
file defaults through the existing guarded refresh. File-default application
cannot become a manual edit or start intermediate origin previews.

## Graph coordinates, navigation and rendering

`inspection.input_plot_time` converts only display coordinates from the selected
time column. Absolute Unix timestamps become UTC dates, datetime columns retain
their stored time zone, and relative/difference/duration values display in seconds.
Relative values retain their origin; differences include the first increment in
their cumulative sum. Original table values and analysis settings stay unchanged.
Data and Results sensor graphs share `RecordingDateLocator` and
`RecordingTimeFormatter`; the existing graph toolbar uses their date locator to
read and edit calendar limits. Graph exports use the same coordinates and labels.

Raw-channel redraws use `RawToolbar.redraw_channels` to preserve time limits
and manually set value limits across channel changes. Axes have stable sensor-group
labels so a change from one to multiple axes of the same sensor keeps its scale.
The new channels' full view is recorded before restoring the zoom, keeping Home
and Back/Forward usable. Recordings and time-column/format changes reset Data's
view; a new context or display clock resets sensor-context navigation. Source
identity tracking uses weak references so it cannot retain discarded recordings.

`TimeToolbar` and `TimeScroll` share interval-only selection, horizontal hand
dragging, Zoom in/out, scrollbar/trackpad navigation, source bounds and Matplotlib
history across raw graphs and all four Results views. Results-specific
canvas/aggregation hooks stay in `ResultsToolbar`. `RawToolbar` starts in
interval-selection mode and binds its scrollbar to Data's complete plot or the
sensor navigator's full source limits,
not just the currently loaded context. Sensor limit callbacks load originals
before raw Y scaling runs. Automatic X restores the full source range; sensor
Home and Reset limits retain their original inspection-context behavior.

Automatic raw Y limits use exact finite extrema from selected visible channels,
reusing `RawSignalLine`'s bounded peak-preserving summaries. Neighbours retained
for drawing clipped lines cannot influence Y limits from outside the window.
Binary indicators keep their fixed scale; empty windows retain finite bounds.
Y fitting settles after hand/scrollbar/trackpad gestures; manual Y limits remain
fixed. Channel redraws reconnect navigation to the new axes while retaining the
time view, group-specific manual limits and a usable Home/history. Zoom-in is
bounded by floating-point precision, and zoom-out by the full source range.
The smoke probe exercises raw zoom, automatic Y, horizontal scrolling and an
actual hand drag with its packaged icon and Back history.

The hand uses Matplotlib's Pan action and mouse-capture lifecycle, with a
time-only translation instead of `Axes.drag_pan` (which would also mark Y as
manual). `TimeScroll.bounded_limits` clamps each proposed window before sample
loading or render callbacks. Hand drags use the existing scroll start/end hooks,
including Results' bounded viewport painting and deferred Y refitting. The
settled view is saved once on release; mode changes, Home/history, zoom buttons,
view/data replacement and lost button releases finish the gesture. The shared
canvas maps Matplotlib's Move cursor to Qt's open/closed hand, retaining normal
wait-cursor restoration. `scripts/benchmark_pan.py` measures actual hand gestures
in all four Results views and both raw workspaces, alongside the scroll scenarios.

`ScrollableFigureCanvas` paints the shared translucent blue interval preview
through Qt's rubberband hook for both raw and Results graphs. The band spans
graphs and gaps without redrawing data or entering the exported figure.

Results Graphs uses one `QScrollArea` for the canvas. The workspace itself does
not scroll: the toolbar, axis-limit controls, time ruler and footer stay outside
that viewport, and the series tree scrolls independently. Canvas minimum heights
preserve readable plots without imposing a workspace minimum that creates a
second scrollbar in compact windows. The plot viewport is installed when Graphs
is first opened, preserving deferred canvas construction.

## Analysis progress

`analysis_progress` reports a 0–1000 work plan through the existing analysis event
queues and a dedicated worker signal. Preparation, coverage and final assembly
use Studio-owned milestones. A read-only logging handler recognizes ParaDigMa
1.1.2's INFO stage messages, scoped to the current prepared section and selected
module. Unknown messages leave progress unchanged. Sections and parallel workers
are weighted by sample count; module groups receive shares based on their stage
counts. Prefix sums and running totals keep updates independent of recording
length and batch size. No sensor values are rescanned for progress.

The job logger carries a dedicated logging `NullHandler` whose callback forwards
progress to the worker signal, so milestones never become new log/status text.
Duplicate values are ignored, the GUI coalesces updates at 200 ms intervals, and
worker identity/cancellation checks reject stale updates.
Analysis uses the existing text-free bar; other jobs keep its busy mode. Child
completion/transfer stops below full scale; the GUI marks it full only after its
results callback finishes on the GUI thread. Cancellation and errors stop pending
updates. `core.analyze(progress=AnalysisProgress(callback))` optionally exposes the
same milestones to synchronous integrations without changing pipeline settings
or result payloads. The callback receives integer work units, not time estimates.
