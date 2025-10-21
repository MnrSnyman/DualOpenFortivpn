"""Centralized stylesheet definitions for the GUI."""

DARK_THEME_QSS = """
* {
    font-family: "Noto Sans", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #eceff4;
}

QMainWindow {
    background-color: #1f232a;
}

QToolBar {
    background-color: #1f232a;
    border: none;
    border-bottom: 1px solid #2f3541;
    padding: 8px 12px;
    spacing: 10px;
}

QToolButton {
    background-color: #2b303b;
    border: 1px solid #363c4d;
    border-radius: 10px;
    color: #eceff4;
    padding: 6px 18px;
    font-weight: 600;
}

QToolButton:hover {
    background-color: #4c566a;
    border-color: #4c566a;
}

QToolButton:pressed {
    background-color: #3b4252;
}

QHeaderView::section {
    background-color: #2b303b;
    color: #eceff4;
    padding: 10px 12px;
    border: none;
    border-bottom: 1px solid #343a46;
    font-weight: 600;
}

QTableCornerButton::section {
    background-color: #2b303b;
    border: none;
}

QTableWidget {
    background-color: #1f232a;
    alternate-background-color: #21262f;
    border: 1px solid #2f3541;
    border-radius: 12px;
    gridline-color: #2f3541;
    selection-background-color: #4c566a;
    selection-color: #eceff4;
}

QTableWidget::item:selected {
    background-color: #4c566a;
    color: #eceff4;
}

QPlainTextEdit {
    background-color: #1b1f27;
    border: 1px solid #2f3541;
    border-radius: 12px;
    padding: 8px;
    selection-background-color: #4c566a;
}

QLineEdit,
QComboBox,
QTextEdit,
QSpinBox {
    background-color: #2b303b;
    border: 1px solid #363c4d;
    border-radius: 10px;
    padding: 6px 10px;
    selection-background-color: #4c566a;
}

QLineEdit:focus,
QComboBox:focus,
QTextEdit:focus,
QSpinBox:focus {
    border-color: #4c566a;
}

QComboBox QAbstractItemView {
    background-color: #1f232a;
    border: 1px solid #2f3541;
    selection-background-color: #4c566a;
    selection-color: #eceff4;
}

QPushButton {
    background-color: #2b303b;
    border: 1px solid #363c4d;
    border-radius: 10px;
    padding: 6px 18px;
    font-weight: 600;
    color: #eceff4;
}

QPushButton:hover {
    background-color: #4c566a;
    border-color: #4c566a;
}

QPushButton:pressed {
    background-color: #3b4252;
}

QPushButton#connectButton {
    background-color: #4c566a;
    border-color: #4c566a;
}

QPushButton#connectButton:hover {
    background-color: #5e6a85;
}

QPushButton#disconnectButton {
    background-color: #bf616a;
    border-color: #bf616a;
}

QPushButton#disconnectButton:hover {
    background-color: #c5727b;
}

QGroupBox {
    border: 1px solid #2f3541;
    border-radius: 12px;
    margin-top: 16px;
    padding-top: 12px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 18px;
    padding: 0 6px;
}

QCheckBox {
    color: #eceff4;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid #363c4d;
    background-color: #1f232a;
}

QCheckBox::indicator:checked {
    background-color: #4c566a;
    border-color: #4c566a;
}

QScrollBar:vertical,
QScrollBar:horizontal {
    background: #1b1f27;
    border: none;
    border-radius: 6px;
    margin: 0;
}

QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {
    background: #4c566a;
    border-radius: 6px;
    min-height: 30px;
    min-width: 30px;
}

QScrollBar::add-line,
QScrollBar::sub-line {
    height: 0;
    width: 0;
}

QSplitter::handle {
    background-color: #1f232a;
    border: none;
    margin: 6px 0;
}
"""
