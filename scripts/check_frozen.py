"""Check native runtime files and run a smoke test in the built executable."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def check_bundle(executable):
    executable = Path(executable).resolve()
    for name in (
        "ACKNOWLEDGEMENTS.md",
        "LICENSE-paradigma.txt",
        "PARADIGMA-CITATION.bib",
        "PARADIGMA-CITATION.cff",
    ):
        notice = executable.parent / name
        packaged = executable.parent / "_internal" / "paradigma_desktop" / "data" / "notices" / name
        if (
            not notice.is_file()
            or not packaged.is_file()
            or notice.read_bytes() != packaged.read_bytes()
        ):
            raise RuntimeError(f"Missing or inconsistent ParaDigMa attribution: {name}")
    if sys.platform == "win32":
        for name in ("vcomp140.dll", "msvcp140.dll"):
            dll = executable.parent / "_internal" / "sklearn" / ".libs" / name
            if not dll.is_file():
                raise RuntimeError(f"Missing scikit-learn runtime library: {dll}")
    # Launch away from the checkout, so local files cannot mask missing assets.
    with tempfile.TemporaryDirectory(prefix="paradigma-bundle-check-") as directory:
        report = Path(directory) / "report.json"
        result = subprocess.run(
            [str(executable), "--smoke-test", str(report)],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if not report.exists():
            raise RuntimeError(
                f"Executable did not write a smoke report (exit {result.returncode}).\n"
                f"{result.stdout}\n{result.stderr}"
            )
        data = json.loads(report.read_text(encoding="utf-8"))
        if result.returncode != 0 or data.get("status") != "passed":
            raise RuntimeError(
                f"Packaged application smoke test failed:\n{json.dumps(data, indent=2)}"
            )
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    check_bundle(sys.argv[1])
