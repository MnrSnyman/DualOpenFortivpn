"""VPN connection management using asyncio subprocesses."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import shlex
from dataclasses import dataclass
from enum import Enum

from ..saml.listener import SAMLListener
from ..utils import network
from ..utils.browsers import launch_browser
from ..utils.logging import get_logger, session_log_path
from ..utils.notifications import notify
from .profile import VPNProfile

logger = get_logger("connection")


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass
class ConnectionStatus:
    state: ConnectionState = ConnectionState.DISCONNECTED
    ip_address: str | None = None
    interface: str | None = None
    bandwidth_in: float = 0.0
    bandwidth_out: float = 0.0
    last_error: str | None = None
    started_at: dt.datetime | None = None
    auto_reconnect: bool = False
    reconnect_in: int | None = None

    def duration(self) -> dt.timedelta:
        if not self.started_at:
            return dt.timedelta(0)
        return dt.datetime.utcnow() - self.started_at


class VPNConnection:
    """Represents a single running OpenFortiVPN subprocess."""

    def __init__(self, profile: VPNProfile, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.profile = profile
        self.loop = loop or asyncio.get_event_loop()
        self.status = ConnectionStatus(auto_reconnect=profile.auto_reconnect)
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._wait_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._saml_listener: SAMLListener | None = None
        self._saml_task: asyncio.Task[None] | None = None
        self._log_path = session_log_path(profile.name)
        self._log_file = None
        self._lock = asyncio.Lock()
        self._applied_routes: list[str] = []
        self._applied_dns: list[str] = []
        self._connected_event: asyncio.Event = asyncio.Event()
        self._saml_browser_opened = False
        self._pending_saml_url = False

    async def connect(self) -> None:
        async with self._lock:
            if self.status.state in {ConnectionState.CONNECTING, ConnectionState.CONNECTED}:
                logger.debug("Connection for %s already active", self.profile.name)
                return
            self.status.state = ConnectionState.CONNECTING
            self.status.auto_reconnect = self.profile.auto_reconnect
            self.status.last_error = None
            self.status.started_at = dt.datetime.utcnow()
            self.status.reconnect_in = None
            self._connected_event = asyncio.Event()
            self._saml_browser_opened = False
            self._pending_saml_url = False
            notify("Connecting", f"Connecting to {self.profile.display_name()}")
            await self._launch_process()

    async def disconnect(self) -> None:
        async with self._lock:
            self.status.auto_reconnect = False
            if self._reconnect_task:
                self._reconnect_task.cancel()
                self._reconnect_task = None
            if self._wait_task:
                self._wait_task.cancel()
            if self._process and self._process.returncode is None:
                logger.info("Terminating openfortivpn process for %s", self.profile.name)
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=10)
                except asyncio.TimeoutError:
                    logger.warning("Force killing openfortivpn for %s", self.profile.name)
                    self._process.kill()
            await self._teardown()
            self.status.state = ConnectionState.DISCONNECTED
            notify("Disconnected", f"Disconnected from {self.profile.display_name()}")

    async def _launch_process(self) -> None:
        target = f"{self.profile.host}:{self.profile.port}"
        cmd = ["sudo", "-E", "openfortivpn", target]
        if self.profile.persistent:
            cmd.append("--persistent")
        if self.profile.enable_saml:
            configured_port = self.profile.saml_port
            saml_port = configured_port if configured_port not in (None, 0) else 8020
            if saml_port == 8020:
                logger.warning("Using Fortinet default SAML port 8020. Consider customizing per session.")
            self._saml_listener = SAMLListener(port=saml_port)
            await self._saml_listener.start()
            if configured_port in (None, 0, 8020):
                cmd.append("--saml-login")
            else:
                cmd.append(f"--saml-login={saml_port}")
        else:
            if self.profile.username:
                cmd.extend(["--username", self.profile.username])
            if self.profile.password:
                cmd.append("--passwd-on-stdin")
        env = os.environ.copy()
        logger.info("Launching command: %s", shlex.join(cmd))
        if not self._log_file or self._log_file.closed:
            self._log_file = self._log_path.open("a", encoding="utf-8")
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if self.profile.password and not self.profile.enable_saml else None,
            env=env,
        )
        if self.profile.enable_saml:
            self._saml_task = self.loop.create_task(self._monitor_saml())
        elif self.profile.password and self._process.stdin:
            self._process.stdin.write((self.profile.password + "\n").encode("utf-8"))
            await self._process.stdin.drain()
            self._process.stdin.close()
        self._stdout_task = self.loop.create_task(self._stream_reader(self._process.stdout, False))
        self._stderr_task = self.loop.create_task(self._stream_reader(self._process.stderr, True))
        self._wait_task = self.loop.create_task(self._wait_for_exit())

    def _open_browser(self, url: str | None = None) -> bool:
        target_url = url or f"https://{self.profile.host}/remote/saml/start?redirect=1"
        notify("SAML login", "Launching browser for SAML authentication")
        launched = launch_browser(self.profile.browser, self.profile.browser_profile, target_url)
        if not launched:
            logger.warning(
                "Falling back to default browser for %s (requested: %s profile %s)",
                self.profile.name,
                self.profile.browser or "default",
                self.profile.browser_profile or "default",
            )
        return launched

    def _log_saml(self, message: str, level: str = "info") -> None:
        log_fn = getattr(logger, level, None)
        if not callable(log_fn):
            log_fn = logger.info
        log_fn("[SAML] %s: %s", self.profile.name, message)
        if self._log_file:
            self._log_file.write(f"[SAML] {message}\n")
            self._log_file.flush()

    @staticmethod
    def _extract_saml_url(text: str) -> str | None:
        match = re.search(r"(https?://[^\s\"']+)", text)
        if match:
            return match.group(1)
        return None

    def _handle_saml_prompt(self, text: str) -> bool:
        url = self._extract_saml_url(text)
        if not url:
            return False
        if not self._saml_browser_opened:
            self._log_saml("Opening browser")
            if not self._open_browser(url):
                self._log_saml("Falling back to system browser", level="warning")
            self._saml_browser_opened = True
        return True

    def _handle_connected(self) -> None:
        first_transition = self.status.state != ConnectionState.CONNECTED
        if first_transition:
            self.status.state = ConnectionState.CONNECTED
            notify("Connected", f"Connected to {self.profile.display_name()}")
        if not self._connected_event.is_set():
            self._connected_event.set()
        if first_transition and self.status.interface:
            self.loop.create_task(self.apply_network_overrides())

    async def _stream_reader(self, stream: asyncio.StreamReader | None, is_stderr: bool) -> None:
        if not stream:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            if self._log_file:
                self._log_file.write(text + "\n")
                self._log_file.flush()
            logger.debug("%s: %s", self.profile.name, text)
            self._parse_output(text, is_stderr)

    def _parse_output(self, line: str, is_stderr: bool) -> None:
        lower_line = line.lower()
        if self.profile.enable_saml:
            if "authenticate at" in lower_line or "open the following url" in lower_line:
                if not self._handle_saml_prompt(line):
                    self._pending_saml_url = True
                else:
                    self._pending_saml_url = False
            elif self._pending_saml_url:
                if self._handle_saml_prompt(line):
                    self._pending_saml_url = False
        if "tunnel is up" in lower_line or "connected to vpn" in lower_line:
            self._handle_connected()
        if "interface name:" in lower_line:
            match = re.search(r"Interface name:\s*(\S+)", line)
            if match:
                self.status.interface = match.group(1)
                if self.status.state == ConnectionState.CONNECTED:
                    self.loop.create_task(self.apply_network_overrides())
        if "assigned virtual ip:" in lower_line:
            match = re.search(r"Assigned virtual IP:\s*(\S+)", line)
            if match:
                self.status.ip_address = match.group(1)
        if "bytes in" in lower_line and "bytes out" in lower_line:
            match = re.search(r"bytes in (\d+).+bytes out (\d+)", line)
            if match:
                self.status.bandwidth_in = float(match.group(1))
                self.status.bandwidth_out = float(match.group(2))
        if "LOGOUT" in line or "disconnected" in line.lower():
            self.status.state = ConnectionState.DISCONNECTED
        if "SAML" in line and "8020" in line:
            notify(
                "SAML redirect warning",
                (
                    "Your FortiGate redirected authentication to 127.0.0.1:8020. "
                    "Update the callback URL to use the configured listener port "
                    f"({self.profile.saml_port}) or enable fallback in settings."
                ),
                urgency="critical",
            )

    async def _wait_for_exit(self) -> None:
        assert self._process is not None
        returncode = await self._process.wait()
        self._log_file.write(f"Process exited with code {returncode}\n")
        self._log_file.flush()
        await self._teardown()
        if returncode == 0:
            self.status.state = ConnectionState.DISCONNECTED
        else:
            self.status.state = ConnectionState.ERROR
            self.status.last_error = f"openfortivpn exited with code {returncode}"
            notify("Connection error", self.status.last_error or "Unknown error", urgency="critical")
        if self.profile.auto_reconnect and returncode != 0:
            self.status.state = ConnectionState.RECONNECTING
            await self._schedule_reconnect()

    async def _schedule_reconnect(self) -> None:
        interval = max(5, self.profile.auto_reconnect_interval)
        self.status.reconnect_in = interval
        notify("Auto reconnect", f"Retrying {self.profile.name} in {interval} seconds")

        async def countdown() -> None:
            try:
                while self.status.reconnect_in and self.status.reconnect_in > 0:
                    await asyncio.sleep(1)
                    self.status.reconnect_in -= 1
                await self.connect()
            finally:
                self._reconnect_task = None

        self._reconnect_task = self.loop.create_task(countdown())

    async def _teardown(self) -> None:
        if self.status.interface and self.profile.routing_rules:
            await network.remove_routes(self.status.interface, self.profile.routing_rules)
        if self.status.interface and self.profile.custom_dns:
            await network.remove_dns(self.status.interface)
        self._applied_routes.clear()
        self._applied_dns.clear()
        if self._stdout_task:
            self._stdout_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()
        if self._saml_listener:
            await self._saml_listener.stop()
            self._saml_listener = None
        if self._saml_task:
            self._saml_task.cancel()
            self._saml_task = None
        if self._log_file:
            self._log_file.flush()
            self._log_file.close()
            self._log_file = None
        self._process = None

    async def apply_network_overrides(self) -> None:
        if self.status.interface:
            if self.profile.routing_rules:
                await network.add_routes(self.status.interface, self.profile.routing_rules)
                self._applied_routes = list(self.profile.routing_rules)
            if self.profile.custom_dns:
                await network.apply_dns(self.profile.custom_dns, self.status.interface)
                self._applied_dns = list(self.profile.custom_dns)

    async def _monitor_saml(self) -> None:
        listener = self._saml_listener
        if not listener:
            return
        timeout = 300.0
        self._log_saml("Waiting for authentication")
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        listener_task = self.loop.create_task(listener.wait_for_result(timeout=timeout))
        connected_future = self.loop.create_task(self._connected_event.wait())
        should_stop = False
        terminate_process = False
        try:
            done, _ = await asyncio.wait(
                {listener_task, connected_future},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=timeout,
            )
            if not done:
                self._log_saml("Listener timeout reached, closing", level="warning")
                should_stop = True
                terminate_process = True
            else:
                if listener_task in done:
                    result = listener_task.result()
                    if result:
                        notify("SAML callback received", result.message)
                        self._log_saml("Authentication callback received")
                        if self._log_file:
                            self._log_file.write(f"SAML result: {result.message} {result.params}\n")
                            self._log_file.flush()
                        if not connected_future.done():
                            self._log_saml("Authentication callback received, waiting for tunnel")
                    else:
                        self._log_saml("Listener timeout reached, closing", level="warning")
                        should_stop = True
                        terminate_process = True
                    if not connected_future.done():
                        elapsed = loop.time() - start_time
                        remaining = max(0.0, timeout - elapsed)
                        if remaining > 0:
                            try:
                                await asyncio.wait_for(connected_future, timeout=remaining)
                            except asyncio.TimeoutError:
                                self._log_saml("Listener timeout reached, closing", level="warning")
                                should_stop = True
                                terminate_process = True
                            else:
                                self._log_saml("Authentication complete")
                                should_stop = True
                        else:
                            self._log_saml("Listener timeout reached, closing", level="warning")
                            should_stop = True
                            terminate_process = True
                    else:
                        self._log_saml("Authentication complete")
                        should_stop = True
                elif connected_future in done:
                    self._log_saml("Authentication complete")
                    should_stop = True
        except asyncio.CancelledError:
            raise
        finally:
            for task in (listener_task, connected_future):
                if not task.done():
                    task.cancel()
            if (should_stop or self._connected_event.is_set()) and self._saml_listener is listener:
                await listener.stop()
                self._saml_listener = None
                self._log_saml("Listener closed")
            if (
                terminate_process
                and self._process
                and self._process.returncode is None
                and self.status.state != ConnectionState.CONNECTED
            ):
                self._log_saml("Terminating openfortivpn after timeout", level="warning")
                self._process.terminate()

