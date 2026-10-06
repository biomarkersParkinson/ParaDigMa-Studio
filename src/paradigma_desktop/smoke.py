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
        window = MainWindow()
        try:
            if window.windowIcon().isNull() or window.windowIcon().pixmap(32, 32).isNull():
                raise RuntimeError("Bundled application icon could not be rendered")
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
                window.analyzed(results)
                window.dataset.setCurrentText("quantifications/tremor")
                window.show()
                app.processEvents()
                window.canvas.draw()
                if len(window.figure.axes[0].lines) != 1:
                    raise RuntimeError("Result plot was not rendered")
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
                report.update(status="passed", paradigma_version=version("paradigma"),
                              app_icon_rendered=True,
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
