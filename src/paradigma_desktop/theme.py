"""Shared visual language for the desktop workspace."""
from pathlib import Path
from PySide6.QtGui import QColor, QPalette


def light_palette():
    palette = QPalette()
    colors = {
        QPalette.Window: "#f4f6fa", QPalette.WindowText: "#22324a",
        QPalette.Base: "#ffffff", QPalette.AlternateBase: "#f8fafc",
        QPalette.Text: "#22324a", QPalette.Button: "#ffffff",
        QPalette.ButtonText: "#22324a", QPalette.Highlight: "#2563a5",
        QPalette.HighlightedText: "#ffffff", QPalette.PlaceholderText: "#68778c",
        QPalette.ToolTipBase: "#ffffff", QPalette.ToolTipText: "#22324a",
    }
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        for role, color in colors.items():
            palette.setColor(group, role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#68778c"))
    return palette

STYLESHEET = """
QWidget { font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; color: #22324a; }
QMainWindow, QWidget#workspace { background: #f4f6fa; }
QFrame#sidebar { background: #17263c; border: none; }
QFrame#sidebar QLabel { color: #adbbce; background: transparent; }
QFrame#sidebar QLabel#brand { color: white; font-size: 20px; font-weight: 600; }
QFrame#sidebar QPushButton { background: transparent; color: #c4cfde; border: none;
    border-radius: 7px; text-align: left; padding: 12px; font-weight: 600; }
QFrame#sidebar QPushButton:hover { background: #253950; }
QFrame#sidebar QPushButton:checked { background: #344960; color: white; }
QFrame#sidebar QPushButton#collapse { color: #adbbce; }
QLabel#pageTitle { font-size: 27px; font-weight: 600; color: #16253a; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; }
QLabel#muted { color: #68778c; }
QLabel#metricValue { font-size: 25px; font-weight: 600; }
QLabel#notice { color: #77561d; background: #fff6e4; border: 1px solid #eddfbf;
    border-radius: 7px; padding: 10px; }
QFrame#card { background: white; border: 1px solid #e1e6ee; border-radius: 10px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QPushButton { background: white; border: 1px solid #d7dfe9; border-radius: 6px;
    padding: 8px 12px; min-height: 18px; }
QPushButton:hover { background: #edf3fa; border-color: #9aadc4; }
QPushButton:pressed, QPushButton:checked { background: #e9f0f8; border-color: #7c95b6; }
QPushButton:disabled { background: #f4f6f9; color: #99a4b4; border-color: #e5e9ef; }
QPushButton#primary { background: #2563a5; color: white; border-color: #2563a5;
    font-weight: 600; padding: 11px 20px; }
QPushButton#primary:hover { background: #1c518b; }
QPushButton#primary:disabled { background: #b3c4d8; border-color: #b3c4d8; color: white; }
QPushButton#module { text-align: left; padding: 14px; min-height: 32px; font-weight: 600; }
QPushButton#helpInfo { padding: 0; min-height: 0; border-radius: 11px;
    background: #edf4fc; color: #21578f; border: 1px solid #adc5df; font-weight: 600; }
QPushButton#helpInfo:hover, QPushButton#helpInfo:checked { background: #d8e8f8; }
QLabel#fieldHelp { color: #33465d; background: #f0f5fb; padding: 10px; border-radius: 6px; }
QPushButton#module:checked { background: #eef5ff; border: 2px solid #2563a5; }
QLineEdit, QComboBox, QPlainTextEdit, QDoubleSpinBox { background: white;
    color: #22324a; border: 1px solid #d7dfe9; border-radius: 5px; padding: 7px;
    selection-background-color: #2563a5; selection-color: white; }
QComboBox { min-height: 22px; padding: 8px 30px 8px 10px; combobox-popup: 0; }
QComboBoxPrivateContainer { background: white; border: 1px solid #d7dfe9; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #2563a5; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right;
    width: 24px; border: none; }
QComboBox::down-arrow { image: url("__DROPDOWN_ICON__"); width: 12px; height: 8px; }
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled { background: #f4f6f9; color: #68778c; }
QComboBox QAbstractItemView { background: white; color: #22324a;
    selection-background-color: #2563a5; selection-color: white;
    border: 1px solid #d7dfe9; outline: none; }
QComboBox QAbstractItemView::item { padding: 8px; min-height: 20px; }
QComboBox QAbstractItemView::item:hover { background: #edf3fa; color: #22324a; }
QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:selected:hover {
    background: #2563a5; color: white; }
QCheckBox { spacing: 9px; padding: 4px 0; }
QListWidget, QTreeWidget { background: white; border: 1px solid #e1e6ee; border-radius: 6px; }
QListWidget::item, QTreeWidget::item { padding: 8px; min-height: 20px; }
QTreeWidget::item { padding: 5px; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #edf3fa; }
QCheckBox::indicator, QListView::indicator, QTreeView::indicator { width: 18px; height: 18px; background: white;
    border: 1px solid #8c9db3; border-radius: 4px; }
QCheckBox::indicator:hover, QListView::indicator:hover, QTreeView::indicator:hover { border-color: #2563a5; }
QCheckBox::indicator:checked, QListView::indicator:checked, QTreeView::indicator:checked { background: #2563a5; border-color: #2563a5;
    image: url("__CHECKMARK_ICON__"); }
QCheckBox::indicator:disabled, QListView::indicator:disabled, QTreeView::indicator:disabled { background: #f4f6f9; border-color: #c6d0de; }
QCheckBox::indicator:checked:disabled, QListView::indicator:checked:disabled, QTreeView::indicator:checked:disabled { background: #8ba9c9; }
QTableView { background: white; alternate-background-color: #f8fafc; border: none;
    gridline-color: #edf0f5; selection-background-color: #e3eefb; selection-color: #16253a; }
QTableView::item { padding: 4px 8px; }
QHeaderView { background: #f8fafc; color: #53657d; }
QHeaderView::section { background: #f8fafc; border: none; border-bottom: 1px solid #e1e6ee;
    padding: 9px; font-weight: 600; color: #53657d; }
QTabWidget::pane { background: white; border: 1px solid #e1e6ee; border-radius: 7px; }
QTabBar::tab { background: transparent; color: #68778c; padding: 10px 18px;
    border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #2563a5; border-bottom-color: #2563a5; }
QTabBar::tab:hover { color: #2563a5; }
QToolBar { background: white; border: none; spacing: 3px; }
QToolButton { background: white; color: #22324a; border: none; border-radius: 5px; padding: 6px; }
QToolButton:hover, QToolButton:checked { background: #e9f0f8; color: #22324a; }
QFrame#graphSettings { background: #f8fafc; border: 1px solid #e1e6ee; border-radius: 7px; }
QFrame#graphSettings QLineEdit { padding: 5px; }
QFrame#graphSettings QPushButton { padding: 5px 8px; }
QLabel#graphError { color: #9d3529; }
QProgressBar { border: none; background: #e7edf5; max-height: 4px; }
QProgressBar::chunk { background: #2563a5; }
QSplitter::handle { background: #edf0f5; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #c6d0de; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: #f4f6fa; height: 10px; }
QScrollBar::handle:horizontal { background: #c6d0de; min-width: 30px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
""".replace("__DROPDOWN_ICON__", (Path(__file__).with_name("data") / "chevron-down.svg").as_posix())
STYLESHEET = STYLESHEET.replace("__CHECKMARK_ICON__", (Path(__file__).with_name("data") / "checkmark.svg").as_posix())


def style_axes(figure, position=(1, 1, 1), sharex=None):
    figure.set_facecolor("white")
    ax = figure.add_subplot(*position, sharex=sharex)
    ax.set_facecolor("white")
    ax.tick_params(colors="#68778c", labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("bottom", "left"):
        ax.spines[side].set_color("#d7dfe9")
    ax.grid(alpha=0.15)
    return ax
