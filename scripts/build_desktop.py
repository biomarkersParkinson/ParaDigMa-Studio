"""Build the portable desktop bundle using the repository's packaging options."""

import subprocess
import shutil
import sys
from pathlib import Path


def copy_notices(bundle):
    """Place the packaged canonical notices next to the portable executable."""
    source = Path(__file__).resolve().parents[1] / "src" / "paradigma_studio" / "data" / "notices"
    for notice in source.iterdir():
        if notice.is_file():
            shutil.copyfile(notice, Path(bundle) / notice.name)


def reset_build_outputs(root):
    """Start from empty app outputs; preserve other builds and source files."""
    root = Path(root).resolve()
    targets = (root / "dist" / "ParaDigMaStudio", root / "build" / "desktop")
    for path in targets:
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError(f"Build output must not be a symlink: {path}")
        if path.exists() and not path.is_dir():
            raise ValueError(f"Build output must be a directory: {path}")
    for path in targets:
        if path.exists():
            shutil.rmtree(path)


def main():
    root = Path(__file__).resolve().parents[1]
    reset_build_outputs(root)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--icon",
            str(root / "src" / "paradigma_studio" / "data" / "app-icon.ico"),
            "--name",
            "ParaDigMaStudio",
            "--distpath",
            str(root / "dist"),
            "--workpath",
            str(root / "build" / "desktop"),
            "--specpath",
            str(root / "build" / "desktop"),
            "--additional-hooks-dir",
            str(root / "scripts" / "pyinstaller_hooks"),
            # The GUI uses Qt, not Tk. Avoid UPX compression of native libraries.
            "--exclude-module",
            "tkinter",
            "--noupx",
            # The stable font cache is invalidated when Matplotlib is updated.
            "--copy-metadata",
            "matplotlib",
            # About displays the installed Studio version in the frozen app.
            "--copy-metadata",
            "paradigma-studio",
            # Include the app icon and licensed recordings for the executable check.
            "--collect-data",
            "paradigma_studio",
            # sklearn's Windows importer preloads .libs/vcomp140.dll and
            # .libs/msvcp140.dll. Collect them with their directory structure.
            "--collect-binaries",
            "sklearn",
            # ParaDigMa's bundled classifier pickles import these modules at runtime.
            "--hidden-import",
            "sklearn.ensemble._forest",
            "--hidden-import",
            "sklearn.linear_model._logistic",
            "desktop.py",
        ],
        cwd=root,
        check=True,
    )
    copy_notices(root / "dist" / "ParaDigMaStudio")


if __name__ == "__main__":
    main()
