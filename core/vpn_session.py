"""Management of openfortivpn subprocess lifecycles with GUI signals."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
import webbrowser
from typing import Dict, Optional, Tuple

from core.qt_compat import QThread, Signal

from .browser_detection import BrowserInfo, detect_browsers
from .logging_manager import get_logging_manager
from .privilege import PrivilegeManager
from .routing import RouteManager
from .vpn_profile import VPNProfile

LOGGER = get_logging_manager().logger
PASSWORD_PROMPT_RE = re.compile(r"password", re.IGNORECASE)


class VPNSession(QThread):
    status_changed = Signal(str)
    log_line = Signal(str)
    connected = Signal(str)
    disconnected = Signal(str)

    def __init__(
        self,
        profile: VPNProfile,
        privilege_manager: PrivilegeManager,
        route_manager: RouteManager,
        browser_catalog: Dict[str, BrowserInfo],
        credentials: Optional[Tuple[str, str]],
    ) -> None:
        super().__init__()
        self.profile = profile
        self._privilege_manager = privilege_manager
        self._route_manager = route_manager
        self._browser_catalog = browser_catalog or {info.key: info for info in detect_browsers()}
        self._credentials = credentials
        self._stop_event = threading.Event()
        self._process: Optional[subprocess.Popen[str]] = None
        self._interface_name: Optional[str] = None
        self._routes_applied = False
        self._browser_launched = False

    def stop(self) -> None:
        self._stop_event.set()
        process = self._process
        if process and process.poll() is None:
            try:
                pgid = os.getpgid(process.pid)
            except Exception:
                pgid = process.pid

            def _signal_group(sig: signal.Signals) -> bool:
                try:
                    os.killpg(pgid, sig)
                    return True
                except PermissionError:
                    LOGGER.debug(
                        "Permission denied sending %s to process group %s; escalating",
                        sig.name,
                        pgid,
                    )
                    return self._privilege_manager.terminate_process_group(pgid, sig)
                except ProcessLookupError:
                    return True
                except Exception as exc:
                    LOGGER.warning(
                        "Failed to send %s to process group %s: %s",
                        sig.name,
                        pgid,
                        exc,
                    )
                    return False

            if not _signal_group(signal.SIGTERM):
                LOGGER.warning("Failed to deliver SIGTERM to process group %s", pgid)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                LOGGER.warning("SIGTERM timeout for process group %s; escalating to SIGKILL", pgid)
                if not _signal_group(signal.SIGKILL):
                    try:
                        process.kill()
                    except Exception as exc:
                        LOGGER.error(
                            "Failed to deliver SIGKILL to process %s: %s",
                            process.pid,
                            exc,
                        )
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    LOGGER.error("openfortivpn process group %s did not terminate", pgid)
            except Exception:
                pass
        self._route_manager.cleanup(self.profile.name)
        self._interface_name = None
        self._routes_applied = False
        self._browser_launched = False
        self._process = None

    def run(self) -> None:
        backoff = 5
        while not self._stop_event.is_set():
            self.status_changed.emit("Starting")
            success = self._run_once()
            if self._stop_event.is_set() or not self.profile.auto_reconnect:
                break
            if success:
                backoff = 5
            else:
                backoff = min(backoff * 2, 60)
            self.status_changed.emit(f"Reconnecting in {backoff}s")
            for _ in range(backoff):
                if self._stop_event.is_set():
                    break
                time.sleep(1)
        self.status_changed.emit("Stopped")

    def _run_once(self) -> bool:
        self._routes_applied = False
        self._browser_launched = False
        self._interface_name = None
        command = self._build_command()
        LOGGER.debug("Launching openfortivpn for profile %s", self.profile.name)
        try:
            argv, password = self._privilege_manager.build_command(command)
        except RuntimeError as exc:
            message = f"Privilege escalation failed: {exc}"
            LOGGER.error(message)
            self.status_changed.emit("Privilege error")
            self.log_line.emit(message)
            return False
        try:
            self._process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                start_new_session=True,
            )
        except FileNotFoundError:
            message = "openfortivpn binary not found"
            LOGGER.error(message)
            self.status_changed.emit("Binary missing")
            self.log_line.emit(message)
            return False
        if password and self._process.stdin:
            self._process.stdin.write(password + "\n")
            self._process.stdin.flush()
        connected_once = False
        while not self._stop_event.is_set():
            line = self._process.stdout.readline() if self._process.stdout else ""
            if not line:
                if self._process.poll() is not None:
                    break
                time.sleep(0.1)
                continue
            cleaned = line.strip()
            if not cleaned:
                continue
            self.log_line.emit(cleaned)
            LOGGER.debug("%s", cleaned)
            self._handle_output(cleaned)
            if ("Tunnel is up" in cleaned or "Established" in cleaned) and not connected_once:
                connected_once = True
                self.status_changed.emit("Connected")
                self.connected.emit(self.profile.name)
        self._route_manager.cleanup(self.profile.name)
        self._interface_name = None
        rc = self._process.wait() if self._process else 0
        self.disconnected.emit(self.profile.name)
        self.status_changed.emit("Disconnected")
        if rc != 0:
            self.log_line.emit(f"Process exited with code {rc}")
        self._process = None
        return connected_once

    def _build_command(self) -> list[str]:
        command = ["openfortivpn", f"{self.profile.host}:{self.profile.port}"]
        if self.profile.auth_type.lower() == "saml":
            if self.profile.saml_port:
                command.append(f"--saml-login={self.profile.saml_port}")
            else:
                command.append("--saml-login")
        else:
            if self.profile.username:
                command.append(f"--username={self.profile.username}")
        return command

    def _handle_output(self, line: str) -> None:
        if self._stop_event.is_set():
            return
        # Capture the interface name as soon as it appears so route management
        # receives an explicit hint instead of falling back to interface
        # detection that can miss already-established PPP/TUN devices.
        if "Interface" in line and ("ppp" in line or "tun" in line):
            parts = line.split()
            for part in parts:
                if part.startswith("ppp") or part.startswith("tun"):
                    self._interface_name = part
                    break
        if self.profile.auth_type.lower() == "saml":
            if not self._browser_launched and ("Authenticate" in line or "browser" in line.lower()):
                # The authenticate line is usually wrapped in single quotes by
                # openfortivpn (e.g. Authenticate at 'https://host/path').
                # Extract the URL without any trailing quotes so the browser
                # receives a clean location and does not percent-encode the
                # quote character into the request.
                match = re.search(r"https?://[^\s\"']+", line)
                if match:
                    url = match.group(0).rstrip("'\"")
                    self._launch_browser(url)
                    self._browser_launched = True
        else:
            if PASSWORD_PROMPT_RE.search(line) and self._process and self._process.stdin:
                if self._credentials:
                    _, password = self._credentials
                    self._process.stdin.write(password + "\n")
                    self._process.stdin.flush()
        if self.profile.routes and not self._routes_applied and self._interface_name:
            self._route_manager.apply_routes(
                self.profile.name,
                self.profile.routes,
                self._interface_name,
            )
            self._routes_applied = True

    def _launch_browser(self, url: str) -> None:
        browser_key = self.profile.browser
        if not browser_key or browser_key == "system":
            webbrowser.open(url)
            return
        info = self._browser_catalog.get(browser_key)
        if not info:
            webbrowser.open(url)
            return
        args = [info.executable, url]
        profile = self.profile.browser_profile
        if profile:
            if info.key == "firefox":
                args.insert(1, "-P")
                args.insert(2, profile)
            else:
                args.insert(1, f"--profile-directory={profile}")
        try:
            subprocess.Popen(args)
        except Exception as exc:
            LOGGER.error("Failed to open browser %s: %s", info.name, exc)
            webbrowser.open(url)
