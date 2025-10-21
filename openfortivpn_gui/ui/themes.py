"""Shared stylesheet helpers for the Qt interface."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets

_THEME_DIR = Path(__file__).resolve().parent
_THEME_FILES = {
    "dark": "theme.qss",
    "light": "theme_light.qss",
}


def load_stylesheet(theme: str = "dark") -> str:
    """Return the stylesheet contents for the requested theme."""

    filename = _THEME_FILES.get(theme, _THEME_FILES["dark"])
    path = _THEME_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def apply_stylesheet(app: QtWidgets.QApplication | None, theme: str = "dark") -> None:
    """Apply the themed stylesheet to the application."""

    if app is None:
        return
    stylesheet = load_stylesheet(theme)
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet)
