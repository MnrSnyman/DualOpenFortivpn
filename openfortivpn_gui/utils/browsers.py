"""Helpers to detect installed web browsers, profiles, and launch commands."""

from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import List

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
    home = Path.home()
    profiles: list[str] = []
    if browser == "firefox":
        profiles_ini = home / ".mozilla" / "firefox" / "profiles.ini"
        if profiles_ini.exists():
            for line in profiles_ini.read_text(encoding="utf-8").splitlines():
                if line.startswith("Name="):
                    profiles.append(line.split("=", 1)[1].strip())
    elif browser in _CHROMIUM_PROFILE_ROOTS:
        base = _CHROMIUM_PROFILE_ROOTS[browser]
        if base.exists():
            for path in base.iterdir():
                if path.is_dir() and (path.name.endswith("Default") or path.name.startswith("Profile")):
                    profiles.append(path.name)
    return profiles


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
            cmd.extend(["--no-remote", "-P", profile])
        cmd.extend(["--new-tab", url])
    elif browser in _CHROMIUM_PROFILE_ROOTS:
        if profile:
            cmd.append(f"--profile-directory={profile}")
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

