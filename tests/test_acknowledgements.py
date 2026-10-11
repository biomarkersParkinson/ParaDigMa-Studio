"""Upstream attribution fidelity and redistributable acknowledgement assets."""

import hashlib
import os
from importlib.metadata import distribution, version
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QLabel
import pytest

from paradigma_studio.acknowledgements import NOTICES, NOTICE_FILES
from paradigma_studio.app import MainWindow
from scripts.build_desktop import copy_notices
from scripts.check_frozen import check_bundle


def test_licence_and_bibtex_preserve_official_package_notices():
    upstream = distribution("paradigma")
    licence = next(
        upstream.locate_file(f) for f in upstream.files if str(f).endswith("/licenses/LICENSE")
    )
    assert (NOTICES / "LICENSE-paradigma.txt").read_text(encoding="utf-8") == licence.read_text(
        encoding="utf-8"
    )
    bibtex = upstream.read_text("METADATA").split("```bibtex\n", 1)[1].split("```", 1)[0]
    assert (NOTICES / "PARADIGMA-CITATION.bib").read_text(encoding="utf-8") == bibtex
    # Independent hash from the pinned upstream CITATION.cff. Normalize only
    # checkout line endings, which may differ on Windows.
    cff = (NOTICES / "PARADIGMA-CITATION.cff").read_text(encoding="utf-8")
    assert (
        hashlib.sha256(cff.encode("utf-8")).hexdigest()
        == "01d39f6b3ac060e6f1193061106061426124c586214874506c6852beca3cddd4"
    )


def test_about_displays_and_copies_citation_without_changing_workspace(tmp_path):
    application = QApplication.instance() or QApplication([])
    window = MainWindow(history_dir=tmp_path)
    window.navigate(1)
    window.set_modules(["gait", "tremor", "pulse_rate"])
    window.about_button.click()
    dialog = window._acknowledgements_dialog
    assert dialog.isVisible()
    assert dialog.windowTitle() == "About & citations · ParaDigMa Studio"
    assert window.windowTitle() == "ParaDigMa Studio"
    assert window.brand.text() == "ParaDigMa Studio"
    assert not hasattr(window, "brand_caption")
    assert any(
        f"Studio {version('paradigma-studio')}" in widget.text()
        for widget in dialog.findChildren(QLabel)
    )
    assert window.pages.currentIndex() == 1
    assert window.selected_modules() == ["gait", "tremor", "pulse_rate"]
    assert "10.5281/zenodo.13838392" in dialog.acknowledgement.toPlainText()
    displayed_licences = dialog.licence.toPlainText()
    assert (NOTICES / "LICENSE-studio.txt").read_text(encoding="utf-8") in displayed_licences
    assert (NOTICES / "LICENSE-paradigma.txt").read_text(encoding="utf-8") in displayed_licences
    dialog.copy_button.click()
    assert application.clipboard().text() == (NOTICES / "PARADIGMA-CITATION.bib").read_text(
        encoding="utf-8"
    )
    dialog.close()
    window.about_button.click()
    assert window._acknowledgements_dialog is dialog
    window.close()
    assert not dialog.isVisible()
    application.processEvents()


@pytest.mark.parametrize("existing_studio", [False, True])
def test_renamed_app_reopens_existing_default_run_history(tmp_path, monkeypatch, existing_studio):
    from paradigma_studio.history import RunHistory, new_run

    application = QApplication.instance() or QApplication([])
    directory = tmp_path / "ParaDigMaDesktop" / "runs"
    record = new_run("sensor.csv", {"pipelines": ["tremor"]})
    record["status"] = "Completed"
    RunHistory(directory).save(record)
    if existing_studio:
        directory = tmp_path / "ParaDigMaStudio" / "runs"
        record = new_run("studio.csv", {"pipelines": ["gait"]})
        record["status"] = "Completed"
        RunHistory(directory).save(record)
    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda location: str(tmp_path))
    window = MainWindow()
    try:
        assert window.history.directory == directory
        assert [run["id"] for run in window.runs] == [record["id"]]
    finally:
        window.close()
        application.processEvents()


def test_bundle_copies_notices_and_rejects_missing_or_inconsistent_attribution(tmp_path):
    copy_notices(tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == set(NOTICE_FILES)
    for name in NOTICE_FILES:
        assert (tmp_path / name).read_bytes() == (NOTICES / name).read_bytes()
    root_licence = Path(__file__).resolve().parents[1] / "LICENSE"
    assert (tmp_path / "LICENSE-studio.txt").read_bytes() == root_licence.read_bytes()
    metadata = distribution("paradigma-studio").metadata
    assert metadata["License-Expression"] == "Apache-2.0"
    assert "LICENSE" in metadata.get_all("License-File")
    with pytest.raises(RuntimeError, match="Missing or inconsistent ParaDigMa attribution"):
        check_bundle(tmp_path / "ParaDigMaStudio.exe")
    packaged = tmp_path / "_internal" / "paradigma_studio" / "data" / "notices"
    packaged.mkdir(parents=True)
    copy_notices(packaged)
    (tmp_path / "LICENSE-studio.txt").write_text("Incomplete licence", encoding="utf-8")
    with pytest.raises(RuntimeError, match="LICENSE-studio.txt"):
        check_bundle(tmp_path / "ParaDigMaStudio.exe")
    copy_notices(tmp_path)
    (tmp_path / "LICENSE-paradigma.txt").write_text("Incomplete licence", encoding="utf-8")
    with pytest.raises(RuntimeError, match="LICENSE-paradigma.txt"):
        check_bundle(tmp_path / "ParaDigMaStudio.exe")
