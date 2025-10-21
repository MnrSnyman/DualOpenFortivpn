"""Qt application bootstrap."""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import Sequence

from PySide6 import QtWidgets

from ..core.manager import ConnectionManager
from .main_window import MainWindow
from .themes import apply_stylesheet


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def run_gui(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    app = QtWidgets.QApplication(list(argv))
    apply_stylesheet(app, "dark")
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_loop, args=(loop,), daemon=True)
    thread.start()
    manager = ConnectionManager(loop=loop)
    window = MainWindow(manager, loop)
    window.show()
    exit_code = app.exec()
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=1)
    loop.close()
    return exit_code

