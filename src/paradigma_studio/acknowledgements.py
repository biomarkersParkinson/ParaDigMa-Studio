"""On-demand attribution view, shared by source and frozen application builds."""

from importlib.metadata import version
from pathlib import Path

from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .branding import APP_NAME, DISTRIBUTION_NAME
from .theme import light_palette
from .widgets import ReadableComboBox, button, label, readout

NOTICES = Path(__file__).with_name("data") / "notices"
NOTICE_FILES = (
    "ACKNOWLEDGEMENTS.md",
    "LICENSE-studio.txt",
    "LICENSE-paradigma.txt",
    "PARADIGMA-CITATION.bib",
    "PARADIGMA-CITATION.cff",
    "PARADIGMA-JOSS-CITATION.bib",
)


def notice_sections() -> dict[str, str]:
    """Use the packaged notice as the single source for the About tabs."""
    sections: dict[str, list[str]] = {}
    heading = None
    for line in (NOTICES / "ACKNOWLEDGEMENTS.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            heading = line[3:]
            sections[heading] = []
        elif heading is not None:
            sections[heading].append(line)
    return {title: "\n".join(lines).strip() for title, lines in sections.items()}


class AcknowledgementsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About")
        self.resize(720, 520)
        self.setMinimumSize(520, 400)
        self.setPalette(light_palette())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(label(APP_NAME, "pageTitle"))
        layout.addWidget(
            label(
                f"Studio {version(DISTRIBUTION_NAME)} · Official ParaDigMa {version('paradigma')}",
                "muted",
            )
        )
        sections = notice_sections()
        self.tabs = QTabWidget()
        self.overview = self._browser(sections["Overview"], "Application overview and links")
        self.tabs.addTab(self.overview, "Overview")
        self._add_citations(sections["Citations"])
        self._add_licences(sections["Licences and attribution"])
        layout.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(button("Close", self.close))
        layout.addLayout(footer)

    @staticmethod
    def _browser(markdown, accessible_name):
        browser = QTextBrowser()
        browser.setPalette(light_palette())
        browser.setOpenExternalLinks(True)
        browser.setMarkdown(markdown)
        browser.setAccessibleName(accessible_name)
        return browser

    def _add_citations(self, markdown):
        panel = QWidget()
        content = QVBoxLayout(panel)
        content.setContentsMargins(0, 0, 0, 0)
        self.acknowledgement = self._browser(markdown, "ParaDigMa research citations")
        content.addWidget(self.acknowledgement, 1)
        actions = QHBoxLayout()
        self.copy_button = button("Copy BibTeX", self.copy_citation)
        actions.addWidget(self.copy_button)
        self.copy_status = label("", "muted")
        actions.addWidget(self.copy_status)
        actions.addStretch()
        content.addLayout(actions)
        self.tabs.addTab(panel, "Citations")

    def _add_licences(self, markdown):
        panel = QWidget()
        content = QVBoxLayout(panel)
        content.setContentsMargins(0, 0, 0, 0)
        choice = QHBoxLayout()
        choice.addWidget(label("Software", "muted"))
        self.licence_choice = ReadableComboBox()
        self.licence_choice.addItem(APP_NAME, "LICENSE-studio.txt")
        self.licence_choice.addItem("ParaDigMa toolbox", "LICENSE-paradigma.txt")
        self.licence_choice.setAccessibleName("Software licence")
        choice.addWidget(self.licence_choice, 1)
        content.addLayout(choice)
        document = QTextDocument()
        document.setMarkdown(markdown)
        self._licence_attribution = document.toPlainText()
        self.licence = readout()
        self.licence.setPalette(light_palette())
        self.licence.setAccessibleName("Attribution and complete selected Apache 2.0 licence")
        content.addWidget(self.licence, 1)
        self.licence_choice.currentIndexChanged.connect(self._show_licence)
        self._show_licence()
        self.tabs.addTab(panel, "Licences")

    def _show_licence(self, _index=0):
        self.licence.setPlainText(
            self._licence_attribution
            + f"\n\n{self.licence_choice.currentText()}\n\n"
            + (NOTICES / self.licence_choice.currentData()).read_text(encoding="utf-8")
        )

    def copy_citation(self):
        QApplication.clipboard().setText(
            (NOTICES / "PARADIGMA-JOSS-CITATION.bib").read_text(encoding="utf-8")
        )
        self.copy_status.setText("BibTeX citation copied")
