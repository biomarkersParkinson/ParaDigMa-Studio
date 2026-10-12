"""On-demand attribution view, shared by source and frozen application builds."""

from importlib.metadata import version
from pathlib import Path

from PySide6.QtGui import (
    QColor,
    QFont,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
)

from .branding import APP_NAME, DISTRIBUTION_NAME
from .theme import LINK_COLOR, light_palette
from .widgets import button, label

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


def _style_links(document: QTextDocument) -> None:
    """Markdown assigns its own anchor format, overriding the widget palette."""
    style = QTextCharFormat()
    style.setForeground(QColor(LINK_COLOR))
    style.setFontUnderline(True)
    block = document.begin()
    while block.isValid():
        fragment_iterator = block.begin()
        while not fragment_iterator.atEnd():
            fragment = fragment_iterator.fragment()
            if fragment.charFormat().isAnchor():
                cursor = QTextCursor(document)
                cursor.setPosition(fragment.position())
                cursor.setPosition(fragment.position() + fragment.length(), QTextCursor.KeepAnchor)
                cursor.mergeCharFormat(style)
            fragment_iterator += 1
        block = block.next()


def _append_licence(document: QTextDocument, title: str, filename: str) -> None:
    cursor = QTextCursor(document)
    cursor.movePosition(QTextCursor.End)
    heading = QTextBlockFormat()
    heading.setHeadingLevel(2)
    heading.setTopMargin(18)
    heading.setBottomMargin(10)
    cursor.insertBlock(heading)
    font = QFont()
    font.setPixelSize(16)
    font.setWeight(QFont.DemiBold)
    style = QTextCharFormat()
    style.setFont(font)
    style.setForeground(QColor("#22324a"))
    cursor.insertText(title, style)
    cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
    cursor.insertText((NOTICES / filename).read_text(encoding="utf-8"))


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
        self.copy_status = label("", "muted")
        footer.addWidget(self.copy_status)
        footer.addStretch()
        self.copy_button = button("Copy BibTeX", self.copy_citation)
        footer.addWidget(self.copy_button)
        footer.addWidget(button("Close", self.close))
        layout.addLayout(footer)
        self.tabs.currentChanged.connect(self._update_citation_actions)
        self._update_citation_actions()

    @staticmethod
    def _browser(markdown, accessible_name):
        browser = QTextBrowser()
        browser.setPalette(light_palette())
        browser.setOpenExternalLinks(True)
        browser.setMarkdown(markdown)
        _style_links(browser.document())
        browser.setAccessibleName(accessible_name)
        return browser

    def _add_citations(self, markdown):
        self.acknowledgement = self._browser(markdown, "ParaDigMa research citations")
        self.tabs.addTab(self.acknowledgement, "Citations")

    def _add_licences(self, markdown):
        self.licence = self._browser(markdown, "Attribution and complete Apache 2.0 licences")
        for title, name in (
            (APP_NAME, "LICENSE-studio.txt"),
            ("ParaDigMa toolbox", "LICENSE-paradigma.txt"),
        ):
            _append_licence(self.licence.document(), title, name)
        self.tabs.addTab(self.licence, "Licences")

    def _update_citation_actions(self, _index=0):
        visible = self.tabs.currentWidget() is self.acknowledgement
        self.copy_button.setVisible(visible)
        self.copy_status.setVisible(visible)

    def copy_citation(self):
        QApplication.clipboard().setText(
            (NOTICES / "PARADIGMA-JOSS-CITATION.bib").read_text(encoding="utf-8")
        )
        self.copy_status.setText("BibTeX citation copied")
