"""Helpers to detect installed web browsers and profiles."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List

BROWSER_BINARIES = {
    "firefox": "firefox",
    "chrome": "google-chrome",
    "chromium": "chromium",
    "brave": "brave-browser",
    "edge": "microsoft-edge",
}


def detect_browsers() -> List[str]:
    found = [name for name, binary in BROWSER_BINARIES.items() if shutil.which(binary)]
    if not found:
        found.append("default")
    return found


def detect_profiles(browser: str) -> List[str]:
    home = Path.home()
    profiles: list[str] = []
    if browser == "firefox":
        profiles_ini = home / ".mozilla" / "firefox" / "profiles.ini"
        if profiles_ini.exists():
            for line in profiles_ini.read_text(encoding="utf-8").splitlines():
                if line.startswith("Name="):
                    profiles.append(line.split("=", 1)[1].strip())
    elif browser in {"chrome", "chromium", "brave", "edge"}:
        base = {
            "chrome": home / ".config" / "google-chrome",
            "chromium": home / ".config" / "chromium",
            "brave": home / ".config" / "BraveSoftware" / "Brave-Browser",
            "edge": home / ".config" / "microsoft-edge",
        }[browser]
        if base.exists():
            for path in base.iterdir():
                if path.is_dir() and (path.name.endswith("Default") or path.name.startswith("Profile")):
                    profiles.append(path.name)
    return profiles

