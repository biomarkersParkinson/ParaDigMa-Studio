"""Upstream attribution fidelity and redistributable acknowledgement assets."""
import hashlib
import os
from importlib.metadata import distribution

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
import pytest

from paradigma_desktop.acknowledgements import NOTICES, NOTICE_FILES
from paradigma_desktop.app import MainWindow
from scripts.build_desktop import copy_notices
from scripts.check_frozen import check_bundle


def test_licence_and_bibtex_preserve_official_package_notices():
    upstream = distribution("paradigma")
    licence = next(upstream.locate_file(f) for f in upstream.files if str(f).endswith("/licenses/LICENSE"))
    assert (NOTICES / "LICENSE-paradigma.txt").read_text(encoding="utf-8") == licence.read_text(encoding="utf-8")
    bibtex = upstream.read_text("METADATA").split("```bibtex\n", 1)[1].split("```", 1)[0]
    assert (NOTICES / "PARADIGMA-CITATION.bib").read_text(encoding="utf-8") == bibtex
    # Independent hash from the pinned upstream CITATION.cff. Normalize only
    # checkout line endings, which may differ on Windows.
    cff = (NOTICES / "PARADIGMA-CITATION.cff").read_text(encoding="utf-8")
    assert hashlib.sha256(cff.encode("utf-8")).hexdigest() == "01d39f6b3ac060e6f1193061106061426124c586214874506c6852beca3cddd4"


def test_about_displays_and_copies_citation_without_changing_workspace(tmp_path):
    application = QApplication.instance() or QApplication([])
    window = MainWindow(history_dir=tmp_path)
    window.navigate(1)
    window.set_modules(["gait", "tremor", "pulse_rate"])
    window.about_button.click()
    dialog = window._acknowledgements_dialog
    assert dialog.isVisible()
    assert window.pages.currentIndex() == 1
    assert window.selected_modules() == ["gait", "tremor", "pulse_rate"]
    assert "10.5281/zenodo.13838392" in dialog.acknowledgement.toPlainText()
    assert dialog.licence.toPlainText() == (NOTICES / "LICENSE-paradigma.txt").read_text(encoding="utf-8")
    dialog.copy_button.click()
    assert application.clipboard().text() == (NOTICES / "PARADIGMA-CITATION.bib").read_text(encoding="utf-8")
    dialog.close()
    window.about_button.click()
    assert window._acknowledgements_dialog is dialog
    window.close()
    assert not dialog.isVisible()
    application.processEvents()


def test_bundle_copies_notices_and_rejects_missing_or_inconsistent_attribution(tmp_path):
    copy_notices(tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == set(NOTICE_FILES)
    for name in NOTICE_FILES:
        assert (tmp_path / name).read_bytes() == (NOTICES / name).read_bytes()
    with pytest.raises(RuntimeError, match="Missing or inconsistent ParaDigMa attribution"):
        check_bundle(tmp_path / "ParaDigMaDesktop.exe")
    packaged = tmp_path / "_internal" / "paradigma_desktop" / "data" / "notices"
    packaged.mkdir(parents=True)
    copy_notices(packaged)
    (tmp_path / "LICENSE-paradigma.txt").write_text("Incomplete licence", encoding="utf-8")
    with pytest.raises(RuntimeError, match="LICENSE-paradigma.txt"):
        check_bundle(tmp_path / "ParaDigMaDesktop.exe")
