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
        from PySide6.QtCore import QEventLoop, QTimer
        from paradigma.classification import ClassifierPackage

        from .app import MainWindow
        from .core import analyze, export_results, load_sensor_file

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
                if [window.data_tabs.tabText(i) for i in range(3)] != ["Overview", "Graphs", "Tables"]:
                    raise RuntimeError("Data exploration tabs are missing")
                window.module_buttons["Tremor"].click()
                if window.selected_modules() != ["gait", "tremor"]:
                    raise RuntimeError("Analysis module multi-selection failed")
                window.set_modules(["tremor"])
                if not window.pages.widget(1).isAncestorOf(window.mapping):
                    raise RuntimeError("Analysis parameters are not integrated into Analyze")
                if not window.pages.widget(2).isAncestorOf(window.y_column):
                    raise RuntimeError("Result controls are not integrated into Results")
                window.analyzed(results)
                if window.pages.currentIndex() != 2:
                    raise RuntimeError("Completed analysis did not open the Results workspace")
                window.dataset.setCurrentText("quantifications/tremor")
                window.show()
                app.processEvents()
                window.canvas.draw()
                if len(window.figure.axes[0].lines) != 1:
                    raise RuntimeError("Result plot was not rendered")
                window.filter_column.setCurrentText("time")
                window.filter_min.setText("60")
                window.apply_filters()
                selected = quantified.loc[quantified["time"] >= 60]
                if window.result_table.model().rowCount() != len(selected) or len(selected) == len(quantified):
                    raise RuntimeError("Shared result filtering did not change the table")
                if not np.array_equal(window.figure.axes[0].lines[0].get_ydata(), selected[window.y_column.currentData()].to_numpy()):
                    raise RuntimeError("Graph and table did not use the same result selection")
                window.reset_filters()
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
                window.loaded((str(cwa_source), cwa_frame))
                window.analyzed(cwa_results)
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
                              linked_result_selection_verified=True,
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
