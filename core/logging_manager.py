"""Application logging facilities integrating disk persistence and GUI updates."""

from __future__ import annotations

import logging
import threading
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Deque, List

from .app_paths import LOG_DIR

LOG_HISTORY_SIZE = 2000


class _InMemoryHandler(logging.Handler):
    """Logging handler that keeps an in-memory deque and notifies listeners."""

    def __init__(self, history: Deque[str], listeners: List[Callable[[str], None]], lock: threading.Lock) -> None:
        super().__init__()
        self._history = history
        self._listeners = listeners
        self._lock = lock

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        with self._lock:
            self._history.append(message)
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(message)
            except Exception:
                # Listener failures must never propagate to the logging flow.
                logging.getLogger(__name__).exception("Log listener raised an exception")


class LoggingManager:
    """Central logging setup for both file persistence and GUI integration."""

    def __init__(self) -> None:
        self._history: Deque[str] = deque(maxlen=LOG_HISTORY_SIZE)
        self._listeners: List[Callable[[str], None]] = []
        self._lock = threading.Lock()
        self.logger = logging.getLogger("openfortivpn_manager")
        self.logger.setLevel(logging.DEBUG)
        self._configure_handlers()

    def _configure_handlers(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
        file_handler = RotatingFileHandler(Path(LOG_DIR) / "application.log", maxBytes=2 * 1024 * 1024, backupCount=3)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        memory_handler = _InMemoryHandler(self._history, self._listeners, self._lock)
        memory_handler.setFormatter(formatter)
        memory_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(memory_handler)

    def add_listener(self, callback: Callable[[str], None]) -> None:
        """Register a GUI callback that should receive log messages."""
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str], None]) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def history(self) -> Deque[str]:
        """Return the current in-memory log history."""
        return self._history


logging_manager_singleton: LoggingManager | None = None


def get_logging_manager() -> LoggingManager:
    global logging_manager_singleton
    if logging_manager_singleton is None:
        logging_manager_singleton = LoggingManager()
    return logging_manager_singleton
