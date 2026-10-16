"""Consistent Studio names without losing existing local data or cached fonts."""

import json
from importlib.metadata import distribution

import pytest

from paradigma_studio.branding import USER_DATA_DIRECTORY, user_storage_path


@pytest.mark.parametrize("parts", [("runs",), ("matplotlib", "font-cache")])
@pytest.mark.parametrize("existing", [(), ("legacy",), ("studio",), ("legacy", "studio")])
def test_new_storage_uses_studio_and_existing_legacy_paths_remain_accessible(
    tmp_path, parts, existing
):
    preferred = tmp_path / "ParaDigMaStudio"
    legacy = tmp_path / "ParaDigMaDesktop"
    for part in parts:
        preferred /= part
        legacy /= part
    for name, path in (("studio", preferred), ("legacy", legacy)):
        if name in existing:
            path.mkdir(parents=True)
            (path / "keep.json").write_text(json.dumps({"location": name}))
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    expected = legacy if existing == ("legacy",) else preferred
    assert USER_DATA_DIRECTORY == "ParaDigMaStudio"
    assert user_storage_path(tmp_path, *parts) == expected
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


def test_installed_launcher_uses_studio_name_and_entrypoint():
    launchers = {
        entry.name: entry.value
        for entry in distribution("paradigma-studio").entry_points
        if entry.group == "gui_scripts"
    }
    assert launchers == {"paradigma-studio": "paradigma_studio.app:main"}
