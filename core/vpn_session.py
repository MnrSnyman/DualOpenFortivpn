"""Management of openfortivpn subprocess lifecycles with GUI signals."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
import webbrowser
from typing import Dict, Iterable, List, Optional, Tuple

import psutil

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

    _registry_lock = threading.Lock()
    _active_processes: Dict[int, Tuple[Optional[int], str, Tuple[str, ...]]] = {}

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
        self._process_group: Optional[int] = None
        self._interface_name: Optional[str] = None
        self._browser_launched = False
        self._allow_reconnect = True
        self._command_signature: Optional[Tuple[str, ...]] = None

    @classmethod
    def _register_process(
        cls, pid: int, pgid: Optional[int], profile: str, signature: Tuple[str, ...]
    ) -> None:
        with cls._registry_lock:
            cls._active_processes[pid] = (pgid, profile, signature)

    @classmethod
    def _unregister_process(cls, pid: int) -> None:
        with cls._registry_lock:
            cls._active_processes.pop(pid, None)

    @staticmethod
    def _wait_for_exit(pid: int, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not psutil.pid_exists(pid):
                return True
            time.sleep(0.2)
        return not psutil.pid_exists(pid)

    @staticmethod
    def _send_signal_group(
        pgid: Optional[int], sig: signal.Signals, privilege: PrivilegeManager, profile: str
    ) -> bool:
        if pgid is None:
            return False
        try:
            os.killpg(pgid, sig)
            return True
        except PermissionError:
            LOGGER.debug(
                "[%s] Permission denied sending %s to process group %s; escalating",
                profile,
                sig.name,
                pgid,
            )
            try:
                code, stdout, stderr = privilege.run_privileged(["/bin/kill", f"-{sig.value}", f"-{pgid}"])
            except RuntimeError as exc:
                LOGGER.warning(
                    "[%s] Unable to escalate kill for process group %s: %s",
                    profile,
                    pgid,
                    exc,
                )
                return False
            if code != 0:
                message = stderr.strip() or stdout.strip()
                if message:
                    LOGGER.warning(
                        "[%s] Failed to deliver %s to process group %s: %s",
                        profile,
                        sig.name,
                        pgid,
                        message,
                    )
                return False
            return True
        except ProcessLookupError:
            return True
        except Exception as exc:
            LOGGER.warning(
                "[%s] Failed to send %s to process group %s: %s",
                profile,
                sig.name,
                pgid,
                exc,
            )
            return False

    @staticmethod
    def _send_signal_pid(pid: int, sig: signal.Signals, privilege: PrivilegeManager, profile: str) -> bool:
        try:
            os.kill(pid, sig)
            return True
        except PermissionError:
            LOGGER.debug(
                "[%s] Permission denied sending %s to pid %s; escalating",
                profile,
                sig.name,
                pid,
            )
            try:
                code, stdout, stderr = privilege.run_privileged(["/bin/kill", f"-{sig.value}", str(pid)])
            except RuntimeError as exc:
                LOGGER.warning(
                    "[%s] Unable to escalate kill for pid %s: %s",
                    profile,
                    pid,
                    exc,
                )
                return False
            if code != 0:
                message = stderr.strip() or stdout.strip()
                if message:
                    LOGGER.warning(
                        "[%s] Failed to deliver %s to pid %s: %s",
                        profile,
                        sig.name,
                        pid,
                        message,
                    )
                return False
            return True
        except ProcessLookupError:
            return True
        except Exception as exc:
            LOGGER.warning(
                "[%s] Failed to send %s to pid %s: %s",
                profile,
                sig.name,
                pid,
                exc,
            )
            return False

    @classmethod
    def _terminate_entry(
        cls,
        pid: int,
        pgid: Optional[int],
        privilege: PrivilegeManager,
        profile: str,
        forced: bool = False,
    ) -> None:
        if pid <= 0:
            return
        if not psutil.pid_exists(pid):
            cls._unregister_process(pid)
            return
        action = "Force terminating" if forced else "Stopping"
        LOGGER.info("[%s] %s openfortivpn pid %s", profile, action, pid)
        delivered = cls._send_signal_group(pgid, signal.SIGTERM, privilege, profile)
        if not delivered:
            cls._send_signal_pid(pid, signal.SIGTERM, privilege, profile)
        if not cls._wait_for_exit(pid, 10):
            LOGGER.warning("[%s] openfortivpn pid %s still running; escalating", profile, pid)
            cls._send_signal_group(pgid, signal.SIGKILL, privilege, profile)
            cls._send_signal_pid(pid, signal.SIGKILL, privilege, profile)
            if not cls._wait_for_exit(pid, 5):
                LOGGER.error("[%s] openfortivpn pid %s did not terminate", profile, pid)
        if not psutil.pid_exists(pid):
            cls._unregister_process(pid)

    @classmethod
    def _tracked_processes_for_profile(
        cls, profile: str
    ) -> List[Tuple[int, Optional[int], Tuple[str, ...]]]:
        with cls._registry_lock:
            return [
                (pid, data[0], data[2])
                for pid, data in cls._active_processes.items()
                if data[1] == profile
            ]

    @staticmethod
    def _build_host_tokens(
        profile: VPNProfile, signatures: Optional[Iterable[Tuple[str, ...]]] = None
    ) -> List[str]:
        tokens: set[str] = set()
        host_value = profile.host or ""
        base_host = host_value
        detected_port: Optional[str] = None
        if ":" in host_value:
            host_part, _, port_part = host_value.rpartition(":")
            if host_part:
                base_host = host_part
            if port_part.isdigit():
                detected_port = port_part
        port_str = str(profile.port)
        tokens.update({host_value, base_host, f"{base_host}:{port_str}", f"{base_host} {port_str}"})
        tokens.add(port_str)
        if detected_port:
            tokens.add(detected_port)
            tokens.add(f"{base_host} {detected_port}")
            tokens.add(f"{base_host}:{detected_port}")
        if profile.auth_type.lower() == "saml":
            tokens.add("--saml-login")
            if profile.saml_port:
                tokens.add(str(profile.saml_port))
        if signatures:
            for signature in signatures:
                for part in signature:
                    if not part:
                        continue
                    tokens.add(part)
                    if ":" in part:
                        base, _, remainder = part.rpartition(":")
                        if base:
                            tokens.add(base)
                        if remainder:
                            tokens.add(remainder)
        return [token for token in tokens if token]

    @classmethod
    def _terminate_signature_matches(
        cls,
        profile: VPNProfile,
        privilege: PrivilegeManager,
        forced: bool = False,
        signatures: Optional[List[Tuple[str, ...]]] = None,
    ) -> None:
        host_tokens = cls._build_host_tokens(profile, signatures)
        with cls._registry_lock:
            tracked = set(cls._active_processes.keys())
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.pid in tracked:
                    continue
                name = proc.info.get("name") or ""
                cmdline = proc.info.get("cmdline") or []
                if not cmdline and hasattr(proc, "cmdline"):
                    cmdline = proc.cmdline()
                if not cmdline:
                    continue
                identifier = " ".join(cmdline)
                if "openfortivpn" not in name and "openfortivpn" not in cmdline[0]:
                    continue
                if not any(token in identifier for token in host_tokens):
                    continue
                try:
                    pgid = os.getpgid(proc.pid)
                except Exception:
                    pgid = None
                cls._terminate_entry(proc.pid, pgid, privilege, profile.name, forced)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    @classmethod
    def cleanup_profile_processes(
        cls,
        profile: VPNProfile,
        privilege: PrivilegeManager,
        forced: bool = False,
        signature: Optional[Tuple[str, ...]] = None,
    ) -> None:
        tracked_signatures: List[Tuple[str, ...]] = []
        for pid, pgid, tracked_signature in cls._tracked_processes_for_profile(profile.name):
            if tracked_signature:
                tracked_signatures.append(tracked_signature)
            cls._terminate_entry(pid, pgid, privilege, profile.name, forced)
        if signature:
            tracked_signatures.append(signature)
        cls._terminate_signature_matches(profile, privilege, forced, tracked_signatures or None)

    @classmethod
    def terminate_orphaned_processes(cls, privilege: PrivilegeManager) -> None:
        with cls._registry_lock:
            entries = list(cls._active_processes.items())
        for pid, (pgid, profile, _signature) in entries:
            cls._terminate_entry(pid, pgid, privilege, profile, True)

    @classmethod
    def cleanup_all_profiles(
        cls, profiles: Iterable[VPNProfile], privilege: PrivilegeManager
    ) -> None:
        seen: set[str] = set()
        for profile in profiles:
            key = profile.name
            if key in seen:
                continue
            seen.add(key)
            cls._terminate_signature_matches(profile, privilege, True)

    def stop(self) -> None:
        self._allow_reconnect = False
        self._stop_event.set()
        self.status_changed.emit("Disconnecting")
        process = self._process
        if process and process.poll() is None:
            pgid = self._process_group
            if pgid is None:
                try:
                    pgid = os.getpgid(process.pid)
                except Exception:
                    pgid = None
            self._terminate_entry(process.pid, pgid, self._privilege_manager, self.profile.name)
        VPNSession.cleanup_profile_processes(
            self.profile,
            self._privilege_manager,
            True,
            self._command_signature,
        )
        self._route_manager.cleanup(self.profile.name)
        self._interface_name = None
        self._browser_launched = False

    def run(self) -> None:
        backoff = 5
        while not self._stop_event.is_set():
            self.status_changed.emit("Starting")
            success = self._run_once()
            if self._stop_event.is_set() or not self.profile.auto_reconnect or not self._allow_reconnect:
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
        VPNSession.cleanup_profile_processes(
            self.profile,
            self._privilege_manager,
            signature=self._command_signature,
        )

    def _run_once(self) -> bool:
        self._browser_launched = False
        self._interface_name = None
        command = self._build_command()
        self._command_signature = tuple(command)
        LOGGER.debug("Launching openfortivpn for profile %s", self.profile.name)
        try:
            argv, password = self._privilege_manager.build_command(command)
        except RuntimeError as exc:
            message = f"Privilege escalation failed: {exc}"
            LOGGER.error(message)
            self.status_changed.emit("Privilege error")
            self.log_line.emit(message)
            return False
        if self._stop_event.is_set():
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
            try:
                self._process_group = os.getpgid(self._process.pid)
            except Exception:
                self._process_group = None
            VPNSession._register_process(
                self._process.pid,
                self._process_group,
                self.profile.name,
                self._command_signature or tuple(command),
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
        pid = self._process.pid if self._process else None
        rc = self._process.wait() if self._process else 0
        self.disconnected.emit(self.profile.name)
        self.status_changed.emit("Disconnected")
        if rc != 0:
            self.log_line.emit(f"Process exited with code {rc}")
        if pid is not None:
            VPNSession._unregister_process(pid)
        self._process = None
        self._process_group = None
        self._command_signature = None
        return connected_once

    def _build_command(self) -> list[str]:
        host, port = self._normalized_host_port()
        command = ["openfortivpn", f"{host}:{port}"]
        if self.profile.auth_type.lower() == "saml":
            if self.profile.saml_port:
                command.append(f"--saml-login={self.profile.saml_port}")
            else:
                command.append("--saml-login")
        else:
            if self.profile.username:
                command.append(f"--username={self.profile.username}")
        return command

    def _normalized_host_port(self) -> Tuple[str, int]:
        host = self.profile.host or ""
        port = self.profile.port
        if ":" in host:
            host_part, _, port_part = host.rpartition(":")
            if host_part and port_part.isdigit():
                host = host_part
                port = int(port_part)
        if host != self.profile.host or port != self.profile.port:
            self.profile.host = host
            self.profile.port = port
        return host, port

    def command_signature(self) -> Optional[Tuple[str, ...]]:
        return self._command_signature

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

    def interface_name(self) -> Optional[str]:
        """Expose the detected VPN interface for manual route operations."""
        return self._interface_name

    def apply_routes(self) -> bool:
        """Apply custom routes on demand when triggered from the UI."""
        if not self.profile.routes:
            self.log_line.emit("No custom routes are configured for this profile.")
            return False
        if not self._route_manager:
            self.log_line.emit("Route manager unavailable; cannot apply routes.")
            return False
        if not self._process or self._process.poll() is not None:
            self.log_line.emit("VPN process is not running; connect before applying routes.")
            return False
        if not self._interface_name:
            self.log_line.emit("VPN interface not yet detected; wait for connection to complete.")
            return False
        self._route_manager.apply_routes(
            self.profile.name,
            self.profile.routes,
            self._interface_name,
        )
        return True

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
