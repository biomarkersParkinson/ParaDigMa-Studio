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
        from PySide6.QtWidgets import QApplication

        from .app import MainWindow

        models = _verify_bundled_models()
        app = QApplication.instance() or QApplication([])
        app.setStyle("Fusion")
        window = MainWindow(history_dir=report_path.parent / "run-history")
        try:
            _verify_bundled_ui(window, app)
            with tempfile.TemporaryDirectory(prefix="paradigma-smoke-") as directory:
                report.update(_verify_smoke_workflows(window, app, Path(directory), models))
        finally:
            window.close()
            app.processEvents()
    except Exception:
        # The packaged probe must report failures from any bundled dependency.
        report["traceback"] = traceback.format_exc()
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


def _verify_smoke_workflows(window, app, directory, models):
    frame, t = _synthetic_sensor_data()
    source, loaded, results, quantified = _run_tremor_example(directory, frame)
    quantified = quantified.copy(deep=True)  # Keep a reference independent of the UI result frames.
    _verify_input_graphs(window, source, loaded)
    _verify_data_descriptives(window)
    _verify_analysis_controls(window)
    _verify_result_navigation(window, app, results, quantified)
    _verify_continuous_outputs(window, quantified)
    classification, present = _verify_binary_outputs(window, results)
    _verify_result_selection(window, classification, present)
    _verify_official_result_tables(window, results, classification)
    export = _verify_result_export(directory, source, results, quantified)
    cwa_source, cwa_frame, cwa_results, cwa_quantified = _run_cwa_example()
    _verify_combined_modules(frame, t)
    _verify_gait_workspace(window, app, cwa_source, cwa_frame, cwa_results)
    _verify_multiple_recordings(window, directory, frame)
    avro_frame = _verify_empatica_inspection(window, app)
    details, physilog_gait = _verify_physilog_preparation()
    _verify_saved_run_roundtrip(window, source, export, quantified)
    return _successful_smoke_report(
        models, quantified, cwa_frame, cwa_quantified, avro_frame, details, physilog_gait
    )


def _verify_bundled_models():
    from importlib.resources import files

    from paradigma.classification import ClassifierPackage

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
    return models


def _verify_bundled_ui(window, app):
    from importlib.resources import files

    from PySide6.QtGui import QPixmap

    if window.windowIcon().isNull() or window.windowIcon().pixmap(32, 32).isNull():
        raise RuntimeError("Bundled application icon could not be rendered")
    if QPixmap(str(files("paradigma_studio") / "data" / "chevron-down.svg")).isNull():
        raise RuntimeError("Bundled dropdown indicator could not be rendered")
    if QPixmap(str(files("paradigma_studio") / "data" / "checkmark.svg")).isNull():
        raise RuntimeError("Bundled checkbox indicator could not be rendered")
    if QPixmap(str(files("paradigma_studio") / "data" / "directions_axes.png")).isNull():
        raise RuntimeError("Bundled ParaDigMa device-axis reference figure could not be rendered")
    window.about_button.click()
    attribution = window._shell_state._acknowledgements_dialog
    if "10.21105/joss.09502" not in attribution.acknowledgement.toPlainText():
        raise RuntimeError("ParaDigMa research citation is missing from About")
    if "Copyright (c) 2023, Peter Kok" not in attribution.licence.toPlainText():
        raise RuntimeError("The full upstream licence/copyright notice is missing")
    if "Copyright 2026 ParaDigMa Studio contributors" not in attribution.licence.toPlainText():
        raise RuntimeError("The Studio Apache 2.0 licence/copyright notice is missing")
    attribution.copy_button.click()
    copied = app.clipboard().text()
    if "@article{post2026paradigma" not in copied or "10.21105/joss.09502" not in copied:
        raise RuntimeError("ParaDigMa JOSS citation could not be copied")
    attribution.close()


def _synthetic_sensor_data():
    import numpy as np
    import pandas as pd

    t = np.arange(12000) / 100
    rng = np.random.default_rng(42)
    frame = pd.DataFrame(
        {
            "time": t,
            **{f"accelerometer_{axis}": 0.2 * np.sin(2 * np.pi * t) for axis in "xyz"},
            **{
                f"gyroscope_{axis}": 0.1 * np.sin(2 * np.pi * 5 * t) + rng.normal(0, 0.02, len(t))
                for axis in "xyz"
            },
        }
    )
    return frame, t


