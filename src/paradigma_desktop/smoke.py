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
                report.update(status="passed", paradigma_version=version("paradigma"),
                              models_loaded=models, quantified_rows=len(quantified),
                              qt_plot_rendered=True, export_verified=True)
        finally:
            window.close()
            app.processEvents()
    except Exception:
        report["traceback"] = traceback.format_exc()
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1
