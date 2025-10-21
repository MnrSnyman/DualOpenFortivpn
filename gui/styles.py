"""Centralized stylesheet definitions for the GUI."""

DARK_THEME_QSS = """
QMainWindow { background-color: #1f232a; }
QToolBar { background-color: #1f232a; border: none; spacing: 6px; }
QToolButton { color: #eceff4; padding: 6px 12px; border-radius: 6px; background-color: #2b303b; }
QToolButton:hover { background-color: #4c566a; }
QHeaderView::section { background-color: #2b303b; color: #eceff4; padding: 6px; border: none; }
QTableWidget { background-color: #2b303b; alternate-background-color: #1f232a; color: #eceff4; gridline-color: #4c566a; }
QTableWidget::item:selected { background-color: #4c566a; }
QGroupBox { border: 1px solid #4c566a; border-radius: 8px; margin-top: 12px; color: #eceff4; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QPlainTextEdit { background-color: #1f232a; color: #eceff4; border: 1px solid #4c566a; border-radius: 6px; }
QLineEdit, QComboBox, QTextEdit { background-color: #2b303b; color: #eceff4; border: 1px solid #4c566a; border-radius: 6px; padding: 4px; }
QPushButton { background-color: #2b303b; color: #eceff4; border: 1px solid #4c566a; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background-color: #4c566a; }
QCheckBox { color: #eceff4; }
"""
