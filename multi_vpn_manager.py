#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-VPN Manager
-----------------

Graphical helper for driving multiple ``openfortivpn`` SAML sessions.

Highlights
~~~~~~~~~~
* PyQt6 interface to create/edit/remove VPN profiles stored in YAML.
* Launches ``openfortivpn`` with SAML auth using ``sudo -S`` (or cached pkexec).
* Inline GUI password prompt (optional session caching) when elevated auth is
  required. Fingerprint/PIN requests trigger a notification dialog instructing
  the user to interact with their system authentication prompt.
* Per‑profile choice of browser/profile for the SAML dance.
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
from dataclasses import dataclass, asdict
from ipaddress import ip_network, ip_address
from typing import Optional, List, Dict, Callable, Tuple
from urllib.parse import urlparse

from PyQt6.QtCore import QTimer, QSize
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
)

CONFIG_DIR = os.path.expanduser("~/.config/multi_vpn_manager")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.yaml")
AUTH_PROMPT = "__VPN_AUTH_PROMPT__"
DESKTOP_ENTRY_NAME = "multi-vpn-manager.desktop"

BROWSER_CMDS = {
    "edge": "microsoft-edge",
    "chrome": "google-chrome",
    "chromium": "chromium-browser",
    "firefox": "firefox",
}

DEFAULT_PORT = 8020  # openfortivpn default saml-login port when unspecified

def _normalise_route_entry(entry: str) -> Optional[str]:
    entry = (entry or "").strip()
    if not entry:
        return None
    # Accept URL/hostname/IP/CIDR. Convert URLs and hostnames to IP/CIDR strings.
    try:
        if "://" in entry:
            parsed = urlparse(entry)
            if not parsed.hostname:
                return None
            entry = parsed.hostname
        if "/" in entry:
            network = ip_network(entry, strict=False)
            return str(network)
        # If entry is host name resolve to IPv4 address.
        try:
            ip = ip_address(entry)
            return str(ip)
        except ValueError:
            pass
    except ValueError:
        try:
            info = socket.getaddrinfo(entry, None, socket.AF_INET)
        except socket.gaierror:
            return None
        if info:
            return info[0][4][0]
    return entry


