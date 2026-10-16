"""Frozen callback contract shared by the workspace page builders."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkspaceCallbacks:
    update_context_action: Callable[..., Any]
    choose_export: Callable[..., Any]
    clear_runs: Callable[..., Any]
    delete_run: Callable[..., Any]
    graph_clicked: Callable[..., Any]
    hide_sensor_context: Callable[..., Any]
    inspect_input_recording: Callable[..., Any]
    inspect_sensor_context: Callable[..., Any]
    navigate: Callable[..., Any]
    open_file: Callable[..., Any]
    open_run: Callable[..., Any]
    plot: Callable[..., Any]
    reset_origin: Callable[..., Any]
    reset_sensor_context: Callable[..., Any]
    results_tab_changed: Callable[..., Any]
    run_analysis: Callable[..., Any]
    save_results: Callable[..., Any]
    selected_result_series: Callable[..., Any]
    set_input_channels: Callable[..., Any]
    set_sensor_channels: Callable[..., Any]
    show_acknowledgements: Callable[..., Any]
    stop_analysis: Callable[..., Any]
    toggle_analysis_help: Callable[..., Any]
    use_run_parameters: Callable[..., Any]