def _run_tremor_example(directory, frame):
    from .analysis_process import run_isolated_analysis
    from .core import load_sensor_file

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
    return source, loaded, results, quantified


def _verify_input_graphs(window, source, loaded):
    import numpy as np

    window.loaded((str(source), loaded))
    window.set_input_channels(["gyroscope_x", "gyroscope_y", "gyroscope_z"])
    lines = window.data_figure.axes[0].lines
    if len(lines) != 3 or len({tuple(line.get_color()) for line in lines}) != 3:
        raise RuntimeError("Input channel multi-selection or distinct plot colors failed")
    for line in lines:
        if not np.array_equal(line.get_ydata(), loaded[line.get_label()].to_numpy()):
            raise RuntimeError("Input graph changed original sensor values")
    window.set_input_channels(["accelerometer_x", "accelerometer_y", "gyroscope_x", "gyroscope_y"])
    groups = [[line.get_label() for line in ax.lines] for ax in window.data_figure.axes]
    if groups != [
        ["accelerometer_x", "accelerometer_y"],
        ["gyroscope_x", "gyroscope_y"],
    ]:
        raise RuntimeError("Raw sensor modalities were mixed in one graph")
    for ax in window.data_figure.axes:
        for line in ax.lines:
            if not np.array_equal(line.get_ydata(), loaded[line.get_label()].to_numpy()):
                raise RuntimeError("Modality grouping changed original sensor values")
    window.set_input_channels(["gyroscope_x", "gyroscope_y", "gyroscope_z"])
    _verify_input_graph_controls(window)


def _verify_input_graph_controls(window):
    import numpy as np

    toolbar = window.data_toolbar
    actions = [action.text() for action in toolbar.actions()]
    if actions.count("Axis limits") != 1 or "Subplots" in actions or "Customize" in actions:
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


def _verify_data_descriptives(window):
    import numpy as np

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


def _verify_analysis_controls(window):
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


def _verify_result_navigation(window, app, results, quantified):
    import numpy as np
    import pandas as pd

    window.analyzed(results)
    if results["classifications"]["tremor"].empty or not window._result_state.overview_values:
        raise RuntimeError("Official classification retention or aggregate overview failed")
    if window.pages.currentIndex() != 2:
        raise RuntimeError("Completed analysis did not open the Results workspace")
    window.dataset.setCurrentText("quantifications/tremor")
    pd.testing.assert_frame_equal(window.result_table.model().frame, quantified, check_exact=True)
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
        if [tab_bar.mapTo(window, tab_bar.tabRect(i).topLeft()) for i in range(3)] != positions:
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
                raise RuntimeError("Pinned recording time axis is missing or misaligned")


def _verify_continuous_outputs(window, quantified):
    import numpy as np
    import pandas as pd
    from PySide6.QtWidgets import QComboBox

    from .time_controls import TimeField

    window.canvas.draw()
    axes = next(
        ax
        for ax in window.figure.axes
        if ax._paradigma_dataset == "quantifications/tremor"
        and ax._paradigma_metric == "tremor_power"
    )
    bars = axes.collections[0].get_paths()
    # Independent reference from ParaDigMa aggregate_tremor; the scientific
    # output is raw, while the graph deliberately uses log10(power + 1).
    values = np.log10(quantified.tremor_power.to_numpy(dtype=float) + 1)
    finite = np.isfinite(values)
    if not finite.any() or not np.array_equal([bar.vertices[1, 1] for bar in bars], values[finite]):
        raise RuntimeError("Tremor bars differ from log10(original power + 1)")
    if axes.get_ylabel() != "log₁₀(power + 1)":
        raise RuntimeError("Tremor power axis does not identify the log transformation")
    pd.testing.assert_frame_equal(
        window._result_state.tables["quantifications/tremor"], quantified, check_exact=True
    )
    if not any(name.startswith("preparation/") for name in window._result_state._plot_tables):
        raise RuntimeError("Prepared-input availability is missing")
    selectors = {window.dataset, window.table_dataset, window.y_column, window.result_graph_view}
    if set(
        window.result_tabs.findChildren(QComboBox)
    ) != selectors or window.result_tabs.findChildren(TimeField):
        raise RuntimeError("Removed Results time filters are still present")


