"""Utility helpers for computing and preparing on-disk paths used by the
OpenFortiVPN Manager application."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

CONFIG_DIR_NAME = "OpenFortiVPN-Manager"
CONFIG_ROOT = Path.home() / ".config" / CONFIG_DIR_NAME
LOG_DIR = CONFIG_ROOT / "logs"
CONFIG_FILE = CONFIG_ROOT / "profiles.yaml"
README_FILE = CONFIG_ROOT / "README.txt"
DESKTOP_FILE = Path.home() / ".local" / "share" / "applications" / "OpenFortiVPN-Manager.desktop"
LAUNCHER_NAME = "OpenFortiVPN Manager"


def ensure_directories() -> Tuple[Path, Path]:
    """Ensure configuration and log directories exist before use."""
    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_ROOT, LOG_DIR


def expand_path(path: str) -> Path:
    """Expand environment variables and user references in ``path``."""
    return Path(os.path.expandvars(os.path.expanduser(path))).resolve()
