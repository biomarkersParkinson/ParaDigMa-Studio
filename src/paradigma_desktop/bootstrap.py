"""Configure the portable font cache before importing any Matplotlib module."""

from PySide6.QtCore import QStandardPaths

from .plot_cache import configure_plot_cache

PLOT_CACHE_DIRECTORY = configure_plot_cache(
    QStandardPaths.writableLocation(QStandardPaths.GenericCacheLocation)
)