def _verify_binary_outputs(window, results):
    import numpy as np
    from PySide6.QtCore import Qt

    from .plotting import binary_indicator

    classification = results["classifications"]["tremor"]
    state = "pred_tremor_checked"
    if not binary_indicator(classification[state], state):
        raise RuntimeError("Checked tremor predictions are not binary")
    window.result_series.blockSignals(True)
    for key, item in window._result_state._series_items.items():
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
    return classification, present


def _verify_result_selection(window, classification, present):
    import numpy as np

    from .results_view import clock_times

    window.dataset.setCurrentText("classifications/tremor")
    row = int(np.flatnonzero(present)[0]) if present.any() else 0
    window.result_table.setCurrentIndex(window.result_table.model().index(row, 0))
    window.canvas.draw()
    seconds = float(
        window._result_state._timings["classifications/tremor"].iloc[row]["Timeline time (s)"]
    )
    expected_label = (
        clock_times([seconds], window._result_state.display_clock)[0]
        .strftime("%d %b %Y %H:%M:%S.%f")
        .rstrip("0")
        .rstrip(".")
        if window._result_state.display_clock
        else f"{seconds:.6g} s"
    )
    if (
        not any(line.get_gid() == "selected-result-time" for line in window.figure.axes[0].lines)
        or not window.time_axis.selection_marker.get_visible()
        or window.time_axis.selection_label.get_text() != expected_label
    ):
        raise RuntimeError("The selected result time is not marked in the graph and pinned axis")
    if not window.clock_input.calendar.calendarPopup():
        raise RuntimeError("The recording time origin has no calendar selector")


def _verify_official_result_tables(window, results, classification):
    import pandas as pd

    window.result_tabs.setCurrentIndex(2)
    window.table_dataset.setCurrentIndex(window.table_dataset.findData("classifications/tremor"))
    pd.testing.assert_frame_equal(
        window.result_table.model().frame, classification, check_exact=True
    )
    window.table_dataset.setCurrentIndex(window.table_dataset.findData("aggregations/tremor"))
    aggregates = window.aggregation_table.model().frame.set_index("measure")["value"].to_dict()
    if aggregates != results["aggregations"]["tremor"]:
        raise RuntimeError("The separate full-run aggregation table differs from official output")
    window.result_tabs.setCurrentIndex(0)


def _verify_result_export(directory, source, results, quantified):
    from .core import export_results

    export = directory / "results.json"
    export_results(export, results, {"source": source.name})
    saved = json.loads(export.read_text(encoding="utf-8"))
    if len(saved["results"]["quantifications"]["tremor"]["data"]) != len(quantified):
        raise RuntimeError("Result export lost quantified rows")
    return export


def _run_cwa_example():
    from importlib.resources import files

    from .core import analyze, load_sensor_file

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
    return cwa_source, cwa_frame, cwa_results, cwa_quantified


def _verify_combined_modules(frame, t):
    import numpy as np

    from .core import analyze

    combined_input = frame.copy()
    combined_input["green"] = np.sin(2 * np.pi * 1.2 * t)
    for axis in "xyz":
        combined_input[f"accelerometer_{axis}"] = (1 if axis == "z" else 0) + 0.1 * np.sin(t)
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


def _verify_gait_workspace(window, app, cwa_source, cwa_frame, cwa_results):
    window.loaded((str(cwa_source), cwa_frame))
    window.analyzed(cwa_results)
    if window._result_state.display_clock is None:
        raise RuntimeError("CWA recording dates are missing from results")
    if any("per_segment" in path for module, group, path in window._result_state.overview_values):
        raise RuntimeError("Individual gait-segment metadata leaked into Overview")
    timing = window._result_state._timings["quantifications/gait/unfiltered"]
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
    if not gait_axes.collections[0].get_paths() or not getattr(gait_axes, "_paradigma_bars", False):
        raise RuntimeError("CWA result plot was not rendered")
    window.result_table.setCurrentIndex(window.result_table.model().index(0, 0))
    if not window.context_button.isEnabled():
        raise RuntimeError("Explicit gait segment metadata did not enable sensor inspection")
    window.inspect_sensor_context()
    window.sensor_tabs.setCurrentIndex(1)
    if window.sensor_table.model() is None or not window.sensor_table.model().rowCount():
        raise RuntimeError("Gait segment did not reveal its original sensor samples")


