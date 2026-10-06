"""Build the portable desktop bundle using the repository's packaging options."""
import subprocess
import shutil
import sys
from pathlib import Path


def copy_notices(bundle):
    """Place the packaged canonical notices next to the portable executable."""
    source = Path(__file__).resolve().parents[1] / "src" / "paradigma_desktop" / "data" / "notices"
    for notice in source.iterdir():
        if notice.is_file():
            shutil.copyfile(notice, Path(bundle) / notice.name)


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--icon", str(root / "src" / "paradigma_desktop" / "data" / "app-icon.ico"),
        "--name", "ParaDigMaDesktop", "--collect-all", "paradigma",
        "--collect-all", "openmovement",
        "--additional-hooks-dir", str(root / "scripts" / "pyinstaller_hooks"),
        # The GUI uses Qt, not Tk. Avoid UPX compression of native libraries.
        "--exclude-module", "tkinter", "--noupx",
        # The stable font cache is invalidated when Matplotlib is updated.
        "--copy-metadata", "matplotlib",
        # Include the app icon and licensed recordings for the executable check.
        "--collect-data", "paradigma_desktop",
        # sklearn's Windows importer preloads .libs/vcomp140.dll and
        # .libs/msvcp140.dll. Collect them with their directory structure.
        "--collect-binaries", "sklearn",
        # ParaDigMa's bundled classifier pickles import these modules at runtime.
        "--hidden-import", "sklearn.ensemble._forest",
        "--hidden-import", "sklearn.linear_model._logistic",
        "desktop.py",
    ], cwd=root, check=True)
    copy_notices(root / "dist" / "ParaDigMaDesktop")


if __name__ == "__main__":
    main()
