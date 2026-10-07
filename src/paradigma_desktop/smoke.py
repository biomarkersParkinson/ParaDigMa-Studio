"""Exercise startup and analysis inside the packaged executable."""
import json
import os
import tempfile
import traceback
from importlib.metadata import version
from pathlib import Path


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

        # These bundled models import sklearn classes dynamically via pickle.
        models = []
        for name in (
            "gait_detection_clf_package.pkl", "gait_filtering_clf_package.pkl",
            "ppg_quality_clf_package.pkl", "tremor_detection_clf_package.pkl",
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
            if QPixmap(str(files("paradigma_desktop") / "data" / "chevron-down.svg")).isNull():
                raise RuntimeError("Bundled dropdown indicator could not be rendered")
            if QPixmap(str(files("paradigma_desktop") / "data" / "checkmark.svg")).isNull():
                raise RuntimeError("Bundled checkbox indicator could not be rendered")
            window.about_button.click()
            attribution = window._acknowledgements_dialog
            if "10.5281/zenodo.13838392" not in attribution.acknowledgement.toPlainText():
                raise RuntimeError("ParaDigMa research citation is missing from About")
            if "Copyright (c) 2023, Peter Kok" not in attribution.licence.toPlainText():
                raise RuntimeError("The full upstream licence/copyright notice is missing")
            attribution.copy_button.click()
            if "@software{paradigma2024" not in app.clipboard().text():
                raise RuntimeError("ParaDigMa software citation could not be copied")
            attribution.close()
            with tempfile.TemporaryDirectory(prefix="paradigma-smoke-") as directory:
                directory = Path(directory)
                t = np.arange(12000) / 100
                rng = np.random.default_rng(42)
                frame = pd.DataFrame({
                    "time": t,
                    **{f"gyroscope_{axis}": 0.1 * np.sin(2 * np.pi * 5 * t)
                       + rng.normal(0, 0.02, len(t)) for axis in "xyz"},
                })
                source = directory / "sensor.csv"
                frame.to_csv(source, index=False)
                loaded = load_sensor_file(source)
                results = analyze(loaded, pipelines=["tremor"], output_dir=directory / "logs")
                if results.get("errors"):
                    raise RuntimeError(f"Tremor analysis failed: {results['errors']}")
                quantified = results["quantifications"]["tremor"]
                if quantified.empty or "tremor_power" not in quantified.columns:
                    raise RuntimeError("Tremor analysis returned no quantified output")
                window.loaded((str(source), loaded))
                window.set_input_channels(["gyroscope_x", "gyroscope_y", "gyroscope_z"])
                lines = window.data_figure.axes[0].lines
                if len(lines) != 3 or len({tuple(line.get_color()) for line in lines}) != 3:
                    raise RuntimeError("Input channel multi-selection or distinct plot colors failed")
                for line in lines:
                    if not np.array_equal(line.get_ydata(), loaded[line.get_label()].to_numpy()):
                        raise RuntimeError("Input graph changed original sensor values")
                toolbar = window.data_toolbar
                actions = [action.text() for action in toolbar.actions()]
                if actions.count("Graph settings") != 1 or "Subplots" in actions or "Customize" in actions:
                    raise RuntimeError("Graph settings are duplicated")
                toolbar.settings_action.setChecked(True)
                toolbar.settings.title.setText("Sensor inspection")
                toolbar.settings.apply_button.click()
                if window.data_figure.axes[0].get_title(loc="left") != "Sensor inspection":
                    raise RuntimeError("Integrated graph settings did not apply")
                toolbar.settings.reset_button.click()
                toolbar.settings_action.setChecked(False)
                if "time" in window.channel_table.model().frame["Channel"].tolist():
                    raise RuntimeError("Time channel was included in sensor descriptives")
                timing = window.time_table.model().frame.set_index("Statistic")
                if not np.isclose(timing.loc["Estimated sampling rate (Hz)", "Value"], 100):
                    raise RuntimeError("Input time descriptives have an incorrect sampling rate")
                if [window.data_tabs.tabText(i) for i in range(3)] != ["Overview", "Graphs", "Tables"]:
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
                window.analyzed(results)
                if results["classifications"]["tremor"].empty or not window.overview_values:
                    raise RuntimeError("Official classification retention or aggregate overview failed")
                if window.pages.currentIndex() != 2:
                    raise RuntimeError("Completed analysis did not open the Results workspace")
                window.dataset.setCurrentText("quantifications/tremor")
                window.show()
                app.processEvents()
                window.canvas.draw()
                if len(window.figure.axes[0].lines) != 1:
                    raise RuntimeError("Result plot was not rendered")
                window.time_from.setText("60")
                window.apply_filters()
                selected = quantified.loc[quantified["time"] >= 60]
                if window.result_table.model().rowCount() != len(selected) or len(selected) == len(quantified):
                    raise RuntimeError("Shared result filtering did not change the table")
                if not np.array_equal(window.figure.axes[0].lines[0].get_ydata(), selected[window.y_column.currentData()].to_numpy()):
                    raise RuntimeError("Graph and table did not use the same result selection")
                window.reset_filters()
                classification = results["classifications"]["tremor"]
                state = next(column for column in classification if binary_indicator(classification[column], column))
                window.result_series.blockSignals(True)
                for key, item in window._series_items.items():
                    item.setCheckState(0, Qt.Checked if key == ("classifications/tremor", state) else Qt.Unchecked)
                window.result_series.blockSignals(False)
                window.plot()
                window.canvas.draw()
                state_axes = window.figure.axes[0]
                valid = np.isfinite(classification[state].to_numpy(dtype=float))
                if state_axes.lines or not np.array_equal(state_axes.collections[0].get_offsets()[:, 1], classification[state].to_numpy()[valid]):
                    raise RuntimeError("Binary output did not preserve its states as a categorical raster")
                window.result_tabs.setCurrentIndex(1)
                if not window.dataset_field.isHidden() or not window.y_column.isHidden():
                    raise RuntimeError("Graphs still have redundant output/metric selectors")
                if not window.clock_input.calendar.calendarPopup():
                    raise RuntimeError("The recording time origin has no calendar selector")
                window.result_tabs.setCurrentIndex(0)
                export = directory / "results.json"
                export_results(export, results, {"source": source.name})
                saved = json.loads(export.read_text(encoding="utf-8"))
                if len(saved["results"]["quantifications"]["tremor"]["data"]) != len(quantified):
                    raise RuntimeError("Result export lost quantified rows")
                # The official example has fractional timestamps that break
                # the older PyPI CWA reader under NumPy 2. Exercise the real
                # recording and gait pipeline inside the packaged executable.
                cwa_source = files("paradigma_desktop") / "data" / "test_data.CWA"
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
                    combined_input[f"accelerometer_{axis}"] = (1 if axis == "z" else 0) + .1 * np.sin(t)
                combined = analyze(combined_input, pipelines=["gait", "tremor", "pulse_rate"],
                                   skip_preparation=True, watch_side="left")
                if combined["errors"] or set(combined["classifications"]) != {"gait", "tremor", "pulse_rate"}:
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
                if len(window.figure.axes[0].lines) != 1:
                    raise RuntimeError("CWA result plot was not rendered")
                window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
                if not window.context_button.isEnabled():
                    raise RuntimeError("Explicit gait segment metadata did not enable sensor inspection")
                window.inspect_sensor_context()
                if window.sensor_table.model() is None or not window.sensor_table.model().rowCount():
                    raise RuntimeError("Gait segment did not reveal its original sensor samples")
                # The official Empatica example has an empty gyroscope stream.
                # Import it for inspection without inventing missing channels.
                avro_source = files("paradigma_desktop") / "data" / "test_data.avro"
                avro_frame = load_sensor_file(avro_source)
                if len(avro_frame) != 115904 or any("gyroscope" in column for column in avro_frame):
                    raise RuntimeError("Empatica import lost samples or invented gyroscope channels")
                window.loaded((str(avro_source), avro_frame))
                app.processEvents()
                if window.input_table.model().rowCount() != 115904:
                    raise RuntimeError("Empatica samples were not displayed")
                if "require gyroscope" not in window.status.text():
                    raise RuntimeError("Empatica analysis requirements were not displayed")
                physilog_source = files("paradigma_desktop") / "data" / "physilog_excerpt.parquet"
                physilog = load_sensor_file(physilog_source)
                physilog_results = analyze(physilog, pipelines=["gait"], watch_side="left",
                                           drop_missing_samples=True, split_by_gaps=True)
                details = physilog_results["metadata"]["desktop_preparation"]
                if physilog_results.get("errors") or details["excluded_samples"] != 10 or details["continuous_sections"] != 4:
                    raise RuntimeError("Physilog missing samples or recording gaps were not handled correctly")
                physilog_gait = physilog_results["quantifications"]["gait"]["unfiltered"]
                if physilog_gait.empty:
                    raise RuntimeError("Physilog example returned no gait measurements")
                # Reopen an explicitly exported result through the Runs page.
                # This also exercises the frozen app's Qt background worker,
                # metadata persistence and safe JSON restoration.
                from .history import new_run, now
                record = new_run(str(source), {"pipelines": ["tremor"]})
                record.update(status="Completed", finished=now(), paradigma_version=version("paradigma"),
                              outputs=[{"kind": "JSON", "path": str(export)}])
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
                if window.worker is not None or window.results["quantifications"]["tremor"].shape != quantified.shape:
                    raise RuntimeError("Exported run did not reopen correctly")
                if window.pages.currentIndex() != 2 or window.result_source_frame is not None:
                    raise RuntimeError("Reopening a run changed its navigation or reloaded original sensor data")
                report.update(status="passed", paradigma_version=version("paradigma"),
                              app_icon_rendered=True,
                              workspace_navigation_verified=True,
                              integrated_page_controls_verified=True,
                              dropdown_indicator_rendered=True,
                              module_multiselection_verified=True,
                              all_module_execution_verified=True,
                              inline_analysis_help_verified=True,
                              paradigma_acknowledgement_verified=True,
                              aggregate_overview_verified=True,
                              absolute_recording_clock_verified=True,
                              estimated_gait_positions_verified=True,
                              linked_result_selection_verified=True,
                              binary_state_raster_verified=True,
                              calendar_time_controls_verified=True,
                              gait_sensor_context_verified=True,
                              run_history_reopened=True,
                              models_loaded=models, quantified_rows=len(quantified),
                              qt_plot_rendered=True, export_verified=True,
                              cwa_samples=len(cwa_frame), cwa_gait_rows=len(cwa_quantified),
                              cwa_plot_rendered=True, empatica_samples=len(avro_frame),
                              empatica_inspection_verified=True,
                              physilog_excluded_samples=details["excluded_samples"],
                              physilog_continuous_sections=details["continuous_sections"],
                              physilog_gait_rows=len(physilog_gait))
        finally:
            window.close()
            app.processEvents()
    except Exception:
        report["traceback"] = traceback.format_exc()
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1