def _verify_multiple_recordings(window, directory, frame):
    import numpy as np

    from .core import export_results
    from .inspection import inspect_recording
    from .parallel_analysis import run_parallel_analysis
    from .recordings import load_recordings

    batch_paths = [directory / "subject-part1.csv", directory / "subject-part2.csv"]
    frame.to_csv(batch_paths[0], index=False)
    second = frame.copy()
    second["gyroscope_x"] += 0.002
    second.to_csv(batch_paths[1], index=False)
    batch_sources, batch_frames = load_recordings(batch_paths)
    # Force the tiny validation batch through two spawned workers regardless of
    # build-runner CPU/RAM heuristics, including in the frozen executable.
    batch_results = run_parallel_analysis(
        batch_frames,
        {"pipelines": ["tremor"]},
        logging.Logger("parallel-smoke", logging.INFO),
        Event(),
        workers=2,
    )
    batch_quantified = batch_results["quantifications"]["tremor"]
    if batch_results["errors"] or set(batch_quantified.file_key) != set(batch_frames):
        raise RuntimeError("Multiple-recording analysis lost a recording")
    window.loaded_recordings(
        (
            batch_sources,
            batch_frames,
            {key: inspect_recording(data, "relative_s") for key, data in batch_frames.items()},
        )
    )
    window._result_state.provenance = {
        "source": str(batch_paths[0]),
        "sources": batch_sources,
        "settings": {"pipelines": ["tremor"]},
    }
    window.analyzed(batch_results)
    if window._result_state.display_clock is not None or window.input_recording.isHidden():
        raise RuntimeError("Multiple input selection or relative recording clocks are incorrect")
    window.dataset.setCurrentText("quantifications/tremor")
    position = int(np.flatnonzero(batch_quantified.file_key.eq("recording_002"))[0])
    window.result_table.setCurrentIndex(window.result_table.model().index(position, 0))
    window.inspect_sensor_context()
    if (
        window._sensor_state._sensor_context.source_name != "subject-part2.csv"
        or not len(window._sensor_state.sensor_times)
        or window._sensor_state.sensor_times.min() < 120.0 - 1e-9
    ):
        raise RuntimeError("Sensor context used the wrong source recording")
    batch_export = directory / "batch-results.json"
    export_results(batch_export, batch_results, window._result_state.provenance)
    from .history import load_result_export

    batch_provenance, reopened_batch = load_result_export(batch_export)
    if batch_provenance["sources"] != batch_sources or len(
        reopened_batch["quantifications"]["tremor"]
    ) != len(batch_quantified):
        raise RuntimeError("Multiple-recording export lost sources or rows")


def _verify_empatica_inspection(window, app):
    from importlib.resources import files

    from .core import load_sensor_file

    # The official Empatica example has an empty gyroscope stream.
    # Import it for inspection without inventing missing channels.
    avro_source = files("paradigma_studio") / "data" / "test_data.avro"
    avro_frame = load_sensor_file(avro_source)
    if len(avro_frame) != 115904 or any("gyroscope" in column for column in avro_frame):
        raise RuntimeError("Empatica import lost samples or invented gyroscope channels")
    window.loaded((str(avro_source), avro_frame))
    app.processEvents()
    if window.input_table.model().rowCount() != 115904:
        raise RuntimeError("Empatica samples were not displayed")
    if "require gyroscope" not in window.status.text():
        raise RuntimeError("Empatica analysis requirements were not displayed")
    return avro_frame


def _verify_physilog_preparation():
    from importlib.resources import files

    from .core import analyze, load_sensor_file

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
        raise RuntimeError("Physilog missing samples or recording gaps were not handled correctly")
    physilog_gait = physilog_results["quantifications"]["gait"]["unfiltered"]
    if physilog_gait.empty:
        raise RuntimeError("Physilog example returned no gait measurements")
    return details, physilog_gait


