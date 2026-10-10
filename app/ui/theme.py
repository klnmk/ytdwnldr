from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from app.storage import asset_root

INK = "#171717"
PAPER = "#F0EDE5"
LIME = "#C9F23C"
CYAN = "#A8DFE1"


def apply_theme(app: QApplication):
    for font in (asset_root() / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Golos Text", 10))
    app.setStyle("Fusion")
    stylesheet = """
        QWidget { color: #171717; font-family: 'Golos Text', 'Segoe UI'; font-size: 13px; }
        QMainWindow, QDialog { background: #F0EDE5; }
        QLabel { background: transparent; }
        QLabel[role='muted'] { color: #595951; font-size: 12px; }
        QLabel[role='section'] { font-family: 'Oswald', 'Segoe UI'; font-size: 19px; font-weight: 600; }
        QLabel[role='display'] { font-family: 'Oswald', 'Segoe UI'; font-size: 29px; font-weight: 600; }
        QFrame[role='panel'] { background: #F8F6F0; border: 2px solid #171717; }
        QLineEdit, QComboBox, QSpinBox { background: #FFFEF9; border: 2px solid #171717; border-radius: 1px; padding: 7px 9px; selection-background-color: #A8DFE1; selection-color: #171717; min-height: 19px; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #37666B; }
        QComboBox::drop-down { width: 26px; border: none; }
        QPushButton { background: #F0EDE5; border: 2px solid #171717; border-radius: 1px; padding: 8px 14px; font-weight: 600; min-height: 18px; }
        QPushButton:hover { background: #DDDCD4; }
        QPushButton:pressed { background: #171717; color: #F0EDE5; }
        QPushButton[role='primary'] { background: #C9F23C; }
        QPushButton[role='primary']:hover { background: #D7FC68; }
        QPushButton[role='primary']:pressed { background: #171717; color: #C9F23C; }
        QPushButton[role='cyan'] { background: #A8DFE1; }
        QPushButton[role='plain'] { border: none; padding: 4px 6px; min-height: 15px; font-size: 12px; }
        QPushButton[role='mode'] { background: #F8F6F0; }
        QPushButton[role='mode']:checked { background: #171717; color: #F0EDE5; }
        QPushButton:disabled { color: #77776E; background: #D8D7D1; border-color: #A8A79F; }
        QCheckBox { spacing: 8px; background: transparent; }
        QCheckBox::indicator { width: 16px; height: 16px; border: 2px solid #171717; background: #FFFEF9; }
        QCheckBox::indicator:checked { background: #C9F23C; image: url("CHECK_ASSET"); }
        QTableView, QListView { background: #F8F6F0; alternate-background-color: #ECEAE2; border: none; gridline-color: #D8D7D1; selection-background-color: #D9EDEE; selection-color: #171717; }
        QTableView::item { padding: 5px; }
        QTableView::item:hover { background: #C9E5E6; }
        QHeaderView::section { background: #E7E4DB; border: none; border-bottom: 1px solid #171717; padding: 7px 8px; font-size: 11px; font-weight: 600; }
        QScrollBar:vertical { background: #E7E4DB; width: 10px; margin: 0; }
        QScrollBar::handle:vertical { background: #898980; min-height: 24px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal { background: #E7E4DB; height: 10px; }
        QScrollBar::handle:horizontal { background: #898980; min-width: 24px; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        QToolTip { background: #FFFEF9; border: 1px solid #171717; padding: 5px; }
        QMessageBox { background: #F0EDE5; }
    """
    app.setStyleSheet(stylesheet.replace("CHECK_ASSET", (asset_root() / "check.svg").as_posix()))
