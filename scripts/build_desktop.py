"""Build the portable desktop bundle using the repository's packaging options."""
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "ParaDigMaDesktop", "--collect-all", "paradigma",
        "--collect-all", "openmovement",
        # Include the licensed upstream CWA recording for the executable check.
        "--collect-data", "paradigma_desktop",
        # sklearn's Windows importer preloads .libs/vcomp140.dll and
        # .libs/msvcp140.dll. Collect them with their directory structure.
        "--collect-binaries", "sklearn",
        # ParaDigMa's bundled classifier pickles import these modules at runtime.
        "--hidden-import", "sklearn.ensemble._forest",
        "--hidden-import", "sklearn.linear_model._logistic",
        "desktop.py",
    ], cwd=root, check=True)


if __name__ == "__main__":
    main()