@dataclass
class VPNProfile:
    name: str
    host: str                 # e.g. jb1vpn.nymbis.cloud:443
    browser: str = "edge"     # edge|chrome|chromium|firefox
    profile: str = "Default"  # browser profile (Edge/Chrome) or Firefox profile name
    use_saml: bool = True      # toggle SAML authentication flow
    port: Optional[int] = None  # None means use default (--saml-login)
    auto_reconnect: bool = False
    interface: Optional[str] = None  # optional override for the PPP interface
    routes: Optional[List[str]] = None  # raw user routes

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "VPNProfile":
        return VPNProfile(
            name=d.get("name", "VPN"),
            host=d.get("host", ""),
            browser=d.get("browser", "edge"),
            profile=d.get("profile", "Default"),
            use_saml=d.get("use_saml", True),
            port=d.get("port", None),
            auto_reconnect=d.get("auto_reconnect", False),
            interface=d.get("interface", None),
            routes=d.get("routes", []) or [],
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
    def __init__(self, prompt: str, parent=None):
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

        self.remember_cb = QCheckBox("Remember for this session")
        layout.addWidget(self.remember_cb)

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

        self.name_edit = QLineEdit()
        self.host_edit = QLineEdit()
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["edge", "chrome", "chromium", "firefox"])
        self.profile_edit = QLineEdit()
        self.use_saml_cb = QCheckBox("Use SAML authentication")
        self.use_saml_cb.setChecked(True)
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
            "  10.10.10.10\n  192.168.1.0/24\n  https://intranet.example.com"
        )

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("FortiVPN Host (host:port)", self.host_edit)
        form.addRow("", self.use_saml_cb)
        form.addRow("Browser", self.browser_combo)
        form.addRow("Browser Profile", self.profile_edit)
        form.addRow("Custom Port", self.port_spin)
        form.addRow("", self.use_default_port)
        form.addRow("Interface (optional)", self.interface_edit)
        form.addRow("", self.auto_reconnect_cb)
        form.addRow("Split Routes", self.routes_edit)

        btns = QHBoxLayout()
        ok_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)

        root = QVBoxLayout()
        root.addLayout(form)
        root.addLayout(btns)
        self.setLayout(root)

        if vpn:
            self.name_edit.setText(vpn.name)
            self.host_edit.setText(vpn.host)
            self.browser_combo.setCurrentText(vpn.browser)
            self.profile_edit.setText(vpn.profile or "")
            self.use_saml_cb.setChecked(bool(vpn.use_saml))
            if vpn.port is None:
                self.use_default_port.setChecked(True)
            else:
                self.use_default_port.setChecked(False)
                self.port_spin.setValue(int(vpn.port))
            self.auto_reconnect_cb.setChecked(bool(vpn.auto_reconnect))
            self.interface_edit.setText(vpn.interface or "")
            if vpn.routes:
                self.routes_edit.setPlainText("\n".join(vpn.routes))

        self.use_saml_cb.stateChanged.connect(self._toggle_port)
        self.use_default_port.stateChanged.connect(self._toggle_port)
        self._toggle_port()

    def _toggle_port(self):
        use_saml = self.use_saml_cb.isChecked()
        self.use_default_port.setEnabled(use_saml)
        if not use_saml:
            if not self.use_default_port.isChecked():
                self.use_default_port.setChecked(True)
        self.port_spin.setEnabled(use_saml and not self.use_default_port.isChecked())

    def get_vpn(self) -> Optional[VPNProfile]:
        name = self.name_edit.text().strip()
        host = self.host_edit.text().strip()
        browser = self.browser_combo.currentText().strip()
        profile = self.profile_edit.text().strip() or "Default"
        use_saml = self.use_saml_cb.isChecked()
        port = None if (self.use_default_port.isChecked() or not use_saml) else int(self.port_spin.value())
        auto_reconnect = self.auto_reconnect_cb.isChecked()
        interface = self.interface_edit.text().strip() or None
        routes = [r for r in (self.routes_edit.toPlainText().splitlines()) if r.strip()]

        if not name or not host:
            QMessageBox.warning(self, "Missing info", "Please fill in at least Name and Host.")
            return None
        if name in self.existing_names:
            QMessageBox.warning(self, "Duplicate name", f"A VPN named '{name}' already exists.")
            return None
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
        )


