"""Install graph fixtures through the GUI's deferred result-installation path."""

from PySide6.QtCore import QSignalBlocker


def install_graph_results(window, results, *, view=0):
    """Prepare one snapshot and choose its view before the first graph build."""
    with QSignalBlocker(window.result_graph_view):
        window.result_graph_view.setCurrentIndex(view)
    inputs = window._input_state
    source = inputs.recordings if inputs.recordings else inputs.frame
    controller = window._result_controller
    prepared = controller.prepare(results, window._result_state.provenance, source)
    controller.install_prepared(prepared)


def require_graph_data(figure):
    """Navigation/layout fixtures must exercise data, including gated Day views."""
    assert figure.axes
    for axes in figure.axes:
        assert any(len(collection.get_paths()) for collection in axes.collections), (
            "Graph fixture has no visible data",
            getattr(axes, "_paradigma_metric", None),
        )
