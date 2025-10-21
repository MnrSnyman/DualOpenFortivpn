"""Detection of installed browsers and available user profiles for SAML flows."""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from shutil import which


@dataclass
class BrowserInfo:
    key: str
    name: str
    executable: str
    profiles: List[str] = field(default_factory=list)


BROWSER_CANDIDATES = {
    "firefox": {
        "executables": ["firefox"],
        "profile_dir": Path.home() / ".mozilla" / "firefox",
        "profile_parser": "ini",
    },
    "chromium": {
        "executables": ["chromium", "chromium-browser"],
        "profile_dir": Path.home() / ".config" / "chromium",
        "profile_parser": "directories",
    },
    "chrome": {
        "executables": ["google-chrome", "google-chrome-stable"],
        "profile_dir": Path.home() / ".config" / "google-chrome",
        "profile_parser": "directories",
    },
    "edge": {
        "executables": ["microsoft-edge"],
        "profile_dir": Path.home() / ".config" / "microsoft-edge",
        "profile_parser": "directories",
    },
}


def _parse_firefox_profiles(path: Path) -> List[str]:
    config_path = path / "profiles.ini"
    if not config_path.exists():
        return []
    parser = configparser.ConfigParser()
    parser.read(config_path)
    profiles: List[str] = []
    for section in parser.sections():
        if parser.has_option(section, "Name"):
            profiles.append(parser.get(section, "Name"))
    return profiles


def _list_directories(path: Path) -> List[str]:
    if not path.exists():
        return []
    entries = []
    for child in path.iterdir():
        if child.is_dir():
            entries.append(child.name)
    return entries


PROFILE_PARSERS = {
    "ini": _parse_firefox_profiles,
    "directories": _list_directories,
}


def detect_browsers() -> List[BrowserInfo]:
    browsers: List[BrowserInfo] = [BrowserInfo("system", "System Default", "", [])]
    for key, meta in BROWSER_CANDIDATES.items():
        executable = None
        for name in meta["executables"]:
            path = which(name)
            if path:
                executable = path
                break
        if not executable:
            continue
        parser = PROFILE_PARSERS.get(meta.get("profile_parser", "directories"))
        profiles: List[str] = []
        if parser:
            try:
                profiles = parser(meta["profile_dir"])
            except Exception:
                profiles = []
        browsers.append(BrowserInfo(key=key, name=key.capitalize(), executable=executable, profiles=profiles))
    return browsers
