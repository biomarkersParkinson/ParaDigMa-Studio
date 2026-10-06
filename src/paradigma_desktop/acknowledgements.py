"""On-demand attribution view, shared by source and frozen application builds."""
from importlib.metadata import version
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QTabWidget, QTextBrowser, QVBoxLayout

from .theme import light_palette
from .widgets import button, label, readout


NOTICES = Path(__file__).with_name("data") / "notices"
NOTICE_FILES = ("ACKNOWLEDGEMENTS.md", "LICENSE-paradigma.txt", "PARADIGMA-CITATION.bib", "PARADIGMA-CITATION.cff")


class AcknowledgementsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About & citations · ParaDigMa Desktop")
        self.resize(820, 680)
        self.setMinimumSize(520, 400)
        self.setPalette(light_palette())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(label("ParaDigMa Desktop", "pageTitle"))
        layout.addWidget(label(f"Desktop {version('paradigma-desktop')} · Official ParaDigMa {version('paradigma')}", "muted"))
        tabs = QTabWidget()
        self.acknowledgement = QTextBrowser()
        self.acknowledgement.setPalette(light_palette())
        self.acknowledgement.setOpenExternalLinks(True)
        self.acknowledgement.setMarkdown((NOTICES / "ACKNOWLEDGEMENTS.md").read_text(encoding="utf-8"))
        self.acknowledgement.setAccessibleName("ParaDigMa acknowledgement and research citations")
        tabs.addTab(self.acknowledgement, "Acknowledgement & citations")
        self.licence = readout()
        self.licence.setPalette(light_palette())
        self.licence.setPlainText((NOTICES / "LICENSE-paradigma.txt").read_text(encoding="utf-8"))
        self.licence.setAccessibleName("Complete ParaDigMa Apache 2.0 licence")
        tabs.addTab(self.licence, "Licence")
        layout.addWidget(tabs, 1)
        footer = QHBoxLayout()
        self.copy_button = button("Copy software citation", self.copy_citation)
        footer.addWidget(self.copy_button)
        self.copy_status = label("", "muted")
        footer.addWidget(self.copy_status)
        footer.addStretch()
        footer.addWidget(button("Close", self.close))
        layout.addLayout(footer)

    def copy_citation(self):
        QApplication.clipboard().setText((NOTICES / "PARADIGMA-CITATION.bib").read_text(encoding="utf-8"))
        self.copy_status.setText("BibTeX citation copied")
