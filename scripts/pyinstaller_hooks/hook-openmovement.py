"""Keep the complete reader package; Python code already lives in the executable."""

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("openmovement", include_py_files=False)
