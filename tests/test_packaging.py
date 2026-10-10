"""Downloads retain runtime files and reject leftover build/report artifacts."""

from pathlib import Path

import pytest

from scripts.build_desktop import copy_notices, reset_build_outputs
from scripts.check_frozen import check_layout


def bundle(tmp_path):
    executable = tmp_path / "ParaDigMaStudio.exe"
    executable.write_bytes(b"executable")
    internal = tmp_path / "_internal"
    (internal / "paradigma_studio-0.5.31.dist-info").mkdir(parents=True)
    native = internal / "sklearn" / ".libs" / "vcomp140.dll"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"runtime")
    model = internal / "paradigma" / "assets" / "classifier.pkl"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")
    copy_notices(tmp_path)
    (tmp_path / "security").mkdir()
    (tmp_path / "security" / "build-info.json").write_text("{}")
    (tmp_path / "SHA256SUMS.txt").write_text("checksums")
    return executable


def test_download_layout_preserves_models_hidden_runtime_libraries_and_notices(tmp_path):
    executable = bundle(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    check_layout(executable)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


@pytest.mark.parametrize(
    "name", ["performance.json", "ui-performance.json", "pan-performance.json", "old.exe"]
)
def test_download_rejects_reports_and_old_executables(tmp_path, name):
    executable = bundle(tmp_path)
    (tmp_path / name).write_bytes(b"leftover")
    with pytest.raises(RuntimeError, match="Unexpected files"):
        check_layout(executable)


@pytest.mark.parametrize("package", ["paradigma", "openmovement"])
def test_download_rejects_duplicate_python_source(tmp_path, package):
    executable = bundle(tmp_path)
    source = tmp_path / "_internal" / package / "module.py"
    source.parent.mkdir(exist_ok=True)
    source.write_text("duplicated code")
    with pytest.raises(RuntimeError, match="Duplicate loose Python source"):
        check_layout(executable)


@pytest.mark.parametrize(
    "name", ["paradigma_studio-0.5.30.dist-info", "paradigma_desktop-0.5.29.dist-info"]
)
def test_download_rejects_leftover_application_versions(tmp_path, name):
    executable = bundle(tmp_path)
    (tmp_path / "_internal" / name).mkdir()
    with pytest.raises(RuntimeError, match="exactly one current Studio version"):
        check_layout(executable)


def test_rebuild_clears_old_internal_files_reports_and_work_cache_only(tmp_path):
    target = tmp_path / "dist" / "ParaDigMaStudio"
    target.mkdir(parents=True)
    bundle(target)
    (target / "performance.json").write_text("old report")
    work = tmp_path / "build" / "desktop"
    work.mkdir(parents=True)
    (work / "old.toc").write_text("old cache")
    unrelated = tmp_path / "dist" / "another-app.txt"
    unrelated.write_text("keep")
    reset_build_outputs(tmp_path)
    assert not target.exists() and not work.exists()
    assert unrelated.read_text() == "keep"
    # First builds and repeated resets have the same empty starting point.
    reset_build_outputs(tmp_path)


def test_invalid_output_paths_are_rejected_before_deleting_any_outputs(tmp_path):
    target = tmp_path / "dist" / "ParaDigMaStudio"
    target.mkdir(parents=True)
    sentinel = target / "keep.txt"
    sentinel.write_text("keep")
    work = tmp_path / "build" / "desktop"
    work.parent.mkdir()
    work.write_text("not a directory")
    with pytest.raises(ValueError, match="must be a directory"):
        reset_build_outputs(tmp_path)
    assert sentinel.read_text() == "keep"


@pytest.mark.parametrize("workflow", ["windows.yml", "windows-signed.yml"])
def test_ci_benchmarks_write_outside_the_application_download(workflow):
    text = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / workflow).read_text()
    commands = [line for line in text.splitlines() if "run: python scripts/benchmark_" in line]
    assert len(commands) == 4
    assert all("--report build-reports/" in command for command in commands)
    assert "name: ParaDigMaStudio-build-reports\n          path: build-reports/" in text
    assert "path: dist/ParaDigMaStudio/" in text
    assert "include-hidden-files: true" in text
