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
    family: int = 4
    replaced: bool = False
    previous: Optional[Dict[str, str]] = None


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

    def _resolve_targets(self, target: str) -> List[Tuple[str, int]]:
        """Expand a user-specified target into concrete destinations."""
        destinations: List[Tuple[str, int]] = []
        try:
            network = ipaddress.ip_network(target, strict=False)
            destinations.append((str(network), network.version))
            return destinations
        except ValueError:
            try:
                address = ipaddress.ip_address(target)
                destinations.append((str(address), address.version))
                return destinations
            except ValueError:
                info = socket.getaddrinfo(target, None)
                seen: set[str] = set()
                for entry in info:
                    addr = entry[4][0]
                    if addr in seen:
                        continue
                    seen.add(addr)
                    family = 6 if ":" in addr else 4
                    destinations.append((addr, family))
        return destinations

    def _detect_interface(self, previous: List[str]) -> Optional[str]:
        interfaces = set(psutil.net_if_addrs().keys())
        new_interfaces = interfaces - set(previous)
        for name in new_interfaces:
            if name.startswith("ppp") or name.startswith("tun"):
                return name
        return None

    def _normalize_destination(self, destination: str, family: int) -> str:
        """Return a canonical representation with explicit prefix length."""
        if destination == "default":
            return destination
        try:
            if "/" in destination:
                network = ipaddress.ip_network(destination, strict=False)
            else:
                suffix = "/32" if family == 4 else "/128"
                network = ipaddress.ip_network(f"{destination}{suffix}", strict=False)
            return str(network)
        except ValueError:
            return destination

    def _prefix_length(self, destination: str, family: int) -> Optional[int]:
        """Extract the CIDR prefix length for comparison purposes."""
        if destination == "default":
            return 0
        try:
            network = ipaddress.ip_network(destination, strict=False)
            return network.prefixlen
        except ValueError:
            try:
                address = ipaddress.ip_address(destination)
            except ValueError:
                return None
            return 32 if family == 4 else 128

    def _build_route_command(
        self,
        action: str,
        destination: str,
        interface: str,
        family: int,
        metric: Optional[int] = None,
    ) -> List[str]:
        """Construct the ip route command for IPv4 or IPv6 targets."""
        command = ["ip"]
        if family == 6:
            command.append("-6")
        command.extend(["route", action, destination, "dev", interface])
        if metric is not None:
            command.extend(["metric", str(metric)])
        return command

    def _capture_existing_route(self, destination: str, family: int) -> Optional[Dict[str, str]]:
        """Return details about an existing route so it can be restored later."""
        command = ["ip"]
        if family == 6:
            command.append("-6")
        command.extend(["route", "show", destination])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None
        line = result.stdout.strip().splitlines()
        if not line:
            return None
        return self._parse_route_line(line[0])

    def _parse_route_line(self, line: str) -> Dict[str, str]:
        """Extract key attributes from an `ip route show` response."""
        tokens = line.split()
        route: Dict[str, str] = {"destination": tokens[0]}
        idx = 1
        while idx < len(tokens):
            token = tokens[idx]
            if token in {"via", "dev", "metric"} and idx + 1 < len(tokens):
                route[token] = tokens[idx + 1]
                idx += 2
                continue
            idx += 1
        return route

    def _restore_previous_route(self, route: AppliedRoute) -> None:
        if not route.previous:
            return
        command = ["ip"]
        if route.family == 6:
            command.append("-6")
        command.extend(["route", "replace", route.previous["destination"]])
        if "via" in route.previous:
            command.extend(["via", route.previous["via"]])
        if "dev" in route.previous:
            command.extend(["dev", route.previous["dev"]])
        if "metric" in route.previous:
            command.extend(["metric", route.previous["metric"]])
        code, stdout, stderr = self._run_privileged(command)
        if code != 0:
            LOGGER.warning(
                "Failed to restore previous route %s: %s",
                route.previous["destination"],
                stderr.strip(),
            )

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
        # When openfortivpn reports the interface name the kernel may still be
        # bringing the device up. Wait briefly until the interface is visible to
        # avoid "Cannot find device" errors when applying routes immediately.
        if interface not in psutil.net_if_addrs():
            for _ in range(20):
                time.sleep(0.25)
                if interface in psutil.net_if_addrs():
                    break
            else:
                LOGGER.warning(
                    "Interface %s not yet available for session %s; skipping custom routes",
                    interface,
                    session_id,
                )
                return
        for entry in targets:
            try:
                destinations = self._resolve_targets(entry)
            except Exception as exc:
                LOGGER.error("Failed to resolve route target %s: %s", entry, exc)
                continue
            if not destinations:
                LOGGER.error("No addresses resolved for route target %s", entry)
                continue
            for destination, family in destinations:
                command_destination = self._normalize_destination(destination, family)
                existing = self._capture_existing_route(destination, family)
                new_prefix = self._prefix_length(command_destination, family)
                existing_prefix = (
                    self._prefix_length(existing["destination"], family)
                    if existing and "destination" in existing
                    else None
                )
                metric_hint = 1
                if existing and existing.get("dev") == interface:
                    # The route already targets the VPN device but may use a higher
                    # metric than competing paths. Force a low metric and record the
                    # previous attributes so they can be restored after disconnect.
                    LOGGER.info(
                        "Route %s already uses interface %s; ensuring preferred metric",
                        command_destination,
                        interface,
                    )
                    ensure_cmd = self._build_route_command(
                        "change",
                        command_destination,
                        interface,
                        family,
                        metric_hint,
                    )
                    code, stdout, stderr = self._run_privileged(ensure_cmd)
                    if code != 0:
                        LOGGER.debug(
                            "Route %s metric update skipped: %s",
                            destination,
                            (stderr.strip() or stdout.strip()),
                        )
                        continue
                    applied.append(
                        AppliedRoute(
                            command_destination,
                            interface,
                            family,
                            replaced=True,
                            previous=existing,
                        )
                    )
                    continue
                try:
                    cmd = self._build_route_command(
                        "add",
                        command_destination,
                        interface,
                        family,
                        metric_hint,
                    )
                    code, stdout, stderr = self._run_privileged(cmd)
                    if code != 0:
                        message = stderr.strip() or stdout.strip()
                        if "exists" in message.lower():
                            if existing_prefix is not None and new_prefix is not None and new_prefix > existing_prefix:
                                replace_cmd = self._build_route_command(
                                    "replace",
                                    command_destination,
                                    interface,
                                    family,
                                    metric_hint,
                                )
                                repl_code, repl_stdout, repl_stderr = self._run_privileged(replace_cmd)
                                if repl_code != 0:
                                    LOGGER.error(
                                        "Failed to install more specific route %s via %s: %s",
                                        command_destination,
                                        interface,
                                        repl_stderr.strip() or repl_stdout.strip(),
                                    )
                                    continue
                                applied.append(
                                    AppliedRoute(
                                        command_destination,
                                        interface,
                                        family,
                                    )
                                )
                                LOGGER.info(
                                    "Route %s added via %s (preferred over existing %s)",
                                    command_destination,
                                    interface,
                                    existing.get("destination", "unknown"),
                                )
                                continue
                            if not existing:
                                LOGGER.error(
                                    "Route %s already exists but could not capture current entry; skipping",
                                    command_destination,
                                )
                                continue
                            replace_cmd = self._build_route_command(
                                "replace",
                                command_destination,
                                interface,
                                family,
                                metric_hint,
                            )
                            repl_code, repl_stdout, repl_stderr = self._run_privileged(replace_cmd)
                            if repl_code != 0:
                                LOGGER.error(
                                    "Failed to replace existing route %s via %s: %s",
                                    command_destination,
                                    interface,
                                    repl_stderr.strip() or repl_stdout.strip(),
                                )
                                continue
                            applied.append(
                                AppliedRoute(
                                    command_destination,
                                    interface,
                                    family,
                                    replaced=True,
                                    previous=existing,
                                )
                            )
                            LOGGER.info(
                                "Route %s replaced with interface %s",
                                command_destination,
                                interface,
                            )
                            continue
                        LOGGER.error(
                            "Failed to add route %s via %s: %s",
                            command_destination,
                            interface,
                            message,
                        )
                        continue
                    applied.append(AppliedRoute(command_destination, interface, family))
                    LOGGER.info("Route %s added via %s", command_destination, interface)
                except Exception as exc:
                    LOGGER.exception("Exception while adding route %s: %s", command_destination, exc)
        if applied:
            self._session_routes[session_id] = applied

    def cleanup(self, session_id: str) -> None:
        applied = self._session_routes.pop(session_id, [])
        if not applied:
            return
        LOGGER.info("Cleaning custom routes for session %s", session_id)
        for route in applied:
            try:
                if route.replaced and route.previous:
                    self._restore_previous_route(route)
                    continue
                cmd = self._build_route_command(
                    "del", route.destination, route.interface, route.family
                )
                code, stdout, stderr = self._run_privileged(cmd)
                if code != 0:
                    message = stderr.strip() or stdout.strip()
                    lowered = message.lower()
                    if "cannot find device" in lowered or "no such device" in lowered:
                        fallback_cmd = ["ip"]
                        if route.family == 6:
                            fallback_cmd.append("-6")
                        fallback_cmd.extend(["route", "del", route.destination])
                        fb_code, fb_stdout, fb_stderr = self._run_privileged(fallback_cmd)
                        if fb_code == 0:
                            LOGGER.info(
                                "Route %s removed (interface %s already absent)",
                                route.destination,
                                route.interface,
                            )
                            continue
                        fb_message = fb_stderr.strip() or fb_stdout.strip()
                        if "no such process" in fb_message.lower():
                            LOGGER.info(
                                "Route %s no longer present during cleanup", route.destination
                            )
                            continue
                        LOGGER.warning(
                            "Failed to remove route %s after fallback: %s",
                            route.destination,
                            fb_message,
                        )
                        continue
                    LOGGER.warning(
                        "Failed to remove route %s: %s", route.destination, message
                    )
                else:
                    LOGGER.info("Route %s removed", route.destination)
            except Exception as exc:
                LOGGER.exception("Exception while removing route %s: %s", route.destination, exc)
