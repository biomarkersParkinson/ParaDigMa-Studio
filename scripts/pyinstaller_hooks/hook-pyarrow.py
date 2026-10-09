"""Keep local Arrow/Parquet support without development headers or RPC APIs.

The default hook collects every Arrow extension and all package data. Flight
and Substrait expose query APIs, unused by pandas/ParaDigMa file loading.
Dataset, compute, filesystem, Parquet codecs and encryption remain available.
Native dependency scanning still resolves libraries needed by these modules
(including libarrow_substrait on Linux). Never delete resolved dependencies.
"""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


def supported_module(name):
    return not any(
        part in {"tests", "flight", "substrait"} or part.endswith(("_flight", "_substrait"))
        for part in name.split(".")
    )


hiddenimports = collect_submodules("pyarrow", filter=supported_module)
excludedimports = [
    "pyarrow.flight",
    "pyarrow._flight",
    "pyarrow.libarrow_python_flight",
    "pyarrow.substrait",
    "pyarrow._substrait",
]
datas = [
    (source, target)
    for source, target in collect_data_files(
        "pyarrow",
        excludes=["include/**", "includes/**", "src/**", "tests/**", "**/*.pxd", "**/*.pyx"],
    )
    # Versioned Linux shared libraries are initially classified as data by
    # collect_data_files; filter them too before native dependency scanning.
    if not any(name in Path(source).name for name in ("flight", "substrait"))
]
binaries = [
    (source, target)
    for source, target in collect_dynamic_libs("pyarrow")
    if not any(name in Path(source).name for name in ("flight", "substrait"))
]