class VPNProcess:
    def __init__(
        self,
        vpn: VPNProfile,
        log_queue: "queue.Queue[str]",
        password_cb: Optional[Callable[[str], Optional[str]]] = None,
        info_cb: Optional[Callable[[str], None]] = None,
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
        if b == "edge":
            return [BROWSER_CMDS["edge"], f"--profile-directory={self.vpn.profile}", url]
        if b == "chrome":
            return [BROWSER_CMDS["chrome"], f"--profile-directory={self.vpn.profile}", url]
        if b == "chromium":
            return [BROWSER_CMDS["chromium"], f"--profile-directory={self.vpn.profile}", url]
        if b == "firefox":
            return [BROWSER_CMDS["firefox"], "-P", self.vpn.profile, url]
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
            try:
                self._log("Stopping openfortivpn...")
                self.proc.send_signal(signal.SIGINT)
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.terminate()
            except Exception as exc:
                self._log(f"Error stopping: {exc}")
        self._cleanup_routes()
        self.status = "Idle"

    # --- internal helpers -------------------------------------------------

    def _run_loop(self):
        backoff = 5
        while self._should_run:
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

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if not use_pkexec else None,
                bufsize=0,
                text=True,
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
        if "finger" in line.lower():
            self._notify_user("Fingerprint or biometric authentication requested. "
                              "Please authenticate using your system prompt.")
        if "Password:" in line and self.status == "Connecting":
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
            target = _normalise_route_entry(raw)
            if not target:
                self._log(f"Skipping invalid route entry: {raw}")
                continue
            if ":" in target:
                cmd = ["ip", "-6", "route", "add", target, "dev", interface]
                is_v6 = True
            else:
                cmd = ["ip", "route", "add", target, "dev", interface]
                is_v6 = False
            if self._run_privileged(cmd):
                self._applied_routes.append((target, interface, is_v6))

    def _cleanup_routes(self):
        for target, interface, is_v6 in self._applied_routes:
            if is_v6:
                cmd = ["ip", "-6", "route", "del", target, "dev", interface]
            else:
                cmd = ["ip", "route", "del", target, "dev", interface]
            self._run_privileged(cmd)
        self._applied_routes.clear()

    def _run_privileged(self, cmd: List[str]) -> bool:
        resolved_cmd = cmd[:]
        resolved_cmd[0] = shutil.which(resolved_cmd[0]) or resolved_cmd[0]

        if self._pkexec_path:
            pkexec_cmd = [self._pkexec_path] + resolved_cmd
            self._log(f"Running: {' '.join(pkexec_cmd)}")
            try:
                proc = subprocess.run(pkexec_cmd, capture_output=True, text=True)
            except Exception as exc:
                self._log(f"Failed to run '{resolved_cmd[0]}' with pkexec: {exc}")
            else:
                if proc.returncode == 0:
                    return True
                stderr_text = (proc.stderr or proc.stdout or "").strip()
                if "dismissed" in stderr_text.lower() or "rejected" in stderr_text.lower():
                    self._log("Route command cancelled from system authentication prompt.")
                    return False
                self._log(f"Command failed ({proc.returncode}): {stderr_text}")

        sudo_cmd = ["sudo", "-n"] + resolved_cmd
        self._log(f"Running: {' '.join(sudo_cmd)}")
        try:
            proc = subprocess.run(sudo_cmd, capture_output=True, text=True)
        except Exception as exc:
            self._log(f"Failed to run '{resolved_cmd[0]}' with sudo: {exc}")
            return False
        if proc.returncode == 0:
            return True

        stderr_text = (proc.stderr or "").strip()
        stderr_lower = stderr_text.lower()
        if any(key in stderr_lower for key in ["password", "a password is required", "authentication required"]):
            self._log("Route command requires authentication.")
            if not self._password_cb:
                self._log("Unable to escalate privileges for route command (no password handler).")
                return False
            password = self._password_cb(
                "Additional privileges are required to adjust custom routes.\n"
                "Enter your sudo password.",
            )
            if password is None:
                self._log("Route command cancelled by user.")
                return False
            try:
                sudo_interactive = ["sudo", "-S", "-p", AUTH_PROMPT] + resolved_cmd
                display_cmd = ["sudo", "-S"] + resolved_cmd
                self._log(f"Running: {' '.join(display_cmd)}")
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

        output = (stderr_text or proc.stdout or "").strip()
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
        self.setWindowTitle("Multi‑VPN Manager")
        self.resize(1024, 640)

        self.config = ConfigStore(CONFIG_PATH)
        self.config.load()

        self.vpn_procs: Dict[str, VPNProcess] = {}
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self._cached_password: Optional[str] = None

        toolbar = QToolBar("Main")
        toolbar.setIconSize(QSize(18, 18))
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
        layout = QVBoxLayout(central)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Name",
            "Host",
            "Port",
            "SAML",
            "Browser",
            "Profile",
            "Auto",
            "Status",
            "Actions",
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(QLabel("Logs"))
        layout.addWidget(self.log_view, stretch=1)

        self.setCentralWidget(central)

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._drain_logs)
        self.ui_timer.start(200)

        self.refresh_table()

    # ---- GUI callbacks ---------------------------------------------------

    def refresh_table(self):
        self.table.setRowCount(0)
        for vpn in self.config.vpns:
            self._add_vpn_row(vpn)

    def _add_vpn_row(self, vpn: VPNProfile):
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(vpn.name))
        self.table.setItem(row, 1, QTableWidgetItem(vpn.host))
        self.table.setItem(row, 2, QTableWidgetItem(str(vpn.port) if vpn.port else ""))
        self.table.setItem(row, 3, QTableWidgetItem("Yes" if vpn.use_saml else "No"))
        self.table.setItem(row, 4, QTableWidgetItem(vpn.browser))
        self.table.setItem(row, 5, QTableWidgetItem(vpn.profile))
        self.table.setItem(row, 6, QTableWidgetItem("Yes" if vpn.auto_reconnect else "No"))

        status_item = QTableWidgetItem(self._status_of(vpn.name))
        self.table.setItem(row, 7, status_item)

        action_w = QWidget()
        hb = QHBoxLayout(action_w)
        hb.setContentsMargins(0, 0, 0, 0)
        btn_conn = QPushButton("Connect")
        btn_disc = QPushButton("Disconnect")
        btn_conn.clicked.connect(lambda _, v=vpn: self.connect_vpn(v))
        btn_disc.clicked.connect(lambda _, v=vpn: self.disconnect_vpn(v))
        hb.addWidget(btn_conn)
        hb.addWidget(btn_disc)
        self.table.setCellWidget(row, 8, action_w)

    def _status_of(self, name: str) -> str:
        proc = self.vpn_procs.get(name)
        return proc.status if proc else "Idle"

    def add_vpn_dialog(self):
        names = [v.name for v in self.config.vpns]
        dlg = AddEditVPNDialog(self, existing_names=names)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vpn = dlg.get_vpn()
            if vpn:
                self.config.vpns.append(vpn)
                self.config.save()
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
                idx = self.config.vpns.index(vpn)
                self.config.vpns[idx] = new_vpn
                self.config.save()
                self.refresh_table()

    def remove_selected_vpn(self):
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.table.item(row, 0).text()
        if QMessageBox.question(self, "Remove VPN",
                                f"Delete VPN '{name}' from configuration?") == QMessageBox.StandardButton.Yes:
            self.config.vpns = [v for v in self.config.vpns if v.name != name]
            self.config.save()
            self.refresh_table()

    def connect_vpn(self, vpn: VPNProfile):
        proc = self.vpn_procs.get(vpn.name)
        if proc and proc.status not in ("Idle", "Error"):
            self._append_log(f"{vpn.name}: already running")
            return
        proc = VPNProcess(vpn, self.log_queue, password_cb=self._request_password, info_cb=self._show_info)
        self.vpn_procs[vpn.name] = proc
        proc.start()
        self._update_status_row(vpn.name, "Connecting")

    def disconnect_vpn(self, vpn: VPNProfile):
        proc = self.vpn_procs.get(vpn.name)
        if not proc:
            self._append_log(f"{vpn.name}: not running")
            return
        proc.stop()
        self._update_status_row(vpn.name, "Idle")

    def clear_cached_password(self):
        self._cached_password = None
        QMessageBox.information(self, "Authentication", "Cached sudo password cleared.")

    # --- helpers ----------------------------------------------------------

    def _request_password(self, prompt: str) -> Optional[str]:
        if self._cached_password:
            return self._cached_password

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

    def _update_status_row(self, name: str, status: str):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0) and self.table.item(r, 0).text() == name:
                self.table.setItem(r, 7, QTableWidgetItem(status))
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

    desktop_entry = """[Desktop Entry]
Version=1.0
Type=Application
Name=Multi-VPN Manager
Comment=Manage multiple openfortivpn connections
Exec={exec_cmd}
Icon=network-vpn
Terminal=false
Categories=Network;Utility;
StartupNotify=true
""".format(exec_cmd=exec_cmd)

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
