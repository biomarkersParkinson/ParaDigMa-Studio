"""Enforce the physical-line limit for every Python module under src/."""

import sys
from pathlib import Path

MAX_MODULE_LINES = 900
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"


def main(source_root: Path = SOURCE_ROOT) -> int:
    modules = sorted(source_root.rglob("*.py")) if source_root.is_dir() else []
    if not modules:
        print(f"No Python modules found in {source_root}", file=sys.stderr)
        return 1
    oversized = []
    for path in modules:
        with path.open(encoding="utf-8") as source:
            lines = sum(1 for _ in source)
        if lines > MAX_MODULE_LINES:
            oversized.append((path, lines))
    if oversized:
        for path, lines in oversized:
            print(
                f"{path.relative_to(source_root).as_posix()}: {lines} lines "
                f"(maximum {MAX_MODULE_LINES})",
                file=sys.stderr,
            )
        return 1
    print(f"Checked {len(modules)} Python modules: all at or below {MAX_MODULE_LINES} lines.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
