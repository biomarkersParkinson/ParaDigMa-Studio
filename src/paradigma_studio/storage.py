"""Shared atomic writes and identification of protected recording files."""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


def recording_files(sources):
    """Include TSDF companion binaries alongside each selected sensor file."""
    paths = []
    for source in sources:
        if not source:
            continue
        path = Path(source)
        paths.append(path)
        if path.suffix.lower() == ".json":
            prefix = path.stem.replace("_meta", "")
            paths.extend(path.parent / f"{prefix}_{suffix}.bin" for suffix in ("time", "values"))
    return paths


def same_file(first, second):
    """Match normalized paths, symbolic links and existing hard links."""
    first, second = Path(first), Path(second)
    return first.resolve() == second.resolve() or (
        first.exists() and second.exists() and first.samefile(second)
    )


@contextmanager
def atomic_file(target, *, binary=False, prefix=".paradigma-export-", newline=None):
    """Replace the destination only after a complete, closed temporary write.

    The temporary file stays on the destination filesystem so replacement is
    atomic. Callers choose newline handling and create parent directories when
    appropriate; failed writes leave existing destinations intact.
    """
    target = Path(target)
    fd, temporary = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=target.parent)
    try:
        options = {} if binary else {"encoding": "utf-8", "newline": newline}
        with os.fdopen(fd, "wb" if binary else "w", **options) as stream:
            yield stream
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
