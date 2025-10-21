"""Routing helper utilities for applying and cleaning up VPN routes."""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import psutil

from .logging_manager import get_logging_manager
from .privilege import PrivilegeManager

LOGGER = get_logging_manager().logger


@dataclass
class AppliedRoute:
    destination: str
    interface: str


class RouteManager:
    """Compute and apply custom routes for VPN sessions."""

    def __init__(self, privilege_manager: PrivilegeManager) -> None:
        self._privilege_manager = privilege_manager
        self._session_routes: Dict[str, List[AppliedRoute]] = {}

    def _run_privileged(self, command: List[str]) -> Tuple[int, str, str]:
        argv, password = self._privilege_manager.build_command(command)
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if password else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if password and process.stdin:
            process.stdin.write(password + "\n")
            process.stdin.flush()
        stdout, stderr = process.communicate()
        return process.returncode, stdout, stderr

    def _resolve_target(self, target: str) -> str:
        try:
            ipaddress.ip_network(target, strict=False)
            return target
        except ValueError:
            try:
                ipaddress.ip_address(target)
                return target
            except ValueError:
                info = socket.getaddrinfo(target, None)
                return info[0][4][0]

    def _detect_interface(self, previous: List[str]) -> Optional[str]:
        interfaces = set(psutil.net_if_addrs().keys())
        new_interfaces = interfaces - set(previous)
        for name in new_interfaces:
            if name.startswith("ppp") or name.startswith("tun"):
                return name
        return None

    def apply_routes(self, session_id: str, targets: List[str], interface_hint: Optional[str]) -> None:
        if not targets:
            return
        LOGGER.info("Applying custom routes for session %s", session_id)
        interface = interface_hint
        if not interface:
            existing = list(psutil.net_if_addrs().keys())
            for _ in range(30):
                time.sleep(1)
                interface = self._detect_interface(existing)
                if interface:
                    break
        if not interface:
            LOGGER.warning("Unable to determine VPN interface for session %s; skipping routes", session_id)
            return
        applied: List[AppliedRoute] = []
        for entry in targets:
            try:
                destination = self._resolve_target(entry)
            except Exception as exc:
                LOGGER.error("Failed to resolve route target %s: %s", entry, exc)
                continue
            try:
                cmd = ["ip", "route", "add", destination, "dev", interface]
                code, stdout, stderr = self._run_privileged(cmd)
                if code != 0:
                    LOGGER.error("Failed to add route %s via %s: %s", destination, interface, stderr.strip())
                    continue
                applied.append(AppliedRoute(destination, interface))
                LOGGER.info("Route %s added via %s", destination, interface)
            except Exception as exc:
                LOGGER.exception("Exception while adding route %s: %s", entry, exc)
        if applied:
            self._session_routes[session_id] = applied

    def cleanup(self, session_id: str) -> None:
        applied = self._session_routes.pop(session_id, [])
        if not applied:
            return
        LOGGER.info("Cleaning custom routes for session %s", session_id)
        for route in applied:
            try:
                cmd = ["ip", "route", "del", route.destination, "dev", route.interface]
                code, stdout, stderr = self._run_privileged(cmd)
                if code != 0:
                    LOGGER.warning("Failed to remove route %s: %s", route.destination, stderr.strip())
                else:
                    LOGGER.info("Route %s removed", route.destination)
            except Exception as exc:
                LOGGER.exception("Exception while removing route %s: %s", route.destination, exc)
