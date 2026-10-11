"""Exercise startup and analysis inside the packaged executable."""

import json
import logging
import os
import tempfile
import traceback
from importlib.metadata import version
from pathlib import Path
from threading import Event


def smoke_test(report_path):
    report_path = Path(report_path).resolve()
    report = {"status": "failed"}
    try:
        # Use real Qt rendering without requiring a display on the build runner.
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        import numpy as np
        import pandas as pd
        from importlib.resources import files
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import QEventLoop, QTimer, Qt
        from paradigma.classification import ClassifierPackage

        from .app import MainWindow
        from .core import analyze, export_results, load_sensor_file
        from .plotting import binary_indicator
        from .results_view import clock_times
        from .inspection import inspect_recording
        from .recordings import load_recordings
        from .analysis_process import run_isolated_analysis

        # These bundled models import sklearn classes dynamically via pickle.
        models = []
        for name in (
            "gait_detection_clf_package.pkl",
            "gait_filtering_clf_package.pkl",
            "ppg_quality_clf_package.pkl",
            "tremor_detection_clf_package.pkl",
        ):
            model = ClassifierPackage.load(files("paradigma.assets") / name)
            if model.classifier is None:
                raise RuntimeError(f"Bundled model has no classifier: {name}")
            models.append(name)

        app = QApplication.instance() or QApplication([])
        app.setStyle("Fusion")
        window = MainWindow(history_dir=report_path.parent / "run-history")
        try:
            if window.windowIcon().isNull() or window.windowIcon().pixmap(32, 32).isNull():
                raise RuntimeError("Bundled application icon could not be rendered")
            if QPixmap(str(files("paradigma_studio") / "data" / "chevron-down.svg")).isNull():
                raise RuntimeError("Bundled dropdown indicator could not be rendered")
            if QPixmap(str(files("paradigma_studio") / "data" / "checkmark.svg")).isNull():
                raise RuntimeError("Bundled checkbox indicator could not be rendered")
            if QPixmap(str(files("paradigma_studio") / "data" / "directions_axes.png")).isNull():
                raise RuntimeError(
                    "Bundled ParaDigMa device-axis reference figure could not be rendered"
                )
            window.about_button.click()
            attribution = window._acknowledgements_dialog
            if "10.5281/zenodo.13838392" not in attribution.acknowledgement.toPlainText():
                raise RuntimeError("ParaDigMa research citation is missing from About")
            if "Copyright (c) 2023, Peter Kok" not in attribution.licence.toPlainText():
                raise RuntimeError("The full upstream licence/copyright notice is missing")
            if (
                "Copyright 2026 ParaDigMa Studio contributors"
                not in attribution.licence.toPlainText()
            ):
                raise RuntimeError("The Studio Apache 2.0 licence/copyright notice is missing")
            attribution.copy_button.click()
            if "@software{paradigma2024" not in app.clipboard().text():
                raise RuntimeError("ParaDigMa software citation could not be copied")
            attribution.close()
            with tempfile.TemporaryDirectory(prefix="paradigma-smoke-") as directory:
                directory = Path(directory)
                t = np.arange(12000) / 100
                rng = np.random.default_rng(42)
                frame = pd.DataFrame(
                    {
                        "time": t,
                        **{f"accelerometer_{axis}": 0.2 * np.sin(2 * np.pi * t) for axis in "xyz"},
                        **{
                            f"gyroscope_{axis}": 0.1 * np.sin(2 * np.pi * 5 * t)
                            + rng.normal(0, 0.02, len(t))
                            for axis in "xyz"
                        },
                    }
                )
                source = directory / "sensor.csv"
                frame.to_csv(source, index=False)
                loaded = load_sensor_file(source)
                results = run_isolated_analysis(
                    loaded, {"pipelines": ["tremor"]}, logging.getLogger("paradigma-smoke"), Event()
                )
                if results.get("errors"):
                    raise RuntimeError(f"Tremor analysis failed: {results['errors']}")
                quantified = results["quantifications"]["tremor"]
                if quantified.empty or "tremor_power" not in quantified.columns:
                    raise RuntimeError("Tremor analysis returned no quantified output")
                window.loaded((str(source), loaded))
                window.set_input_channels(["gyroscope_x", "gyroscope_y", "gyroscope_z"])
                lines = window.data_figure.axes[0].lines
                if len(lines) != 3 or len({tuple(line.get_color()) for line in lines}) != 3:
                    raise RuntimeError(
                        "Input channel multi-selection or distinct plot colors failed"
                    )
                for line in lines:
                    if not np.array_equal(line.get_ydata(), loaded[line.get_label()].to_numpy()):
                        raise RuntimeError("Input graph changed original sensor values")
                window.set_input_channels(
                    ["accelerometer_x", "accelerometer_y", "gyroscope_x", "gyroscope_y"]
                )
                groups = [[line.get_label() for line in ax.lines] for ax in window.data_figure.axes]
                if groups != [
                    ["accelerometer_x", "accelerometer_y"],
                    ["gyroscope_x", "gyroscope_y"],
                ]:
                    raise RuntimeError("Raw sensor modalities were mixed in one graph")
                for ax in window.data_figure.axes:
                    for line in ax.lines:
                        if not np.array_equal(
                            line.get_ydata(), loaded[line.get_label()].to_numpy()
                        ):
                            raise RuntimeError("Modality grouping changed original sensor values")
                window.set_input_channels(["gyroscope_x", "gyroscope_y", "gyroscope_z"])
                toolbar = window.data_toolbar
                actions = [action.text() for action in toolbar.actions()]
                if (
                    actions.count("Axis limits") != 1
                    or "Subplots" in actions
                    or "Customize" in actions
                ):
                    raise RuntimeError("Graph settings are duplicated")
                toolbar.settings_action.setChecked(True)
                automatic, lower, upper = toolbar.settings.bounds["x"]
                automatic.setChecked(False)
                lower.setText("0.5")
                upper.setText("1.5")
                upper.editingFinished.emit()
                if not np.allclose(window.data_figure.axes[0].get_xlim(), [0.5, 1.5]):
                    raise RuntimeError("Integrated axis limits did not apply")
                if (
                    not window.plot_toolbar.select_action.isChecked()
                    or window.plot_toolbar.select_action.icon().pixmap(24, 24).isNull()
                    or toolbar.select_action is not None
                    or not toolbar._actions["pan"].isChecked()
                ):
                    raise RuntimeError("Default timepoint cursor or its packaged icon is missing")
                toolbar.settings.reset_button.click()
                toolbar.settings_action.setChecked(False)
                if "time" in window.channel_table.model().frame["Channel"].tolist():
                    raise RuntimeError("Time channel was included in sensor descriptives")
                timing = window.time_table.model().frame.set_index("Statistic")
                if not np.isclose(timing.loc["Estimated sampling rate (Hz)", "Value"], 100):
                    raise RuntimeError("Input time descriptives have an incorrect sampling rate")
                if [window.data_tabs.tabText(i) for i in range(3)] != [
                    "Overview",
                    "Graphs",
                    "Tables",
                ]:
                    raise RuntimeError("Data exploration tabs are missing")
                window.module_buttons["Tremor"].click()
                if window.selected_modules() != ["gait", "tremor"]:
                    raise RuntimeError("Analysis module multi-selection failed")
                window.set_modules(["tremor"])
                window.set_modules(["gait", "tremor", "pulse_rate"])
                if window.selected_modules() != ["gait", "tremor", "pulse_rate"]:
                    raise RuntimeError("All three modules cannot be selected together")
                help_button, help_text = window.analysis_help["Device axes"]
                help_button.click()
                if help_text.isHidden() or "toolbox X = minus sensor Y" not in help_text.text():
                    raise RuntimeError("Documented inline axis guidance is unavailable")
                help_button.click()
                window.set_modules(["tremor"])
                if not window.pages.widget(1).isAncestorOf(window.mapping):
                    raise RuntimeError("Analysis parameters are not integrated into Analyze")
                if not window.pages.widget(2).isAncestorOf(window.y_column):
                    raise RuntimeError("Result controls are not integrated into Results")
                if (
                    window.gaps.isChecked()
                    or window.max_gap.value() != 1.5
                    or window.min_segment.value() != 1.5
                ):
                    raise RuntimeError("Gap controls differ from the pinned official defaults")
                for title, spin in (
                    ("Maximum gap", window.max_gap),
                    ("Minimum section duration", window.min_segment),
                ):
                    spin.setValue(12)
                    window.section_reset_buttons[title].click()
                    if spin.value() != 1.5:
                        raise RuntimeError("The official section default could not be restored")
                window.analyzed(results)
                if results["classifications"]["tremor"].empty or not window.overview_values:
                    raise RuntimeError(
                        "Official classification retention or aggregate overview failed"
                    )
                if window.pages.currentIndex() != 2:
                    raise RuntimeError("Completed analysis did not open the Results workspace")
                window.dataset.setCurrentText("quantifications/tremor")
                pd.testing.assert_frame_equal(
                    window.result_table.model().frame, quantified, check_exact=True
                )
                window.show()
                app.processEvents()
                if window.about_button.text() != "About" or not window.sidebar.isAncestorOf(
                    window.about_button
                ):
                    raise RuntimeError("Sidebar About action is missing")
                tab_bar = window.result_tabs.tabBar()
                positions = [tab_bar.mapTo(window, tab_bar.tabRect(i).topLeft()) for i in range(3)]
                for index in (1, 2, 0):
                    window.result_tabs.setCurrentIndex(index)
                    app.processEvents()
                    if [
                        tab_bar.mapTo(window, tab_bar.tabRect(i).topLeft()) for i in range(3)
                    ] != positions:
                        raise RuntimeError("Results tabs move between views")
                    if index == 1:
                        window.canvas.draw()
                        if (
                            not window.time_axis.isVisible()
                            or window.graph_scroll.isAncestorOf(window.time_axis)
                            or not np.allclose(
                                window.time_axis.axes.get_xlim(), window.figure.axes[0].get_xlim()
                            )
                        ):
                            raise RuntimeError(
                                "Pinned recording time axis is missing or misaligned"
                            )
                window.canvas.draw()
                axes = next(
                    ax
                    for ax in window.figure.axes
                    if ax._paradigma_dataset == "quantifications/tremor"
                )
                bars = axes.collections[0].get_paths()
                values = quantified[window.y_column.currentData()].to_numpy()
                finite = np.isfinite(values)
                if not np.array_equal([bar.vertices[1, 1] for bar in bars], values[finite]):
                    raise RuntimeError("Result bars differ from the original output")
                if not any(name.startswith("preparation/") for name in window._plot_tables):
                    raise RuntimeError("Prepared-input availability is missing")
                if hasattr(window, "filters_toggle"):
                    raise RuntimeError("Removed Results time filters are still present")
                classification = results["classifications"]["tremor"]
                state = "pred_tremor_checked"
                if not binary_indicator(classification[state], state):
                    raise RuntimeError("Checked tremor predictions are not binary")
                window.result_series.blockSignals(True)
                for key, item in window._series_items.items():
                    item.setCheckState(
                        0, Qt.Checked if key == ("classifications/tremor", state) else Qt.Unchecked
                    )
                window.result_series.blockSignals(False)
                window.plot()
                window.canvas.draw()
                state_axes = window.figure.axes[0]
                present = classification[state].to_numpy(dtype=float) == 1.0
                if state_axes.lines or not np.array_equal(
                    [bar.vertices[:, 0].min() for bar in state_axes.collections[0].get_paths()],
                    classification.time.to_numpy()[present],
                ):
                    raise RuntimeError("Binary output did not show only positive detections")
                if state_axes.patches:
                    raise RuntimeError("Binary graph background implies continuous detection")
                window.result_tabs.setCurrentIndex(1)
                if not window.dataset_field.isHidden() or not window.y_column.isHidden():
                    raise RuntimeError("Graphs still have redundant output/metric selectors")
                if not window.graph_footer.isAncestorOf(window.context_controls):
                    raise RuntimeError("Sensor context controls are not in the graph footer")
                if not window.figure_actions.isAncestorOf(window.graph_view_controls):
                    raise RuntimeError("Graph View selector is not beside the figure buttons")
                window.dataset.setCurrentText("classifications/tremor")
                row = int(np.flatnonzero(present)[0]) if present.any() else 0
                window.result_table.setCurrentIndex(window.result_table.model().index(row, 0))
                window.canvas.draw()
                seconds = float(
                    window._timings["classifications/tremor"].iloc[row]["Timeline time (s)"]
                )
                expected_label = (
                    clock_times([seconds], window.display_clock)[0]
                    .strftime("%d %b %Y %H:%M:%S.%f")
                    .rstrip("0")
                    .rstrip(".")
                    if window.display_clock
                    else f"{seconds:.6g} s"
                )
                if (
                    not any(
                        line.get_gid() == "selected-result-time"
                        for line in window.figure.axes[0].lines
                    )
                    or not window.time_axis.selection_marker.get_visible()
                    or window.time_axis.selection_label.get_text() != expected_label
                ):
                    raise RuntimeError(
                        "The selected result time is not marked in the graph and pinned axis"
                    )
                if not window.clock_input.calendar.calendarPopup():
                    raise RuntimeError("The recording time origin has no calendar selector")
                window.result_tabs.setCurrentIndex(2)
                window.table_dataset.setCurrentIndex(
                    window.table_dataset.findData("classifications/tremor")
                )
                pd.testing.assert_frame_equal(
                    window.result_table.model().frame, classification, check_exact=True
                )
                window.table_dataset.setCurrentIndex(
                    window.table_dataset.findData("aggregations/tremor")
                )
                aggregates = (
                    window.aggregation_table.model().frame.set_index("measure")["value"].to_dict()
                )
                if aggregates != results["aggregations"]["tremor"]:
                    raise RuntimeError(
                        "The separate full-run aggregation table differs from official output"
                    )
                window.result_tabs.setCurrentIndex(0)
                export = directory / "results.json"
                export_results(export, results, {"source": source.name})
                saved = json.loads(export.read_text(encoding="utf-8"))
                if len(saved["results"]["quantifications"]["tremor"]["data"]) != len(quantified):
                    raise RuntimeError("Result export lost quantified rows")
                # The official example has fractional timestamps that break
                # the older PyPI CWA reader under NumPy 2. Exercise the real
                # recording and gait pipeline inside the packaged executable.
                cwa_source = files("paradigma_studio") / "data" / "test_data.CWA"
                cwa_frame = load_sensor_file(cwa_source)
                if len(cwa_frame) != 36400 or not cwa_frame["time"].is_unique:
                    raise RuntimeError("CWA sample count or timestamps are incorrect")
                cwa_results = analyze(cwa_frame, pipelines=["gait"], watch_side="left")
                if cwa_results.get("errors"):
                    raise RuntimeError(f"CWA gait analysis failed: {cwa_results['errors']}")
                cwa_quantified = cwa_results["quantifications"]["gait"]["unfiltered"]
                if cwa_quantified.empty or "range_of_motion" not in cwa_quantified:
                    raise RuntimeError("CWA gait analysis returned no quantified output")
                combined_input = frame.copy()
                combined_input["green"] = np.sin(2 * np.pi * 1.2 * t)
                for axis in "xyz":
                    combined_input[f"accelerometer_{axis}"] = (
                        1 if axis == "z" else 0
                    ) + 0.1 * np.sin(t)
                combined = analyze(
                    combined_input,
                    pipelines=["gait", "tremor", "pulse_rate"],
                    skip_preparation=True,
                    watch_side="left",
                )
                if combined["errors"] or set(combined["classifications"]) != {
                    "gait",
                    "tremor",
                    "pulse_rate",
                }:
                    raise RuntimeError("Combined official IMU and pulse-rate execution failed")
                window.loaded((str(cwa_source), cwa_frame))
                window.analyzed(cwa_results)
                if window.display_clock is None:
                    raise RuntimeError("CWA recording dates are missing from results")
                if any("per_segment" in path for module, group, path in window.overview_values):
                    raise RuntimeError("Individual gait-segment metadata leaked into Overview")
                timing = window._timings["quantifications/gait/unfiltered"]
                if not timing["Time basis"].str.contains("Estimated", case=False).all():
                    raise RuntimeError("Gait display times were not identified as estimates")
                window.dataset.setCurrentText("quantifications/gait/unfiltered")
                app.processEvents()
                window.canvas.draw()
                gait_axes = next(
                    ax
                    for ax in window.figure.axes
                    if ax._paradigma_dataset == "quantifications/gait/unfiltered"
                )
                if not gait_axes.collections[0].get_paths() or not getattr(
                    gait_axes, "_paradigma_bars", False
                ):
                    raise RuntimeError("CWA result plot was not rendered")
                window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
                if not window.context_button.isEnabled():
                    raise RuntimeError(
                        "Explicit gait segment metadata did not enable sensor inspection"
                    )
                window.inspect_sensor_context()
                if (
                    window.sensor_table.model() is None
                    or not window.sensor_table.model().rowCount()
                ):
                    raise RuntimeError("Gait segment did not reveal its original sensor samples")
                batch_paths = [directory / "subject-part1.csv", directory / "subject-part2.csv"]
                frame.to_csv(batch_paths[0], index=False)
                second = frame.copy()
                second["gyroscope_x"] += 0.002
                second.to_csv(batch_paths[1], index=False)
                batch_sources, batch_frames = load_recordings(batch_paths)
                batch_results = analyze(batch_frames, pipelines=["tremor"])
                batch_quantified = batch_results["quantifications"]["tremor"]
                if batch_results["errors"] or set(batch_quantified.file_key) != set(batch_frames):
                    raise RuntimeError("Multiple-recording analysis lost a recording")
                window.loaded_recordings(
                    (
                        batch_sources,
                        batch_frames,
                        {
                            key: inspect_recording(data, "relative_s")
                            for key, data in batch_frames.items()
                        },
                    )
                )
                window.provenance = {
                    "source": str(batch_paths[0]),
                    "sources": batch_sources,
                    "settings": {"pipelines": ["tremor"]},
                }
                window.analyzed(batch_results)
                if window.display_clock is not None or window.input_recording.isHidden():
                    raise RuntimeError(
                        "Multiple input selection or relative recording clocks are incorrect"
                    )
                window.dataset.setCurrentText("quantifications/tremor")
                position = int(np.flatnonzero(batch_quantified.file_key.eq("recording_002"))[0])
                window.result_table.setCurrentIndex(window.result_table.model().index(position, 0))
                window.inspect_sensor_context()
                if (
                    window._sensor_context.source_name != "subject-part2.csv"
                    or not len(window.sensor_times)
                    or window.sensor_times.min() < 120.0 - 1e-9
                ):
                    raise RuntimeError("Sensor context used the wrong source recording")
                batch_export = directory / "batch-results.json"
                export_results(batch_export, batch_results, window.provenance)
                from .history import load_result_export

                batch_provenance, reopened_batch = load_result_export(batch_export)
                if batch_provenance["sources"] != batch_sources or len(
                    reopened_batch["quantifications"]["tremor"]
                ) != len(batch_quantified):
                    raise RuntimeError("Multiple-recording export lost sources or rows")
                # The official Empatica example has an empty gyroscope stream.
                # Import it for inspection without inventing missing channels.
                avro_source = files("paradigma_studio") / "data" / "test_data.avro"
                avro_frame = load_sensor_file(avro_source)
                if len(avro_frame) != 115904 or any("gyroscope" in column for column in avro_frame):
                    raise RuntimeError(
                        "Empatica import lost samples or invented gyroscope channels"
                    )
                window.loaded((str(avro_source), avro_frame))
                app.processEvents()
                if window.input_table.model().rowCount() != 115904:
                    raise RuntimeError("Empatica samples were not displayed")
                if "require gyroscope" not in window.status.text():
                    raise RuntimeError("Empatica analysis requirements were not displayed")
                physilog_source = files("paradigma_studio") / "data" / "physilog_excerpt.parquet"
                physilog = load_sensor_file(physilog_source)
                physilog_results = analyze(
                    physilog,
                    pipelines=["gait"],
                    watch_side="left",
                    drop_missing_samples=True,
                    split_by_gaps=True,
                )
                details = physilog_results["metadata"]["desktop_preparation"]
                if (
                    physilog_results.get("errors")
                    or details["excluded_samples"] != 10
                    or details["continuous_sections"] != 4
                ):
                    raise RuntimeError(
                        "Physilog missing samples or recording gaps were not handled correctly"
                    )
                physilog_gait = physilog_results["quantifications"]["gait"]["unfiltered"]
                if physilog_gait.empty:
                    raise RuntimeError("Physilog example returned no gait measurements")
                # Reopen an explicitly exported result through the Runs page.
                # This also exercises the frozen app's Qt background worker,
                # metadata persistence and safe JSON restoration.
                from .history import new_run, now

                record = new_run(str(source), {"pipelines": ["tremor"]})
                record.update(
                    status="Completed",
                    finished=now(),
                    paradigma_version=version("paradigma"),
                    outputs=[{"kind": "JSON", "path": str(export)}],
                )
                window.history.save(record)
                window.runs, issues = window.history.load()
                if issues or len(window.runs) != 1:
                    raise RuntimeError("Run history did not round-trip")
                window.selected_run = None
                window.refresh_runs()
                window.navigate(3)
                window.open_run()
                if window.worker is None:
                    raise RuntimeError("Exported result was not reopened in a background worker")
                loop = QEventLoop()
                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(loop.quit)
                window.worker.finished.connect(loop.quit)
                timer.start(15000)
                loop.exec()
                timer.stop()
                if (
                    window.worker is not None
                    or window.results["quantifications"]["tremor"].shape != quantified.shape
                ):
                    raise RuntimeError("Exported run did not reopen correctly")
                if window.pages.currentIndex() != 2 or window.result_source_frame is not None:
                    raise RuntimeError(
                        "Reopening a run changed its navigation or reloaded original sensor data"
                    )
                window.save_results_button.click()
                if window.worker is None:
                    raise RuntimeError("Local results were not saved in a background worker")
                window.worker.finished.connect(loop.quit)
                timer.start(15000)
                loop.exec()
                timer.stop()
                if window.worker is not None:
                    raise RuntimeError("Local results save did not finish")
                window.runs, issues = window.history.load()
                saved_output = window.runs[0]["outputs"][-1]
                if (
                    issues
                    or not saved_output.get("local")
                    or not Path(saved_output["path"]).is_file()
                ):
                    raise RuntimeError("Local results were not linked to the saved run")
                window.selected_run = None
                window.refresh_runs()
                window.navigate(3)
                window.open_run()
                if window.worker is None:
                    raise RuntimeError("Local saved run was not reopened from disk")
                window.worker.finished.connect(loop.quit)
                timer.start(15000)
                loop.exec()
                timer.stop()
                if (
                    window.worker is not None
                    or window.results["quantifications"]["tremor"].shape != quantified.shape
                ):
                    raise RuntimeError("Local saved results did not reopen correctly")
                report.update(
                    status="passed",
                    paradigma_version=version("paradigma"),
                    app_icon_rendered=True,
                    workspace_navigation_verified=True,
                    integrated_page_controls_verified=True,
                    dropdown_indicator_rendered=True,
                    module_multiselection_verified=True,
                    all_module_execution_verified=True,
                    inline_analysis_help_verified=True,
                    paradigma_acknowledgement_verified=True,
                    studio_licence_verified=True,
                    local_results_saved_verified=True,
                    aggregate_overview_verified=True,
                    original_output_tables_verified=True,
                    aggregation_tables_verified=True,
                    official_gap_defaults_verified=True,
                    absolute_recording_clock_verified=True,
                    estimated_gait_positions_verified=True,
                    linked_result_selection_verified=True,
                    binary_state_raster_verified=True,
                    presence_only_verified=True,
                    context_footer_verified=True,
                    view_toolbar_verified=True,
                    selected_result_marker_verified=True,
                    calendar_time_controls_verified=True,
                    gait_sensor_context_verified=True,
                    multiple_recordings_verified=True,
                    run_history_reopened=True,
                    models_loaded=models,
                    quantified_rows=len(quantified),
                    qt_plot_rendered=True,
                    raw_modality_groups_verified=True,
                    export_verified=True,
                    cwa_samples=len(cwa_frame),
                    cwa_gait_rows=len(cwa_quantified),
                    cwa_plot_rendered=True,
                    empatica_samples=len(avro_frame),
                    empatica_inspection_verified=True,
                    physilog_excluded_samples=details["excluded_samples"],
                    physilog_continuous_sections=details["continuous_sections"],
                    physilog_gait_rows=len(physilog_gait),
                )
        finally:
            window.close()
            app.processEvents()
    except Exception:
        report["traceback"] = traceback.format_exc()
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1
