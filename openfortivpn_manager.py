"""Application entry point for the OpenFortiVPN Manager GUI."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import List, Tuple

from core.app_paths import DESKTOP_FILE, LAUNCHER_NAME, README_FILE, ensure_directories

REQUIRED_MODULES = [
    ("PyQt6", "python3-qt6"),
    ("yaml", "python3-yaml"),
    ("psutil", "python3-psutil"),
    ("keyring", "python3-keyring"),
]
REQUIRED_BINARIES = ["openfortivpn"]


def check_python_dependencies() -> List[Tuple[str, str]]:
    missing: List[Tuple[str, str]] = []
    for module, package in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append((module, package))
    return missing


def check_binaries() -> List[str]:
    from shutil import which

    missing: List[str] = []
    for binary in REQUIRED_BINARIES:
        if which(binary) is None:
            missing.append(binary)
    return missing


def write_readme() -> None:
    if README_FILE.exists():
        return
    content = f"""
OpenFortiVPN Manager
====================

Overview
The OpenFortiVPN Manager provides a graphical interface for creating, editing, and
monitoring multiple OpenFortiVPN connections. Profiles support either SAML or
password-based authentication and expose settings for auto-reconnect, browser
selection, and custom routing.

Requirements
- Python 3
- python3-qt6
- python3-yaml
- python3-psutil
- python3-keyring
- openfortivpn

Setup
1. Ensure the dependencies above are installed. On Debian/Ubuntu run:
   sudo apt install python3 python3-pyqt6 python3-yaml python3-psutil python3-keyring openfortivpn
   On Fedora use:
   sudo dnf install python3 python3-qt6 python3-PyYAML python3-psutil python3-keyring openfortivpn
2. Launch the manager with: python3 openfortivpn_manager.py
3. Add VPN profiles from the toolbar. Populate host, port, authentication type,
   browser selection (for SAML), and optional routes.
4. Use the Connect button beside each profile to establish a tunnel.

Password Storage
Passwords can be securely stored using the system keyring. Use the "Forget Password"
button to remove stored credentials for a profile.

SAML Tips
Ensure a modern browser is installed. The manager will launch the selected browser
when OpenFortiVPN prints the authentication URL. Browser profiles can be selected
for Chromium, Chrome, Edge, and Firefox when detected.

Troubleshooting
- Missing pkexec: The application falls back to sudo prompts.
- Permission errors: Make sure your user can elevate with sudo or pkexec.
- Route conflicts: Review the routes configured for each VPN and adjust as needed.
- Keyring issues: Some desktop environments require a running secrets service.
- DNS issues: Confirm the VPN-provided DNS servers are reachable.

Files
Configuration and logs are stored under ~/.config/OpenFortiVPN-Manager/.
""".strip()
    README_FILE.write_text(content + "\n", encoding="utf-8")


def write_launcher() -> None:
    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    exec_path = Path(sys.argv[0]).resolve()
    content = f"""[Desktop Entry]
Type=Application
Name={LAUNCHER_NAME}
Exec=python3 {exec_path}
Icon=network-vpn
Terminal=false
Categories=Network;
"""
    DESKTOP_FILE.write_text(content, encoding="utf-8")
    os.chmod(DESKTOP_FILE, 0o755)


def main() -> None:
    missing_modules = check_python_dependencies()
    if missing_modules:
        print("Missing Python dependencies:\n" + "\n".join(f"- {module} ({package})" for module, package in missing_modules))
        sys.exit(1)

    from PyQt6.QtWidgets import QApplication, QMessageBox

    missing_bins = check_binaries()
    ensure_directories()
    write_readme()
    write_launcher()

    app = QApplication(sys.argv)
    app.setApplicationName(LAUNCHER_NAME)

    if missing_bins:
        QMessageBox.critical(
            None,
            "Missing binaries",
            "\n".join(["The following required binaries were not found:"] + missing_bins),
        )
        sys.exit(1)

    from gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
