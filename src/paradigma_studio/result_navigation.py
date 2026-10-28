"""Results rendering hooks for the shared time navigation controls."""

from .time_navigation import TimeToolbar


class ResultsToolbar(TimeToolbar):
    def _prepare_time_scroll(self):
        self.canvas.panning = self.canvas.time_scrolling = True
        self._automatic_bar_y = [
            ax
            for ax in self.canvas.figure.axes
            if getattr(ax, "_paradigma_bars", False) and ax.get_autoscaley_on()
        ]
        for ax in self._automatic_bar_y:
            ax.set_autoscaley_on(False)
        self.canvas.prepare_time_scroll()

    def _finish_time_scroll(self):
        self.canvas.panning = self.canvas.time_scrolling = False
        self.canvas.finish_time_scroll()
        self.restore_automatic_bar_y()
        self._automatic_bar_y = []
