#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-VPN Manager
-----------------

Graphical helper for driving multiple ``openfortivpn`` SAML or credential-based
sessions.

Highlights
~~~~~~~~~~
* PyQt6 interface to create/edit/remove VPN profiles stored in YAML.
* Launches ``openfortivpn`` with SAML auth using ``sudo -S`` (or cached pkexec).
* Inline GUI password prompt (optional session caching) when elevated auth is
  required. Fingerprint/PIN requests trigger a notification dialog instructing
  the user to interact with their system authentication prompt.
* Per‑profile choice of browser/profile for the SAML dance or password-based
  credentials stored securely in the system keyring.
* Per‑profile split routes so specific hosts/subnets are forced through the VPN
  even when overlapping networks exist.
* Optional auto‑reconnect with exponential backoff when the VPN drops.
* Live log panel and per‑profile status column.

The application persists its configuration at
``~/.config/multi_vpn_manager/config.yaml``.
"""
from __future__ import annotations

import os
import sys
import re
import yaml
import time
import queue
import signal
import socket
import shutil
import threading
import subprocess
import shlex
import random
import struct
from dataclasses import dataclass, asdict
from ipaddress import ip_network, ip_address
from typing import Optional, List, Dict, Callable, Tuple
from urllib.parse import urlparse

try:
    import keyring
    from keyring.errors import KeyringError  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    keyring = None  # type: ignore
    KeyringError = Exception  # type: ignore

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QDialog,
    QFormLayout,
    QCheckBox,
    QTextEdit,
    QToolBar,
    QPlainTextEdit,
    QGroupBox,
    QSplitter,
    QFrame,
    QHeaderView,
    QAbstractItemView,
)

CONFIG_DIR = os.path.expanduser("~/.config/multi_vpn_manager")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.yaml")
AUTH_PROMPT = "__VPN_AUTH_PROMPT__"
DESKTOP_ENTRY_NAME = "multi-vpn-manager.desktop"
KEYRING_SERVICE = "multi_vpn_manager"
APP_NAME = "Multi-VPN Manager"
APP_DISPLAY_NAME = "Multi‑VPN Manager"
APP_VERSION = "1.0.0"
__version__ = APP_VERSION

BROWSER_CMDS = {
    "edge": "microsoft-edge",
    "chrome": "google-chrome",
    "chromium": "chromium-browser",
    "firefox": "firefox",
}

DEFAULT_PORT = 8020  # openfortivpn default saml-login port when unspecified


def keyring_available() -> bool:
    return keyring is not None


def get_saved_vpn_password(key: str) -> Optional[str]:
    if not keyring_available():
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, key)  # type: ignore[arg-type]
    except KeyringError:
        return None


def set_saved_vpn_password(key: str, value: str) -> bool:
    if not keyring_available():
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, key, value)  # type: ignore[arg-type]
    except KeyringError:
        return False
    return True


def delete_saved_vpn_password(key: str) -> None:
    if not keyring_available():
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, key)  # type: ignore[arg-type]
    except KeyringError:
        pass


@dataclass
class VPNProfile:
    name: str
    host: str                 # e.g. jb1vpn.nymbis.cloud:443
    browser: str = "edge"     # edge|chrome|chromium|firefox
    profile: Optional[str] = None  # optional browser profile name
    use_saml: bool = True      # toggle SAML authentication flow
    port: Optional[int] = None  # None means use default (--saml-login)
    auto_reconnect: bool = False
    interface: Optional[str] = None  # optional override for the PPP interface
    routes: Optional[List[str]] = None  # raw user routes
    username: Optional[str] = None
    save_password: bool = False

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "VPNProfile":
        return VPNProfile(
            name=d.get("name", "VPN"),
            host=d.get("host", ""),
            browser=d.get("browser", "edge"),
            profile=d.get("profile") if d.get("profile") else None,
            use_saml=d.get("use_saml", True),
            port=d.get("port", None),
            auto_reconnect=d.get("auto_reconnect", False),
            interface=d.get("interface", None),
            routes=d.get("routes", []) or [],
            username=d.get("username"),
            save_password=d.get("save_password", False),
        )


class ConfigStore:
    def __init__(self, path: str):
        self.path = path
        self.vpns: List[VPNProfile] = []

    def load(self):
        if not os.path.exists(self.path):
            self.vpns = []
            return
        with open(self.path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self.vpns = [VPNProfile.from_dict(x) for x in data.get("vpns", [])]

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = {"vpns": [v.to_dict() for v in self.vpns]}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False)
        os.replace(tmp, self.path)


class PasswordDialog(QDialog):
    def __init__(self, prompt: str, parent=None, allow_cache: bool = True, checkbox_text: str = "Remember for this session"):
        super().__init__(parent)
        self.setWindowTitle("Authentication Required")
        self.setModal(True)
        self._password = ""
        self._remember = False

        layout = QVBoxLayout()
        label = QLabel(prompt)
        label.setWordWrap(True)
        layout.addWidget(label)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.pass_edit)

        self.remember_cb = QCheckBox(checkbox_text)
        if allow_cache:
            layout.addWidget(self.remember_cb)
        else:
            self.remember_cb.setVisible(False)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)
        self.pass_edit.setFocus()

    def get_result(self) -> tuple[str, bool]:
        return self.pass_edit.text(), self.remember_cb.isChecked()


class AddEditVPNDialog(QDialog):
    def __init__(self, parent=None, existing_names=None, vpn: Optional[VPNProfile] = None):
        super().__init__(parent)
        self.setWindowTitle("Add VPN" if vpn is None else "Edit VPN")
        self.setMinimumWidth(480)
        self.existing_names = set(existing_names or [])
        if vpn:
            self.existing_names.discard(vpn.name)
        self._vpn = vpn
        self._pending_password: Optional[str] = None
        self._should_forget_password = False
        self._original_name = vpn.name if vpn else None
        self._had_saved_password = False

        self.name_edit = QLineEdit()
        self.host_edit = QLineEdit()
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["edge", "chrome", "chromium", "firefox"])
        self.profile_edit = QLineEdit()
        self.profile_edit.setPlaceholderText("Optional; leave blank for default profile")
        self.auth_mode_combo = QComboBox()
        self.auth_mode_combo.addItem("SAML (browser login)", True)
        self.auth_mode_combo.addItem("Username & Password", False)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(0, 65535)
        self.port_spin.setValue(DEFAULT_PORT)
        self.use_default_port = QCheckBox("Use default SAML listener port (omit '=PORT')")
        self.use_default_port.setChecked(True)
        self.auto_reconnect_cb = QCheckBox("Auto-reconnect")
        self.interface_edit = QLineEdit()
        self.routes_edit = QPlainTextEdit()
        self.routes_edit.setPlainText("")
        self.routes_edit.setPlaceholderText(
            "One host/network/URL per line.\n"
            "Examples:\n"
            "  10.10.10.10\n"
            "  192.168.1.0/24\n"
            "  https://intranet.example.com"
        )
        self.routes_edit.setMinimumHeight(120)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("vpn-user")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Enter password to store securely")
        self.save_password_cb = QCheckBox("Save password securely in the system keyring")
        if not keyring_available():
            self.save_password_cb.setEnabled(False)
            self.save_password_cb.setToolTip("Install python3-keyring to enable secure password storage.")
        self.password_status = QLabel()
        self.password_status.setWordWrap(True)

        general_box = QGroupBox("Connection")
        general_form = QFormLayout()
        general_form.addRow("Name", self.name_edit)
        general_form.addRow("FortiVPN Host (host:port)", self.host_edit)
        general_form.addRow("Authentication", self.auth_mode_combo)
        general_form.addRow("Browser", self.browser_combo)
        general_form.addRow("Browser Profile", self.profile_edit)
        general_form.addRow("Custom Port", self.port_spin)
        general_form.addRow("", self.use_default_port)
        general_form.addRow("Interface (optional)", self.interface_edit)
        general_form.addRow("", self.auto_reconnect_cb)
        general_box.setLayout(general_form)

        credentials_box = QGroupBox("Credentials")
        credentials_form = QFormLayout()
        credentials_form.addRow("Username", self.username_edit)
        credentials_form.addRow("Password", self.password_edit)
        credentials_form.addRow("", self.save_password_cb)
        credentials_form.addRow("", self.password_status)
        credentials_box.setLayout(credentials_form)

        routes_box = QGroupBox("Split Routes")
        routes_layout = QVBoxLayout()
        helper = QLabel("One host, network or URL per line (optional).")
        helper.setStyleSheet("color: #808792;")
        routes_layout.addWidget(helper)
        routes_layout.addWidget(self.routes_edit)
        routes_box.setLayout(routes_layout)

        btns = QHBoxLayout()
        ok_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)

        root = QVBoxLayout()
        root.addWidget(general_box)
        root.addWidget(credentials_box)
        root.addWidget(routes_box)
        root.addLayout(btns)
        self.setLayout(root)

        if vpn:
            self.name_edit.setText(vpn.name)
            self.host_edit.setText(vpn.host)
            self.browser_combo.setCurrentText(vpn.browser)
            self.profile_edit.setText(vpn.profile or "")
            target_mode = 0 if vpn.use_saml else 1
            self.auth_mode_combo.setCurrentIndex(target_mode)
            if vpn.port is None:
                self.use_default_port.setChecked(True)
            else:
                self.use_default_port.setChecked(False)
                self.port_spin.setValue(int(vpn.port))
            self.auto_reconnect_cb.setChecked(bool(vpn.auto_reconnect))
            self.interface_edit.setText(vpn.interface or "")
            if vpn.routes:
                self.routes_edit.setPlainText("\n".join(vpn.routes))
            self.username_edit.setText(vpn.username or "")
            if vpn.save_password and keyring_available() and get_saved_vpn_password(vpn.name) is not None:
                self.save_password_cb.setChecked(True)
                self._had_saved_password = True
                self.password_status.setText("A password is already stored securely. Leave blank to keep it.")
            elif vpn.save_password and not keyring_available():
                self.password_status.setText("Stored password available but keyring backend is currently unavailable.")

        self.auth_mode_combo.currentIndexChanged.connect(self._update_auth_fields)
        self.use_default_port.stateChanged.connect(self._update_auth_fields)
        self.save_password_cb.stateChanged.connect(self._update_auth_fields)
        self._update_auth_fields()

    def _update_auth_fields(self):
        use_saml = self._current_use_saml()
        has_keyring = keyring_available()

        self.use_default_port.setEnabled(use_saml)
        if not use_saml and not self.use_default_port.isChecked():
            self.use_default_port.setChecked(True)
        self.port_spin.setEnabled(use_saml and not self.use_default_port.isChecked())
        self.browser_combo.setEnabled(use_saml)
        self.profile_edit.setEnabled(use_saml)

        self.username_edit.setEnabled(not use_saml)
        can_save = not use_saml and has_keyring
        self.save_password_cb.setEnabled(can_save)
        if not can_save:
            self.save_password_cb.setChecked(False)
        self.password_edit.setEnabled(not use_saml and self.save_password_cb.isChecked() and has_keyring)

        if use_saml:
            self.password_edit.clear()
            self.username_edit.setPlaceholderText("Not required for SAML")
        else:
            self.username_edit.setPlaceholderText("vpn-user")

        if not has_keyring:
            self.password_status.setText("Install python3-keyring to enable secure password storage.")
        elif use_saml:
            self.password_status.setText("SAML connections manage credentials in the browser.")
        elif self.save_password_cb.isChecked():
            if self._had_saved_password and not self.password_edit.text():
                self.password_status.setText("A password is stored securely. Leave blank to keep it or enter a new one.")
            else:
                self.password_status.setText("Enter the password to store securely for this VPN.")
        elif self._had_saved_password:
            self.password_status.setText("Stored password will be removed when you save changes.")
        else:
            self.password_status.clear()

    def _current_use_saml(self) -> bool:
        data = self.auth_mode_combo.currentData()
        return bool(data) if data is not None else True

    def get_vpn(self) -> Optional[VPNProfile]:
        name = self.name_edit.text().strip()
        host = self.host_edit.text().strip()
        browser = self.browser_combo.currentText().strip()
        profile = self.profile_edit.text().strip() or None
        use_saml = self._current_use_saml()
        port = None if (self.use_default_port.isChecked() or not use_saml) else int(self.port_spin.value())
        auto_reconnect = self.auto_reconnect_cb.isChecked()
        interface = self.interface_edit.text().strip() or None
        routes = [r for r in (self.routes_edit.toPlainText().splitlines()) if r.strip()]
        username = self.username_edit.text().strip() or None
        save_password = self.save_password_cb.isChecked() and keyring_available()
        password_text = self.password_edit.text()

        if not name or not host:
            QMessageBox.warning(self, "Missing info", "Please fill in at least Name and Host.")
            return None
        if name in self.existing_names:
            QMessageBox.warning(self, "Duplicate name", f"A VPN named '{name}' already exists.")
            return None
        if not use_saml and not username:
            QMessageBox.warning(self, "Missing credentials", "Username is required when SAML is disabled.")
            return None
        if not use_saml and save_password and not password_text and not self._had_saved_password:
            QMessageBox.warning(self, "Password required", "Enter a password to store securely or uncheck the option.")
            return None

        if use_saml:
            username = None
            save_password = False
            password_text = ""
        elif not save_password:
            self._should_forget_password = self._had_saved_password
        else:
            self._should_forget_password = False

        if save_password and password_text:
            self._pending_password = password_text
        else:
            self._pending_password = None

        return VPNProfile(
            name=name,
            host=host,
            browser=browser,
            profile=profile,
            use_saml=use_saml,
            port=port,
            auto_reconnect=auto_reconnect,
            interface=interface,
            routes=routes,
            username=username,
            save_password=save_password,
        )

    def pending_password(self) -> Optional[str]:
        return self._pending_password

    def should_forget_password(self) -> bool:
        return self._should_forget_password or self._current_use_saml()

    def original_name(self) -> Optional[str]:
        return self._original_name

class VPNProcess:
    def __init__(
        self,
        vpn: VPNProfile,
        log_queue: "queue.Queue[str]",
        password_cb: Optional[Callable[[str], Optional[str]]] = None,
        info_cb: Optional[Callable[[str], None]] = None,
        vpn_password: Optional[str] = None,
        vpn_password_cb: Optional[Callable[[VPNProfile], Optional[str]]] = None,
    ):
        self.vpn = vpn
        self.log_queue = log_queue
        self.proc: Optional[subprocess.Popen] = None
        self.thread: Optional[threading.Thread] = None
        self.status = "Idle"
        self._pending_url = None
        self._should_run = False
        self._current_interface: Optional[str] = None
        self._applied_routes: List[Tuple[str, str, bool]] = []
        self._password_cb = password_cb
        self._info_cb = info_cb
        self._pkexec_path = shutil.which("pkexec")
        self._tunnel_dns_servers: List[str] = []
        self._vpn_password = vpn_password
        self._vpn_password_cb = vpn_password_cb
        self._vpn_password_sent = False

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_queue.put(f"[{ts}] [{self.vpn.name}] {msg}")

    def _browser_cmd(self) -> Optional[List[str]]:
        if not self.vpn.use_saml:
            return None
        b = self.vpn.browser.lower()
        url = self._pending_url
        if not url:
            return None
        profile = (self.vpn.profile or "").strip()
        if b == "edge":
            cmd = [BROWSER_CMDS["edge"]]
            if profile:
                cmd.append(f"--profile-directory={profile}")
            cmd.append(url)
            return cmd
        if b == "chrome":
            cmd = [BROWSER_CMDS["chrome"]]
            if profile:
                cmd.append(f"--profile-directory={profile}")
            cmd.append(url)
            return cmd
        if b == "chromium":
            cmd = [BROWSER_CMDS["chromium"]]
            if profile:
                cmd.append(f"--profile-directory={profile}")
            cmd.append(url)
            return cmd
        if b == "firefox":
            cmd = [BROWSER_CMDS["firefox"]]
            if profile:
                cmd.extend(["-P", profile])
            cmd.append(url)
            return cmd
        return None

    def start(self):
        if self.thread and self.thread.is_alive():
            self._log("Already running.")
            return
        self._should_run = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self._should_run = False
        if self.proc and self.proc.poll() is None:
            self._log("Stopping openfortivpn...")
            if not self._terminate_process(signal.SIGINT):
                self._log("SIGINT did not stop the session; escalating to SIGTERM.")
                if not self._terminate_process(signal.SIGTERM):
                    self._log("SIGTERM failed; forcing SIGKILL.")
                    self._terminate_process(signal.SIGKILL)
        self._cleanup_routes()
        self.status = "Idle"
        self.wait_for_stop(timeout=10)

    def _terminate_process(self, sig: signal.Signals) -> bool:
        if not self.proc:
            return True
        if self._send_signal_local(sig):
            return True
        return self._send_signal_privileged(sig)

    def _send_signal_local(self, sig: signal.Signals) -> bool:
        if not self.proc:
            return True
        try:
            self.proc.send_signal(sig)
        except PermissionError:
            return False
        except ProcessLookupError:
            return True
        except Exception as exc:
            self._log(f"Local signal delivery failed: {exc}")
            return False
        return self._wait_for_process(timeout=5)

    def _send_signal_privileged(self, sig: signal.Signals) -> bool:
        if not self.proc:
            return True
        try:
            sig_enum = sig if isinstance(sig, signal.Signals) else signal.Signals(sig)
        except ValueError:
            sig_enum = signal.SIGTERM
        pid = self.proc.pid
        group_target = f"-{pid}"
        purpose_map = {
            signal.SIGINT: "stop the VPN process",
            signal.SIGTERM: "force-stop the VPN process",
            signal.SIGKILL: "terminate the VPN process immediately",
        }
        purpose = purpose_map.get(sig_enum, "stop the VPN process")
        cmd = ["kill", f"-{sig_enum.name}", "--", group_target]
        if not self._run_privileged(cmd, purpose=purpose):
            cmd = ["kill", f"-{sig_enum.name}", "--", str(pid)]
            if not self._run_privileged(cmd, purpose=purpose):
                return False
        return self._wait_for_process(timeout=5)

    def _wait_for_process(self, timeout: Optional[float] = None) -> bool:
        if not self.proc:
            return True
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return True
        return True

    def wait_for_stop(self, timeout: Optional[float] = None):
        thread = self.thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout)
        if self.thread and not self.thread.is_alive():
            self.thread = None

    # --- internal helpers -------------------------------------------------

    def _run_loop(self):
        backoff = 5
        while self._should_run:
            self._vpn_password_sent = False
            rc = self._run_once()
            if not self._should_run:
                break
            if not self.vpn.auto_reconnect:
                break
            wait_time = backoff
            self.status = "Reconnecting"
            self._log(f"Connection ended (code {rc}). Reconnecting in {wait_time}s...")
            for _ in range(wait_time):
                if not self._should_run:
                    break
                time.sleep(1)
            if not self._should_run:
                break
            if rc == 0:
                backoff = 5
            else:
                backoff = min(backoff * 2, 60)
        self.status = "Idle"
        self._cleanup_routes()
        self.thread = None
        
    def _run_once(self) -> int:
        host = self.vpn.host
        if not host:
            self._log("No host configured; aborting.")
            self.status = "Error"
            return -1

        openfortivpn_path = shutil.which("openfortivpn")
        if not openfortivpn_path:
            self._log("'openfortivpn' not found. Is it installed and in PATH?")
            self.status = "Error"
            return -1

        base_cmd = [openfortivpn_path, host]
        if self.vpn.use_saml:
            if self.vpn.port is None:
                base_cmd.append("--saml-login")
            else:
                base_cmd.append(f"--saml-login={self.vpn.port}")
        else:
            if self.vpn.username:
                base_cmd.append(f"--username={self.vpn.username}")

        use_pkexec = bool(self._pkexec_path)
        if use_pkexec:
            cmd = [self._pkexec_path] + base_cmd
        else:
            cmd = ["sudo", "-S", "-p", AUTH_PROMPT] + base_cmd

        self._log(f"Launching: {' '.join(base_cmd)}")
        self.status = "Connecting"
        self._pending_url = None
        self._current_interface = None
        self._applied_routes.clear()
        self._tunnel_dns_servers = []

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if not use_pkexec else None,
                bufsize=0,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            self._log(f"Required binary not found: {exc}")
            self.status = "Error"
            return -1
        except Exception as exc:
            self._log(f"Failed to start: {exc}")
            self.status = "Error"
            return -1

        rc = self._monitor_process(not use_pkexec)
        self.proc = None
        return rc

    def _monitor_process(self, used_sudo: bool) -> int:
        assert self.proc is not None and self.proc.stdout is not None
        buffer = ""

        def flush_buffer():
            nonlocal buffer
            if buffer:
                self._handle_line(buffer)
                buffer = ""

        while True:
            ch = self.proc.stdout.read(1)
            if ch == "":  # EOF
                flush_buffer()
                break
            if ch in "\r\n":
                flush_buffer()
                continue
            buffer += ch
            if used_sudo and AUTH_PROMPT in buffer:
                buffer = buffer.replace(AUTH_PROMPT, "")
                self._handle_authentication()
        flush_buffer()
        rc = self.proc.wait()
        if self.status == "Connected":
            self._log("Disconnected.")
        else:
            self._log(f"Process exited with code {rc}.")
        self.status = "Idle"
        self._cleanup_routes()
        return rc

    def _handle_line(self, line: str):
        line = line.strip()
        if not line:
            return
        self._log(line)
        lower = line.lower()

        if not self.vpn.use_saml and "vpn" in lower and "password" in lower and lower.rstrip().endswith(":"):
            self.status = "Authenticating"
            self._handle_vpn_password_prompt()

        if "dns server" in lower:
            candidate = ""
            for pattern in (
                r"dns server[^:]*:\s*([0-9a-fA-F:.]+)",
                r"dns server[^0-9a-fA-F]*([0-9a-fA-F:.]+)",
            ):
                dns_match = re.search(pattern, line, re.IGNORECASE)
                if dns_match:
                    candidate = dns_match.group(1).strip()
                    break
            if candidate:
                try:
                    ip_address(candidate)
                except ValueError:
                    candidate = ""
            if candidate and candidate not in self._tunnel_dns_servers:
                self._tunnel_dns_servers.append(candidate)
                self._log(f"Using tunnel DNS server {candidate} for custom route resolution.")

        if self.vpn.use_saml and ("Authenticate at" in line or "open the following URL" in line):
            url = self._extract_url(line)
            if url:
                self._pending_url = url
                self._log(f"Opening browser for SAML: {url}")
                self._launch_browser()
        if any(keyword in line for keyword in ["Tunnel is up", "Connected to VPN", "SSL tunnel connected"]):
            self.status = "Connected"
            self._ensure_routes()
        if "interface" in line.lower():
            match = re.search(r"(ppp\d+|tun\d+|tap\d+)", line, re.IGNORECASE)
            if match:
                self._current_interface = match.group(1)
        if "Sorry, try again" in line:
            self._log("Authentication failed. You may be prompted again.")
        if "finger" in lower:
            self._notify_user("Fingerprint or biometric authentication requested. "
                              "Please authenticate using your system prompt.")
        if "password:" in lower and self.status == "Connecting":
            self._log("Waiting for additional credentials...")
            self.status = "Authenticating"

    def _handle_authentication(self):
        if not self._password_cb:
            self._log("Password prompt encountered but no callback is available.")
            return
        prompt = f"Administrative privileges are required to connect to '{self.vpn.name}'.\n" \
                 "Enter your sudo password or authenticate as requested."
        password = self._password_cb(prompt)
        if password is None:
            self._log("Authentication cancelled by user.")
            self.stop()
            return
        if self.proc and self.proc.stdin:
            try:
                self.status = "Authenticating"
                self.proc.stdin.write(password + "\n")
                self.proc.stdin.flush()
            except Exception as exc:
                self._log(f"Failed to send password: {exc}")

    def _handle_vpn_password_prompt(self):
        if self._vpn_password_sent:
            return
        if self._vpn_password is None and self._vpn_password_cb:
            password = self._vpn_password_cb(self.vpn)
            if password:
                self._vpn_password = password
        if not self._vpn_password:
            self._log("VPN password entry cancelled or unavailable; terminating attempt.")
            self._vpn_password_sent = True
            if self.proc and self.proc.stdin:
                try:
                    self.proc.stdin.write("\n")
                    self.proc.stdin.flush()
                except Exception:
                    pass
            self.status = "Error"
            self._should_run = False
            return
        if self.proc and self.proc.stdin:
            try:
                self.proc.stdin.write(self._vpn_password + "\n")
                self.proc.stdin.flush()
                self._vpn_password_sent = True
            except Exception as exc:
                self._log(f"Failed to send VPN password: {exc}")

    def _notify_user(self, message: str):
        if self._info_cb:
            self._info_cb(message)

    def _launch_browser(self):
        cmd = self._browser_cmd()
        if not cmd:
            self._log("Unable to construct browser command.")
            return
        exe = shutil.which(cmd[0])
        if not exe:
            self._log(f"Browser executable '{cmd[0]}' not found.")
            return
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            self._log(f"Failed to launch browser: {exc}")

    def _ensure_routes(self):
        routes = self.vpn.routes or []
        if not routes:
            return
        interface = self.vpn.interface or self._current_interface
        if not interface:
            self._log("Custom routes defined but interface could not be determined.")
            return
        for raw in routes:
            raw_clean = raw.strip()
            targets = self._resolve_route_targets(raw)
            if targets is None:
                self._log(f"Skipping invalid route entry: {raw}")
                continue
            if not targets:
                self._log(f"Unable to resolve route target '{raw}'.")
                continue
            resolved_list = ", ".join(t for t, _ in targets)
            if resolved_list and raw_clean not in resolved_list.split(", "):
                self._log(f"Route '{raw}' resolved to {resolved_list}.")
            for target, is_v6 in targets:
                purpose = f"add route {target} via {interface}"
                if is_v6:
                    cmd = ["ip", "-6", "route", "add", target, "dev", interface]
                else:
                    cmd = ["ip", "route", "add", target, "dev", interface]
                self._log(f"Requesting elevated access to {purpose}.")
                if self._run_privileged(cmd, purpose=purpose):
                    self._applied_routes.append((target, interface, is_v6))

    def _cleanup_routes(self):
        for target, interface, is_v6 in self._applied_routes:
            purpose = f"remove route {target} via {interface}"
            if is_v6:
                cmd = ["ip", "-6", "route", "del", target, "dev", interface]
            else:
                cmd = ["ip", "route", "del", target, "dev", interface]
            self._log(f"Requesting elevated access to {purpose}.")
            self._run_privileged(cmd, purpose=purpose)
        self._applied_routes.clear()

    def _resolve_route_targets(self, entry: str) -> Optional[List[Tuple[str, bool]]]:
        entry = (entry or "").strip()
        if not entry:
            return None
        try:
            if "://" in entry:
                parsed = urlparse(entry)
                if not parsed.hostname:
                    return None
                entry = parsed.hostname
            if ":" in entry and entry.count(":") == 1 and not entry.startswith("["):
                host_only = urlparse(f"//{entry}").hostname
                if host_only:
                    entry = host_only
            if entry.startswith("[") and entry.endswith("]"):
                entry = entry[1:-1]
        except ValueError:
            return None

        try:
            ip_obj = ip_address(entry)
            return [(str(ip_obj), ip_obj.version == 6)]
        except ValueError:
            pass

        try:
            network = ip_network(entry, strict=False)
            return [(str(network), network.version == 6)]
        except ValueError:
            pass

        if any(c.isspace() for c in entry):
            return None

        resolved_hosts = self._resolve_hostname(entry)
        results: List[Tuple[str, bool]] = []
        seen: set[str] = set()
        for addr in resolved_hosts:
            if addr in seen:
                continue
            seen.add(addr)
            try:
                ip_obj = ip_address(addr)
            except ValueError:
                continue
            results.append((str(ip_obj), ip_obj.version == 6))
        return results

    def _resolve_hostname(self, hostname: str) -> List[str]:
        if not hostname:
            return []
        try:
            ascii_host = hostname.encode("idna").decode("ascii")
        except UnicodeError:
            ascii_host = hostname

        seen: set[str] = set()
        results: List[str] = []

        if self._tunnel_dns_servers:
            for server in self._tunnel_dns_servers:
                for qtype in (1, 28):  # A, AAAA
                    for addr in self._query_dns_server(server, ascii_host, qtype):
                        if addr not in seen:
                            seen.add(addr)
                            results.append(addr)
            if results:
                return results

        try:
            info = socket.getaddrinfo(ascii_host, None)
        except socket.gaierror:
            return results

        for res in info:
            addr = res[4][0]
            if addr not in seen:
                seen.add(addr)
                results.append(addr)
        return results

    def _query_dns_server(self, server: str, hostname: str, qtype: int) -> List[str]:
        if not server:
            return []
        try:
            query_id = random.randint(0, 0xFFFF)
            header = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
            labels = hostname.split(".") if hostname else []
            qname = b"".join(len(label).to_bytes(1, "big") + label.encode("ascii") for label in labels if label) + b"\x00"
            question = qname + struct.pack("!HH", qtype, 1)
            message = header + question

            if ":" in server:
                sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
                address = (server, 53, 0, 0)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                address = (server, 53)
            sock.settimeout(2.0)
            try:
                sock.sendto(message, address)
                data, _ = sock.recvfrom(2048)
            finally:
                sock.close()
        except Exception:
            return []

        if len(data) < 12:
            return []

        try:
            resp_id, flags, qdcount, ancount, _, _ = struct.unpack("!HHHHHH", data[:12])
        except struct.error:
            return []
        if resp_id != query_id:
            return []
        if flags & 0x000F:  # RCODE non-zero
            return []

        offset = 12
        for _ in range(qdcount):
            offset = self._skip_dns_name(data, offset)
            if offset is None or offset + 4 > len(data):
                return []
            offset += 4  # type + class

        results: List[str] = []
        for _ in range(ancount):
            offset = self._skip_dns_name(data, offset)
            if offset is None or offset + 10 > len(data):
                return results
            try:
                rtype, rclass, _, rdlength = struct.unpack("!HHIH", data[offset:offset + 10])
            except struct.error:
                return results
            offset += 10
            if offset + rdlength > len(data):
                return results
            rdata = data[offset:offset + rdlength]
            offset += rdlength

            if rclass != 1:
                continue
            if rtype == 1 and qtype == 1 and rdlength == 4:
                try:
                    results.append(socket.inet_ntop(socket.AF_INET, rdata))
                except (ValueError, OSError):
                    continue
            elif rtype == 28 and qtype == 28 and rdlength == 16:
                try:
                    results.append(socket.inet_ntop(socket.AF_INET6, rdata))
                except (ValueError, OSError):
                    continue
        return results

    @staticmethod
    def _skip_dns_name(packet: bytes, offset: int) -> Optional[int]:
        length = len(packet)
        while True:
            if offset >= length:
                return None
            label_len = packet[offset]
            if label_len == 0:
                return offset + 1
            if label_len & 0xC0 == 0xC0:
                if offset + 1 >= length:
                    return None
                return offset + 2
            offset += 1 + label_len

    def _run_privileged(self, cmd: List[str], purpose: str = "perform this action") -> bool:
        if not cmd:
            return False

        resolved_cmd = cmd[:]
        resolved_cmd[0] = shutil.which(resolved_cmd[0]) or resolved_cmd[0]
        pretty_cmd = shlex.join(resolved_cmd)

        if self._pkexec_path:
            pkexec_cmd = [self._pkexec_path] + resolved_cmd
            self._log(f"Requesting system authentication to {purpose}.")
            self._log(f"Running: {shlex.join(pkexec_cmd)}")
            try:
                proc = subprocess.run(pkexec_cmd, capture_output=True, text=True)
            except Exception as exc:
                self._log(f"Failed to run '{resolved_cmd[0]}' with pkexec: {exc}")
            else:
                if proc.returncode == 0:
                    return True
                stderr_text = (proc.stderr or proc.stdout or "").strip()
                stderr_lower = stderr_text.lower()
                if "no authentication agent" in stderr_lower:
                    self._log("pkexec could not find a graphical authentication agent; falling back to sudo prompts.")
                    self._pkexec_path = None
                elif proc.returncode == 126 or any(key in stderr_lower for key in ["dismissed", "rejected", "authentication failed"]):
                    message = stderr_text or "Privileged command cancelled from system authentication prompt."
                    self._log(message)
                    return False
                else:
                    output = stderr_text or "Unknown error"
                    self._log(f"pkexec failed ({proc.returncode}): {output}. Falling back to sudo prompts.")

        sudo_cmd = ["sudo", "-n"] + resolved_cmd
        self._log(f"Running: {shlex.join(sudo_cmd)}")
        try:
            proc = subprocess.run(sudo_cmd, capture_output=True, text=True)
        except Exception as exc:
            self._log(f"Failed to run '{resolved_cmd[0]}' with sudo: {exc}")
            return False
        if proc.returncode == 0:
            return True

        stderr_text = (proc.stderr or proc.stdout or "").strip()
        stderr_lower = stderr_text.lower()
        auth_indicators = [
            "password",
            "a password is required",
            "authentication required",
            "permission denied",
        ]
        needs_auth = any(key in stderr_lower for key in auth_indicators)

        if needs_auth or (proc.returncode == 1 and not stderr_text):
            self._log(f"Privileged command requires authentication to {purpose}.")
            if not self._password_cb:
                self._log("Unable to escalate privileges (no password handler available).")
                return False
            password = self._password_cb(
                f"Administrative privileges are required to {purpose}.\n"
                f"Command: {pretty_cmd}\n"
                "Enter your sudo password or authenticate as prompted.",
            )
            if password is None:
                self._log("Privileged command cancelled by user.")
                return False
            try:
                sudo_interactive = ["sudo", "-S", "-p", AUTH_PROMPT] + resolved_cmd
                display_cmd = ["sudo", "-S"] + resolved_cmd
                self._log(f"Running: {shlex.join(display_cmd)}")
                proc = subprocess.run(
                    sudo_interactive,
                    input=password + "\n",
                    capture_output=True,
                    text=True,
                )
            except Exception as exc:
                self._log(f"Failed to run '{resolved_cmd[0]}' with sudo: {exc}")
                return False
            if proc.returncode != 0:
                output = (proc.stderr or proc.stdout or "").strip()
                self._log(f"Command failed ({proc.returncode}): {output}")
                return False
            return True

        output = stderr_text or (proc.stdout or "").strip()
        self._log(f"Command failed ({proc.returncode}): {output}")
        return False



    @staticmethod
    def _extract_url(line: str) -> Optional[str]:
        url_re = re.compile(r"https?://[^\s']+")
        match = url_re.search(line)
        return match.group(0) if match else None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_DISPLAY_NAME} {APP_VERSION}")
        self.resize(1080, 680)

        self.config = ConfigStore(CONFIG_PATH)
        self.config.load()

        self.vpn_procs: Dict[str, VPNProcess] = {}
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self._cached_password: Optional[str] = None

        toolbar = QToolBar("Main")
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        add_act = QAction(QIcon.fromTheme("list-add"), "Add VPN", self)
        add_act.triggered.connect(self.add_vpn_dialog)
        toolbar.addAction(add_act)

        edit_act = QAction(QIcon.fromTheme("document-edit"), "Edit Selected", self)
        edit_act.triggered.connect(self.edit_selected_vpn)
        toolbar.addAction(edit_act)

        del_act = QAction(QIcon.fromTheme("edit-delete"), "Remove Selected", self)
        del_act.triggered.connect(self.remove_selected_vpn)
        toolbar.addAction(del_act)

        forget_act = QAction(QIcon.fromTheme("dialog-password"), "Forget Saved Password", self)
        forget_act.triggered.connect(self.clear_cached_password)
        toolbar.addAction(forget_act)

        refresh_act = QAction(QIcon.fromTheme("view-refresh"), "Refresh", self)
        refresh_act.triggered.connect(self.refresh_table)
        toolbar.addAction(refresh_act)

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        header = QLabel("VPN Profiles")
        header.setObjectName("headingLabel")
        main_layout.addWidget(header)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "Name",
            "Host",
            "Port",
            "Auth",
            "Browser",
            "Profile",
            "Username",
            "Auto",
            "Status",
            "Actions",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)

        header_view = self.table.horizontalHeader()
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for idx in range(2, 10):
            mode = QHeaderView.ResizeMode.ResizeToContents
            if idx == 8:
                mode = QHeaderView.ResizeMode.Stretch
            header_view.setSectionResizeMode(idx, mode)

        table_frame = QFrame()
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addWidget(self.table)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_view.setMaximumBlockCount(2000)

        log_frame = QFrame()
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_label = QLabel("Event Log")
        log_label.setObjectName("sectionLabel")
        log_layout.addWidget(log_label)
        log_layout.addWidget(self.log_view)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(table_frame)
        splitter.addWidget(log_frame)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter)
        self.setCentralWidget(central)

        self.statusBar().showMessage("Ready")

        self._apply_theme()

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._drain_logs)
        self.ui_timer.start(200)

        self.refresh_table()

    def _apply_theme(self):
        self.setStyleSheet(
            """
            QMainWindow { background-color: #1f232a; color: #d8dee9; }
            QToolBar { background-color: #242933; border: none; padding: 6px; }
            QToolButton { color: #eceff4; font-weight: 500; }
            QLabel#headingLabel { font-size: 20px; font-weight: 600; color: #eceff4; padding-bottom: 8px; }
            QLabel#sectionLabel { font-size: 14px; font-weight: 600; color: #eceff4; padding: 6px 0; }
            QTableWidget { background-color: #2b303b; color: #eceff4; border: 1px solid #3b4252; border-radius: 8px; }
            QTableWidget::item { padding: 4px; }
            QHeaderView::section { background-color: #242933; color: #eceff4; padding: 6px; border: none; }
            QTextEdit { background-color: #2b303b; color: #eceff4; border: 1px solid #3b4252; border-radius: 8px; }
            QPushButton { background-color: #4c566a; color: #eceff4; border-radius: 4px; padding: 4px 12px; }
            QPushButton:hover { background-color: #5e6b80; }
            QPushButton:pressed { background-color: #3b4252; }
            QGroupBox { border: 1px solid #3b4252; border-radius: 6px; margin-top: 12px; padding: 12px; color: #eceff4; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; font-weight: 600; }
            QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background-color: #2b303b; border: 1px solid #3b4252; border-radius: 4px; padding: 4px; color: #eceff4; }
            QCheckBox { color: #d8dee9; }
            QMessageBox { background-color: #2b303b; }
            """
        )

        self.refresh_table()

    # ---- GUI callbacks ---------------------------------------------------

    def refresh_table(self):
        self.table.setRowCount(0)
        for vpn in self.config.vpns:
            self._add_vpn_row(vpn)

    def _add_vpn_row(self, vpn: VPNProfile):
        row = self.table.rowCount()
        self.table.insertRow(row)

        def make_item(value: str, alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
            item = QTableWidgetItem(value)
            item.setTextAlignment(int(alignment))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return item

        port_text = "-"
        if vpn.use_saml:
            port_text = str(vpn.port) if vpn.port else "Default"
        elif vpn.port:
            port_text = str(vpn.port)

        auth_text = "SAML" if vpn.use_saml else "Password"
        browser_text = vpn.browser if vpn.use_saml else "-"
        profile_text = vpn.profile if vpn.profile else ("Auto" if vpn.use_saml else "-")
        username_text = vpn.username or "-"
        auto_text = "Yes" if vpn.auto_reconnect else "No"

        self.table.setItem(row, 0, make_item(vpn.name))
        self.table.setItem(row, 1, make_item(vpn.host))
        self.table.setItem(row, 2, make_item(port_text, Qt.AlignmentFlag.AlignCenter))
        self.table.setItem(row, 3, make_item(auth_text, Qt.AlignmentFlag.AlignCenter))
        self.table.setItem(row, 4, make_item(browser_text, Qt.AlignmentFlag.AlignCenter))
        self.table.setItem(row, 5, make_item(profile_text, Qt.AlignmentFlag.AlignCenter))
        self.table.setItem(row, 6, make_item(username_text, Qt.AlignmentFlag.AlignCenter))
        self.table.setItem(row, 7, make_item(auto_text, Qt.AlignmentFlag.AlignCenter))

        status_item = make_item(self._status_of(vpn.name), Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 8, status_item)

        action_w = QWidget()
        hb = QHBoxLayout(action_w)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(6)
        btn_conn = QPushButton("Connect")
        btn_disc = QPushButton("Disconnect")
        btn_conn.clicked.connect(lambda _, v=vpn: self.connect_vpn(v))
        btn_disc.clicked.connect(lambda _, v=vpn: self.disconnect_vpn(v))
        hb.addWidget(btn_conn)
        hb.addWidget(btn_disc)
        hb.addStretch()
        self.table.setCellWidget(row, 9, action_w)
    def _status_of(self, name: str) -> str:
        proc = self.vpn_procs.get(name)
        return proc.status if proc else "Idle"

    def add_vpn_dialog(self):
        names = [v.name for v in self.config.vpns]
        dlg = AddEditVPNDialog(self, existing_names=names)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vpn = dlg.get_vpn()
            if vpn:
                pending_password = dlg.pending_password()
                forget = dlg.should_forget_password()
                origin = dlg.original_name()
                self.config.vpns.append(vpn)
                self.config.save()
                self._sync_vpn_password(vpn, pending_password, forget, origin)
                self.refresh_table()
    def edit_selected_vpn(self):
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.table.item(row, 0).text()
        vpn = next((v for v in self.config.vpns if v.name == name), None)
        if not vpn:
            return
        names = [v.name for v in self.config.vpns]
        dlg = AddEditVPNDialog(self, existing_names=names, vpn=vpn)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_vpn = dlg.get_vpn()
            if new_vpn:
                pending_password = dlg.pending_password()
                forget = dlg.should_forget_password()
                origin = dlg.original_name() or vpn.name
                idx = self.config.vpns.index(vpn)
                self.config.vpns[idx] = new_vpn
                self.config.save()
                self._sync_vpn_password(new_vpn, pending_password, forget, origin)
                if vpn.name != new_vpn.name and vpn.name in self.vpn_procs:
                    proc = self.vpn_procs.pop(vpn.name)
                    proc.vpn = new_vpn
                    self.vpn_procs[new_vpn.name] = proc
                self.refresh_table()
    def remove_selected_vpn(self):
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.table.item(row, 0).text()
        vpn = next((v for v in self.config.vpns if v.name == name), None)
        if QMessageBox.question(
            self,
            "Remove VPN",
            f"Delete VPN '{name}' from configuration?",
        ) == QMessageBox.StandardButton.Yes:
            if vpn:
                delete_saved_vpn_password(vpn.name)
            self.config.vpns = [v for v in self.config.vpns if v.name != name]
            self.config.save()
            self.refresh_table()
    def connect_vpn(self, vpn: VPNProfile):
        proc = self.vpn_procs.get(vpn.name)
        if proc and proc.status not in ("Idle", "Error"):
            self._append_log(f"{vpn.name}: already running")
            return

        if not vpn.use_saml and not vpn.username:
            QMessageBox.warning(
                self,
                "Credentials required",
                "Configure a username for password-based VPN profiles before connecting.",
            )
            return

        vpn_password = None
        vpn_password_cb = None
        if not vpn.use_saml:
            vpn_password = self._load_saved_vpn_password(vpn)
            vpn_password_cb = lambda profile=vpn: self._prompt_vpn_password(profile)

        proc = VPNProcess(
            vpn,
            self.log_queue,
            password_cb=self._request_password,
            info_cb=self._show_info,
            vpn_password=vpn_password,
            vpn_password_cb=vpn_password_cb,
        )
        self.vpn_procs[vpn.name] = proc
        proc.start()
        self._update_status_row(vpn.name, "Connecting")
    def disconnect_vpn(self, vpn: VPNProfile):
        proc = self.vpn_procs.get(vpn.name)
        if not proc:
            self._append_log(f"{vpn.name}: not running")
            return
        proc.stop()
        proc.wait_for_stop()
        self._update_status_row(vpn.name, "Idle")

    def clear_cached_password(self):
        self._cached_password = None
        QMessageBox.information(self, "Authentication", "Cached sudo password cleared.")

    # --- helpers ----------------------------------------------------------

    def _request_password(self, prompt: str) -> Optional[str]:
        if self._cached_password:
            return self._cached_password

        # If the request originates from the UI thread we can present the dialog
        # synchronously. This avoids a deadlock where the event loop is blocked
        # waiting for itself while a privileged command is pending.
        if threading.current_thread() is threading.main_thread():
            dlg = PasswordDialog(prompt, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                password, remember = dlg.get_result()
                if password and remember:
                    self._cached_password = password
                return password
            return None

        result: Dict[str, Optional[str]] = {"password": None}
        remember: Dict[str, bool] = {"remember": False}
        finished = threading.Event()

        def ask():
            dlg = PasswordDialog(prompt, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                pwd, rem = dlg.get_result()
                result["password"] = pwd
                remember["remember"] = rem
            finished.set()

        QTimer.singleShot(0, ask)
        finished.wait()

        password = result["password"]
        if password and remember["remember"]:
            self._cached_password = password
        return password

    def _show_info(self, message: str):
        def notify():
            QMessageBox.information(self, "Authentication", message)
        QTimer.singleShot(0, notify)

    def _load_saved_vpn_password(self, vpn: VPNProfile) -> Optional[str]:
        if vpn.use_saml or not vpn.save_password:
            return None
        if not keyring_available():
            self._append_log(f"{vpn.name}: secure password storage unavailable; you will be prompted when connecting.")
            return None
        password = get_saved_vpn_password(vpn.name)
        if password is None:
            self._append_log(f"{vpn.name}: stored password not found; you will be prompted when connecting.")
        return password

    def _prompt_vpn_password(self, vpn: VPNProfile) -> Optional[str]:
        result: Dict[str, Optional[str]] = {"password": None}
        finished = threading.Event()

        def ask():
            prompt = f"Enter VPN password for '{vpn.name}'"
            dlg = PasswordDialog(prompt, self, allow_cache=False)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                pwd, _ = dlg.get_result()
                result["password"] = pwd or None
            finished.set()

        QTimer.singleShot(0, ask)
        finished.wait()
        return result["password"]

    def _sync_vpn_password(
        self, vpn: VPNProfile, pending_password: Optional[str], forget: bool, previous_name: Optional[str]
    ) -> None:
        if vpn.use_saml or not vpn.save_password:
            delete_saved_vpn_password(vpn.name)
            return
        if not keyring_available():
            QMessageBox.warning(
                self,
                "Secure storage unavailable",
                "python3-keyring is not available; VPN passwords cannot be stored securely.",
            )
            delete_saved_vpn_password(vpn.name)
            return

        previous_saved: Optional[str] = None
        if previous_name:
            previous_saved = get_saved_vpn_password(previous_name)
            if previous_name != vpn.name:
                delete_saved_vpn_password(previous_name)

        if forget:
            delete_saved_vpn_password(vpn.name)
            return

        password_to_store = pending_password or previous_saved
        if not password_to_store:
            delete_saved_vpn_password(vpn.name)
            return
        if not set_saved_vpn_password(vpn.name, password_to_store):
            QMessageBox.warning(
                self,
                "Secure storage unavailable",
                "Failed to store the VPN password securely. It will need to be entered when connecting.",
            )
            delete_saved_vpn_password(vpn.name)

    def _update_status_row(self, name: str, status: str):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.text() == name:
                status_item = QTableWidgetItem(status)
                status_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter))
                status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 8, status_item)
                break
    def _append_log(self, line: str):
        self.log_view.append(line)

    def _drain_logs(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self._append_log(line)
                if "] [" in line:
                    try:
                        name_part = line.split("] [", 1)[1]
                        vpn_name = name_part.split("]", 1)[0]
                        lower = line.lower()
                        if any(k in lower for k in ["tunnel is up", "connected to vpn", "ssl tunnel connected"]):
                            self._update_status_row(vpn_name, "Connected")
                        elif "reconnecting" in lower:
                            self._update_status_row(vpn_name, "Reconnecting")
                        elif "waiting for authentication" in lower:
                            self._update_status_row(vpn_name, "Authenticating")
                        elif any(k in lower for k in ["process exited", "disconnected", "error", "failed"]):
                            self._update_status_row(vpn_name, "Idle")
                    except Exception:
                        pass
        except queue.Empty:
            pass

    def _stop_all_vpns(self):
        procs = list(self.vpn_procs.values())
        for proc in procs:
            proc.stop()
        for proc in procs:
            proc.wait_for_stop()
        for name in list(self.vpn_procs.keys()):
            self._update_status_row(name, "Idle")

    def closeEvent(self, event):  # type: ignore[override]
        self._stop_all_vpns()
        super().closeEvent(event)


def ensure_config_exists():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        template = {"vpns": []}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(template, f, sort_keys=False)


def install_desktop_entry():
    try:
        script_path = os.path.abspath(__file__)
    except NameError:
        return

    exec_path = shlex.quote(sys.executable or "python3")
    script_exec = shlex.quote(script_path)
    exec_cmd = f"{exec_path} {script_exec}"

    desktop_entry = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Comment={APP_NAME} {APP_VERSION} launcher for openfortivpn sessions\n"
        f"Exec={exec_cmd}\n"
        "Icon=network-vpn\n"
        "Terminal=false\n"
        "Categories=Network;Utility;\n"
        "StartupNotify=true\n"
    )

    targets = [
        (os.path.expanduser("~/.local/share/applications"), True),
        (os.path.join(os.path.expanduser("~"), "Desktop"), False),
    ]

    for directory, create in targets:
        try:
            if create:
                os.makedirs(directory, exist_ok=True)
            elif not os.path.isdir(directory):
                continue
        except OSError:
            continue
        target_path = os.path.join(directory, DESKTOP_ENTRY_NAME)
        try:
            if os.path.exists(target_path):
                with open(target_path, "r", encoding="utf-8") as existing:
                    if existing.read() == desktop_entry:
                        continue
            with open(target_path, "w", encoding="utf-8") as handle:
                handle.write(desktop_entry)
            os.chmod(target_path, 0o755)
        except OSError:
            continue


def main():
    ensure_config_exists()
    install_desktop_entry()
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