def _verify_saved_run_roundtrip(window, source, export, quantified):
    from PySide6.QtCore import QEventLoop, QTimer

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
    window._run_state.runs, issues = window.history.load()
    if issues or len(window._run_state.runs) != 1:
        raise RuntimeError("Run history did not round-trip")
    window._run_state.selected_run = None
    window.refresh_runs()
    window.navigate(3)
    window.open_run()
    if window._job_state.worker is None:
        raise RuntimeError("Exported result was not reopened in a background worker")
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    window._job_state.worker.finished.connect(loop.quit)
    timer.start(15000)
    loop.exec()
    timer.stop()
    if (
        window._job_state.worker is not None
        or window._result_state.results["quantifications"]["tremor"].shape != quantified.shape
    ):
        raise RuntimeError("Exported run did not reopen correctly")
    if window.pages.currentIndex() != 2 or window._result_state.result_source_frame is not None:
        raise RuntimeError(
            "Reopening a run changed its navigation or reloaded original sensor data"
        )
    window.save_results_button.click()
    if window._job_state.worker is None:
        raise RuntimeError("Local results were not saved in a background worker")
    window._job_state.worker.finished.connect(loop.quit)
    timer.start(15000)
    loop.exec()
    timer.stop()
    if window._job_state.worker is not None:
        raise RuntimeError("Local results save did not finish")
    window._run_state.runs, issues = window.history.load()
    saved_output = window._run_state.runs[0]["outputs"][-1]
    if issues or not saved_output.get("local") or not Path(saved_output["path"]).is_file():
        raise RuntimeError("Local results were not linked to the saved run")
    window._run_state.selected_run = None
    window.refresh_runs()
    window.navigate(3)
    window.open_run()
    if window._job_state.worker is None:
        raise RuntimeError("Local saved run was not reopened from disk")
    window._job_state.worker.finished.connect(loop.quit)
    timer.start(15000)
    loop.exec()
    timer.stop()
    if (
        window._job_state.worker is not None
        or window._result_state.results["quantifications"]["tremor"].shape != quantified.shape
    ):
        raise RuntimeError("Local saved results did not reopen correctly")


def _successful_smoke_report(
    models, quantified, cwa_frame, cwa_quantified, avro_frame, details, physilog_gait
):
    return {
        "status": "passed",
        "paradigma_version": version("paradigma"),
        "app_icon_rendered": True,
        "workspace_navigation_verified": True,
        "integrated_page_controls_verified": True,
        "dropdown_indicator_rendered": True,
        "module_multiselection_verified": True,
        "all_module_execution_verified": True,
        "inline_analysis_help_verified": True,
        "paradigma_acknowledgement_verified": True,
        "studio_licence_verified": True,
        "local_results_saved_verified": True,
        "aggregate_overview_verified": True,
        "original_output_tables_verified": True,
        "tremor_power_log_scale_verified": True,
        "aggregation_tables_verified": True,
        "official_gap_defaults_verified": True,
        "absolute_recording_clock_verified": True,
        "estimated_gait_positions_verified": True,
        "linked_result_selection_verified": True,
        "binary_state_raster_verified": True,
        "presence_only_verified": True,
        "context_footer_verified": True,
        "view_toolbar_verified": True,
        "selected_result_marker_verified": True,
        "calendar_time_controls_verified": True,
        "gait_sensor_context_verified": True,
        "multiple_recordings_verified": True,
        "parallel_recordings_verified": True,
        "run_history_reopened": True,
        "models_loaded": models,
        "quantified_rows": len(quantified),
        "qt_plot_rendered": True,
        "raw_modality_groups_verified": True,
        "export_verified": True,
        "cwa_samples": len(cwa_frame),
        "cwa_gait_rows": len(cwa_quantified),
        "cwa_plot_rendered": True,
        "empatica_samples": len(avro_frame),
        "empatica_inspection_verified": True,
        "physilog_excluded_samples": details["excluded_samples"],
        "physilog_continuous_sections": details["continuous_sections"],
        "physilog_gait_rows": len(physilog_gait),
    }
