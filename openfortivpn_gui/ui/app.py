"""Qt application bootstrap with Uptime Kuma styling and theme support."""

from __future__ import annotations

import asyncio
import sys
import threading
import pathlib
from typing import Sequence

from PySide6 import QtWidgets, QtCore

from ..core.manager import ConnectionManager
from .main_window import MainWindow


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Run the asyncio loop in a background thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def load_stylesheet(app: QtWidgets.QApplication, theme: str = "dark") -> None:
    """
    Load a QSS stylesheet for the application.
    Supports 'dark' and 'light' themes stored in openfortivpn_gui/ui/.
    """
    base_path = pathlib.Path(__file__).parent / "ui"
    theme_file = base_path / f"theme_{theme}.qss"
    if not theme_file.exists():
        theme_file = base_path / "theme.qss"  # fallback to default
    if theme_file.exists():
        try:
            with open(theme_file, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
                print(f"[INFO] Loaded theme stylesheet: {theme_file.name}")
        except Exception as e:
            print(f"[WARN] Failed to load theme {theme_file}: {e}")


def run_gui(argv: Sequence[str] | None = None) -> int:
    """Main Qt entry point."""
    if argv is None:
        argv = sys.argv

    app = QtWidgets.QApplication(list(argv))
    app.setApplicationName("OpenFortiVPN Manager")

    # Load Uptime Kuma-inspired dark theme
    load_stylesheet(app, "dark")

    # Initialize event loop
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_loop, args=(loop,), daemon=True)
    thread.start()

    # Core connection manager
    manager = ConnectionManager(loop=loop)

    # Create main window
    window = MainWindow(manager, loop)

    # Connect theme toggle if implemented
    if hasattr(window, "theme_toggled"):
        window.theme_toggled.connect(lambda theme: load_stylesheet(app, theme))

    window.show()

    # Run Qt event loop
    exit_code = app.exec()

    # Cleanup async loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=1)
    loop.close()

    return exit_code
