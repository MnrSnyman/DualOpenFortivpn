"""Application entry point for the OpenFortiVPN Manager GUI."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from core.app_paths import (
    CONFIG_ROOT,
    DESKTOP_FILE,
    LAUNCHER_NAME,
    LOG_DIR,
    README_FILE,
    ensure_directories,
)

APP_VERSION = "1.0.0"
PYTHON_DEPENDENCIES: List[Tuple[str, str]] = [
    ("yaml", "python3-pyyaml"),
    ("psutil", "python3-psutil"),
    ("keyring", "python3-keyring"),
]
REQUIRED_BINARIES = ["openfortivpn"]
INSTALL_GUIDANCE = {
    "Fedora": "sudo dnf install python3-qt5 python3-pyyaml python3-psutil python3-keyring openfortivpn",
    "Debian/Ubuntu": "sudo apt install python3-pyqt6 python3-yaml python3-psutil python3-keyring openfortivpn",
    "Arch": "sudo pacman -S python-pyqt6 python-yaml python-psutil python-keyring openfortivpn",
}


def detect_qt_binding() -> Tuple[Optional[str], Optional[int]]:
    """Return the available Qt binding (PyQt6 preferred, PyQt5 fallback)."""

    try:
        importlib.import_module("PyQt6")
        return "PyQt6", 6
    except ImportError:
        try:
            importlib.import_module("PyQt5")
            return "PyQt5", 5
        except ImportError:
            return None, None


def check_python_dependencies() -> List[Tuple[str, str]]:
    """Check for required Python modules other than the Qt binding."""

    missing: List[Tuple[str, str]] = []
    for module, package in PYTHON_DEPENDENCIES:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append((module, package))
    return missing


def check_binaries() -> List[str]:
    """Check for required external binaries."""

    from shutil import which

    missing: List[str] = []
    for binary in REQUIRED_BINARIES:
        if which(binary) is None:
            missing.append(binary)
    return missing


def print_dependency_help(missing_modules: List[Tuple[str, str]], qt_binding: Optional[str]) -> None:
    """Print human-friendly installation instructions for missing dependencies."""

    print("OpenFortiVPN Manager cannot start because required dependencies are missing.\n")
    if missing_modules:
        print("Missing Python modules:")
        for module, package in missing_modules:
            print(f" - {module} (install package {package})")
        print()
    if qt_binding is None:
        print("Neither PyQt6 nor PyQt5 could be imported. Install PyQt6 when available, or fall back to PyQt5.")
        print()
    print("Install the prerequisites with one of the following commands:")
    for distro, command in INSTALL_GUIDANCE.items():
        print(f"{distro}: {command}")
    print()
    print("After installing the dependencies, run: python3 openfortivpn_manager.py")


def write_readme() -> None:
    """Generate the runtime README with installation and troubleshooting notes."""

    if README_FILE.exists():
        return
    content = f"""OpenFortiVPN Manager v{APP_VERSION}

Supported distributions:
 - Fedora (PyQt5 packages)
 - Debian and Ubuntu (PyQt6 packages)
 - Arch Linux and derivatives (PyQt6 packages)

Installation instructions:
 Fedora: {INSTALL_GUIDANCE['Fedora']}
 Debian/Ubuntu: {INSTALL_GUIDANCE['Debian/Ubuntu']}
 Arch: {INSTALL_GUIDANCE['Arch']}

Usage:
 1. Run: python3 openfortivpn_manager.py
 2. Create or edit VPN profiles using the toolbar actions.
 3. Connect and monitor sessions from the main table and log pane.

Troubleshooting tips:
 - pkexec authentication agent not found: start a polkit authentication agent or rely on sudo prompts.
 - missing openfortivpn binary: install the openfortivpn package using the command above.
 - cannot import PyQt6: install PyQt6 via pip install PyQt6 or use the python3-qt5 package on Fedora.
 - permission denied when adding routes: ensure sudo or pkexec credentials are available and valid.

Storage locations:
 Configuration: {CONFIG_ROOT}
 Logs: {LOG_DIR}
 README: {README_FILE}

Notes:
 - The application automatically detects whether PyQt6 or PyQt5 is available at runtime.
 - Passwords are stored securely using the system keyring when requested.
"""
    README_FILE.write_text(content + "\n", encoding="utf-8")


def write_launcher() -> None:
    """Create a desktop launcher for integration with desktop environments."""

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
    """Run preflight checks and start the Qt event loop."""

    ensure_directories()
    write_readme()
    write_launcher()

    qt_binding, _ = detect_qt_binding()
    missing_modules = check_python_dependencies()
    if missing_modules or qt_binding is None:
        print_dependency_help(missing_modules, qt_binding)
        sys.exit(1)

    missing_bins = check_binaries()

    from core.qt_compat import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName(LAUNCHER_NAME)

    if missing_bins:
        message = "The following required binaries were not found:\n" + "\n".join(f" - {binary}" for binary in missing_bins)
        print(message)
        QMessageBox.critical(None, "Missing binaries", message)
        sys.exit(1)

    from gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
