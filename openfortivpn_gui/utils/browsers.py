"""Helpers to detect installed web browsers, profiles, and launch commands."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Dict, List

BROWSER_BINARIES = {
    "firefox": "firefox",
    "chrome": "google-chrome",
    "chromium": "chromium",
    "brave": "brave-browser",
    "edge": "microsoft-edge",
}

_CHROMIUM_PROFILE_ROOTS = {
    "chrome": Path.home() / ".config" / "google-chrome",
    "chromium": Path.home() / ".config" / "chromium",
    "brave": Path.home() / ".config" / "BraveSoftware" / "Brave-Browser",
    "edge": Path.home() / ".config" / "microsoft-edge",
}


def detect_browsers() -> List[str]:
    found = [name for name, binary in BROWSER_BINARIES.items() if shutil.which(binary)]
    if not found:
        found.append("default")
    return found


def detect_profiles(browser: str) -> List[str]:
    profiles: list[str] = []
    if browser == "firefox":
        profiles.extend(_firefox_profile_map().keys())
    elif browser in _CHROMIUM_PROFILE_ROOTS:
        base = _CHROMIUM_PROFILE_ROOTS[browser]
        if base.exists():
            for path in base.iterdir():
                if path.is_dir() and (path.name.endswith("Default") or path.name.startswith("Profile")):
                    profiles.append(path.name)
    return sorted(dict.fromkeys(profiles))


def _browser_binary(browser: str | None) -> str | None:
    if not browser:
        return None
    if shutil.which(browser):
        return browser
    return BROWSER_BINARIES.get(browser)


def launch_browser(browser: str | None, profile: str | None, url: str) -> bool:
    """Launch the requested browser/profile combination for SAML auth.

    Returns ``True`` if a dedicated browser command was executed, otherwise ``False``
    if the system fallback handler was used.
    """

    binary = _browser_binary(browser)
    if not binary:
        webbrowser.open(url)
        return False

    cmd = [binary]
    if browser == "firefox":
        if profile:
            profile_path = _firefox_profile_map().get(profile)
            if profile_path:
                cmd.extend(["--no-remote", "--profile", str(profile_path)])
            else:
                cmd.extend(["--no-remote", "-P", profile])
        cmd.extend(["--new-tab", url])
    elif browser in _CHROMIUM_PROFILE_ROOTS:
        if profile:
            cmd.extend(["--profile-directory", profile])
        profile_root = _CHROMIUM_PROFILE_ROOTS[browser]
        if profile_root.exists():
            cmd.append(f"--user-data-dir={profile_root}")
        cmd.append(url)
    else:
        cmd.append(url)

    env = os.environ.copy()
    try:
        subprocess.Popen(cmd, env=env)
        return True
    except OSError:
        webbrowser.open(url)
        return False


def _firefox_profile_map() -> Dict[str, Path]:
    """Parse Firefox profile metadata and return ``{name: absolute_path}``."""

    profiles_ini = Path.home() / ".mozilla" / "firefox" / "profiles.ini"
    if not profiles_ini.exists():
        return {}

    parser = configparser.RawConfigParser()
    parser.optionxform = str  # preserve case of keys like "IsRelative"
    try:
        with profiles_ini.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except OSError:
        return {}

    profiles: Dict[str, Path] = {}
    for section in parser.sections():
        if not section.startswith("Profile"):
            continue
        if not parser.has_option(section, "Name") or not parser.has_option(section, "Path"):
            continue
        name = parser.get(section, "Name")
        path_value = parser.get(section, "Path")
        is_relative = parser.get(section, "IsRelative", fallback="1") != "0"
        path = Path(path_value)
        if is_relative:
            path = profiles_ini.parent / path
        profiles[name] = path.resolve()
    return profiles

