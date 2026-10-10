"""Record fresh-process startup times and the portable bundle's actual size."""

import argparse
import json
import platform
import statistics
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path


def benchmark(executable, report_path, repetitions=5):
    executable = Path(executable).resolve()
    runs = []
    with tempfile.TemporaryDirectory(prefix="paradigma-benchmark-") as directory:
        for index in range(repetitions):
            report = Path(directory) / f"startup-{index}.json"
            launched = time.perf_counter()
            process = subprocess.Popen(
                [str(executable), "--startup-test", str(report)],
                cwd=directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                while not report.exists() and process.poll() is None:
                    if time.perf_counter() - launched > 45:
                        raise RuntimeError("Packaged application startup timed out.")
                    time.sleep(0.01)
                visible = time.perf_counter() - launched
                stdout, stderr = process.communicate(timeout=15)
            except BaseException:
                process.kill()
                process.communicate()
                raise
            if process.returncode != 0 or not report.exists():
                raise RuntimeError(
                    f"Startup failed (exit {process.returncode}): {stdout}\n{stderr}"
                )
            data = json.loads(report.read_text(encoding="utf-8"))
            if (
                data.get("status") != "passed"
                or data.get("analysis_modules_loaded")
                or data.get("data_modules_loaded")
            ):
                raise RuntimeError(
                    f"Startup did not remain independent of analysis imports: {data}"
                )
            runs.append({**data, "launch_to_report_seconds": visible})
    sizes = defaultdict(int)
    count = 0
    for path in executable.parent.rglob("*"):
        if (
            path.is_file()
            and not path.is_symlink()
            and path.resolve() != Path(report_path).resolve()
        ):
            relative = path.relative_to(executable.parent)
            group = relative.parts[1] if relative.parts[0] == "_internal" else relative.parts[0]
            sizes[group] += path.stat().st_size
            count += 1
    output = {
        "platform": platform.platform(),
        "repetitions": repetitions,
        "conditions": "Fresh processes, empty run history, existing OS/font caches; not a cold-boot measurement.",
        "startup_runs": runs,
        "median_launch_to_report_seconds": statistics.median(
            r["launch_to_report_seconds"] for r in runs
        ),
        "median_first_paint_seconds": statistics.median(r["first_paint_seconds"] for r in runs),
        "bundle_bytes": sum(sizes.values()),
        "bundle_file_count": count,
        "component_bytes": dict(sorted(sizes.items(), key=lambda item: item[1], reverse=True)),
    }
    Path(report_path).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    benchmark(args.executable, args.report, args.repetitions)
