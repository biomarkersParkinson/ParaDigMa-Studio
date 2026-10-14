"""Time-of-day labels for a 24-hour mean profile, without invented dates."""

import math

from matplotlib import ticker

from .epoch_axis import EpochHourLocator
from .epoch_profile import format_profile_time


class ProfileTimeFormatter(ticker.Formatter):
    def set_locs(self, locs):
        super().set_locs(locs)
        left, right = self.axis.get_view_interval()
        for value, tick in zip(locs, self.axis.get_major_ticks(len(locs)), strict=True):
            # The pinned ruler aligns to the plots, which have no margin for
            # centered endpoint labels. Keep 00:00 and 24:00 inside the canvas.
            alignment = (
                "left"
                if math.isclose(value, left, rel_tol=0, abs_tol=1e-8)
                else "right"
                if math.isclose(value, right, rel_tol=0, abs_tol=1e-8)
                else "center"
            )
            if tick.label1.get_ha() != alignment:
                tick.label1.set_ha(alignment)

    def __call__(self, value, pos=None):
        return format_profile_time(value)


def style_profile_axis(axis, *, labels=False):
    axis.xaxis.set_major_locator(EpochHourLocator(calendar=False))
    axis.xaxis.set_major_formatter(ProfileTimeFormatter())
    axis.xaxis.set_minor_locator(ticker.NullLocator())
    axis.xaxis.set_minor_formatter(ticker.NullFormatter())
    axis.tick_params(axis="x", labelbottom=labels, labelsize=9, colors="#60728A", pad=6, length=3)
    axis.grid(False, axis="x", which="both")
