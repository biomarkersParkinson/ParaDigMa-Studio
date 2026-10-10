"""Preserve all official modules, models and metadata without loose source copies."""

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("paradigma", include_py_files=False)
