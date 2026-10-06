"""Retain fonts between launches of the portable, fixed-directory build."""
import hashlib
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def configure_plot_cache(cache_root):
    # PyInstaller normally replaces MPLCONFIGDIR on every launch to protect
    # one-file builds whose bundled font paths change after every extraction.
    # Our onedir bundle has stable paths. Keep one-file/source behavior intact.
    if not getattr(sys, "frozen", False) or not cache_root:
        return None
    bundle = Path(getattr(sys, "_MEIPASS", ""))
    if bundle.name != "_internal":
        return None
    try:
        identity = f"{bundle.resolve()}|{version('matplotlib')}"
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        directory = Path(cache_root) / "ParaDigMaDesktop" / "matplotlib" / key
        directory.mkdir(parents=True, exist_ok=True)
    except (OSError, PackageNotFoundError):
        # Retain PyInstaller's temporary cache when storage is unavailable;
        # inability to cache fonts must never prevent opening the application.
        return None
    os.environ["MPLCONFIGDIR"] = str(directory)
    return directory
