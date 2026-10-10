"""Check native runtime files and run a smoke test in the built executable."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


NOTICE_FILES = (
    "ACKNOWLEDGEMENTS.md",
    "LICENSE-studio.txt",
    "LICENSE-paradigma.txt",
    "PARADIGMA-CITATION.bib",
    "PARADIGMA-CITATION.cff",
)


def check_layout(executable):
    """Reject reports, duplicate source files and stale app versions in a download."""
    executable = Path(executable).resolve()
    bundle = executable.parent
    allowed = {executable.name, "_internal", "security", "SHA256SUMS.txt", *NOTICE_FILES}
    unexpected = sorted(path.name for path in bundle.iterdir() if path.name not in allowed)
    if unexpected:
        raise RuntimeError("Unexpected files in the app download: " + ", ".join(unexpected))
    internal = bundle / "_internal"
    if not internal.is_dir():
        raise RuntimeError("Missing _internal runtime directory.")
    metadata = [
        path
        for path in internal.glob("*.dist-info")
        if path.name.lower().replace("-", "_").startswith("paradigma_studio_")
    ]
    legacy = [
        path
        for path in internal.glob("*.dist-info")
        if path.name.lower().replace("-", "_").startswith("paradigma_desktop_")
    ]
    if len(metadata) != 1 or legacy:
        raise RuntimeError("The bundle must contain exactly one current Studio version.")
    for package in ("paradigma", "openmovement"):
        if any((internal / package).rglob("*.py")):
            raise RuntimeError(f"Duplicate loose Python source in the bundle: {package}")


def check_bundle(executable):
    executable = Path(executable).resolve()
    for name in NOTICE_FILES:
        notice = executable.parent / name
        packaged = executable.parent / "_internal" / "paradigma_desktop" / "data" / "notices" / name
        if (
            not notice.is_file()
            or not packaged.is_file()
            or notice.read_bytes() != packaged.read_bytes()
        ):
            raise RuntimeError(f"Missing or inconsistent ParaDigMa attribution: {name}")
    check_layout(executable)
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
