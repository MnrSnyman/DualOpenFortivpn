"""Logging utilities."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Dict

LOG_DIR = Path("/tmp/openfortivpn-gui")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_logger(name: str, log_file: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if log_file:
        handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
    else:
        log_file = LOG_DIR / f"{name}.log"
        handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers):
        logger.addHandler(handler)
    return logger


def session_log_path(profile_name: str) -> Path:
    safe_name = profile_name.replace("/", "_")
    return LOG_DIR / f"{safe_name}.log"

