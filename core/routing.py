"""Routing helper utilities for applying and cleaning up VPN routes."""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import time
from dataclasses import dataclass, field
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
    removed: List[Dict[str, str]] = field(default_factory=list)


class RouteManager:
    """Compute and apply custom routes for VPN sessions."""

    def __init__(self, privilege_manager: PrivilegeManager) -> None:
        self._privilege_manager = privilege_manager
        self._session_routes: Dict[str, List[AppliedRoute]] = {}
        self._pending_restores: Dict[str, List[Tuple[int, Dict[str, str]]]] = {}

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
        interface: Optional[str],
        family: int,
        metric: Optional[int] = None,
    ) -> List[str]:
        """Construct the ip route command for IPv4 or IPv6 targets."""
        command = ["ip"]
        if family == 6:
            command.append("-6")
        command.extend(["route", action, destination])
        if interface:
            command.extend(["dev", interface])
        if metric is not None:
            command.extend(["metric", str(metric)])
        return command

    def _capture_existing_route(self, destination: str, family: int) -> List[Dict[str, str]]:
        """Return all matching routes so they can be restored later."""
        command = ["ip"]
        if family == 6:
            command.append("-6")
        command.extend(["route", "show", destination])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return []
        lines = result.stdout.strip().splitlines()
        if not lines:
            return []
        routes: List[Dict[str, str]] = []
        for raw in lines:
            parsed = self._parse_route_line(raw)
            if parsed:
                routes.append(parsed)
        return routes

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

    def _restore_previous_route(self, route: AppliedRoute, data: Optional[Dict[str, str]] = None) -> bool:
        entry = data or route.previous
        if not entry:
            return False
        command = ["ip"]
        if route.family == 6:
            command.append("-6")
        command.extend(["route", "replace", entry["destination"]])
        if "via" in entry:
            command.extend(["via", entry["via"]])
        if "dev" in entry:
            command.extend(["dev", entry["dev"]])
        if "metric" in entry:
            command.extend(["metric", entry["metric"]])
        code, stdout, stderr = self._run_privileged(command)
        if code != 0:
            message = stderr.strip() or stdout.strip()
            LOGGER.warning(
                "[%s] RESTORE %s failed: %s",
                entry.get("dev", "system"),
                entry["destination"],
                message,
            )
            return False
        LOGGER.info(
            "[%s] RESTORE %s metric %s – success",
            entry.get("dev", "system"),
            entry["destination"],
            entry.get("metric", "0"),
        )
        return True

    def _restore_removed_routes(
        self,
        session_id: str,
        interface: str,
        destination: str,
        family: int,
        removed_entries: List[Dict[str, str]],
    ) -> None:
        if not removed_entries:
            return
        LOGGER.info(
            "[%s] RESTORE %s – reapplying %d previously removed route(s)",
            interface,
            destination,
            len(removed_entries),
        )
        restoration = AppliedRoute(destination=destination, interface=interface, family=family)
        failed: List[Tuple[int, Dict[str, str]]] = []
        restored = False
        for entry in removed_entries:
            if self._restore_previous_route(restoration, entry):
                restored = True
            else:
                failed.append((family, entry))
        if restored:
            flush_cmd = ["ip"]
            if family == 6:
                flush_cmd.append("-6")
            flush_cmd.extend(["route", "flush", "cache"])
            code, stdout, stderr = self._run_privileged(flush_cmd)
            message = stderr.strip() or stdout.strip()
            if code == 0:
                LOGGER.info("[system] FLUSH route cache")
            elif message:
                LOGGER.warning("[system] FLUSH route cache failed: %s", message)
        if failed:
            LOGGER.warning(
                "Session %s still has %d original route(s) pending restoration for %s",
                session_id,
                len(failed),
                destination,
            )
            self._pending_restores.setdefault(session_id, []).extend(failed)

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
        # Give the PPP/TUN device time to settle before manipulating the table.
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
        time.sleep(1)
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
                attempt = 0
                removed_entries: List[Dict[str, str]] = []
                seen_signatures: set[Tuple[str, str, str, str]] = set()
                while True:
                    duplicates = self._capture_existing_route(command_destination, family)
                    if duplicates:
                        LOGGER.info(
                            "[%s] DELETE %s – removing %d existing entries",
                            interface,
                            command_destination,
                            len(duplicates),
                        )
                        general_delete = self._build_route_command("del", command_destination, None, family)
                        code, stdout, stderr = self._run_privileged(general_delete)
                        message = stderr.strip() or stdout.strip()
                        if code == 0:
                            LOGGER.info("[system] DELETE %s – duplicate removed", command_destination)
                        elif message:
                            LOGGER.debug("[system] DELETE %s – %s", command_destination, message)
                        for existing_entry in duplicates:
                            signature = (
                                existing_entry.get("destination", ""),
                                existing_entry.get("dev", ""),
                                existing_entry.get("via", ""),
                                existing_entry.get("metric", ""),
                            )
                            if signature not in seen_signatures:
                                removed_entries.append(existing_entry)
                                seen_signatures.add(signature)
                            existing_iface = existing_entry.get("dev")
                            if existing_iface:
                                specific_delete = self._build_route_command(
                                    "del",
                                    command_destination,
                                    existing_iface,
                                    family,
                                )
                                code, stdout, stderr = self._run_privileged(specific_delete)
                                message = stderr.strip() or stdout.strip()
                                if code == 0:
                                    LOGGER.info(
                                        "[%s] DELETE %s – duplicate removed",
                                        existing_iface,
                                        command_destination,
                                    )
                                elif message:
                                    LOGGER.debug(
                                        "[%s] DELETE %s – %s",
                                        existing_iface,
                                        command_destination,
                                        message,
                                    )
                        flush_cmd = ["ip"]
                        if family == 6:
                            flush_cmd.append("-6")
                        flush_cmd.extend(["route", "flush", "cache"])
                        code, stdout, stderr = self._run_privileged(flush_cmd)
                        message = stderr.strip() or stdout.strip()
                        if code == 0:
                            LOGGER.info("[system] FLUSH route cache")
                        elif message:
                            LOGGER.warning("[system] FLUSH route cache failed: %s", message)
                    add_cmd = self._build_route_command(
                        "add",
                        command_destination,
                        interface,
                        family,
                        0,
                    )
                    code, stdout, stderr = self._run_privileged(add_cmd)
                    message = stderr.strip() or stdout.strip()
                    if code == 0:
                        LOGGER.info("[%s] ADD %s metric 0 – success", interface, command_destination)
                        applied_route = AppliedRoute(
                            destination=command_destination,
                            interface=interface,
                            family=family,
                            replaced=bool(removed_entries),
                            previous=removed_entries[0] if removed_entries else None,
                        )
                        if removed_entries:
                            applied_route.removed.extend(removed_entries)
                        confirm = self._capture_existing_route(command_destination, family)
                        if any(item.get("dev") == interface for item in confirm):
                            LOGGER.info(
                                "[%s] VERIFY %s via %s – confirmed",
                                interface,
                                command_destination,
                                interface,
                            )
                        else:
                            LOGGER.warning(
                                "[%s] VERIFY %s – expected interface %s not found",
                                interface,
                                command_destination,
                                interface,
                            )
                        applied.append(applied_route)
                        break
                    if message and "exists" in message.lower() and attempt == 0:
                        LOGGER.info(
                            "[system] RETRY %s – duplicate detected, retrying once",
                            command_destination,
                        )
                        attempt += 1
                        time.sleep(0.5)
                        continue
                    LOGGER.error(
                        "[%s] ADD %s metric 0 failed: %s",
                        interface,
                        command_destination,
                        message or "unknown error",
                    )
                    if removed_entries:
                        self._restore_removed_routes(
                            session_id,
                            interface,
                            command_destination,
                            family,
                            removed_entries,
                        )
                    break
        if applied:
            self._session_routes[session_id] = applied

    def cleanup(self, session_id: str) -> None:
        applied = self._session_routes.pop(session_id, [])
        pending = self._pending_restores.pop(session_id, [])
        if not applied and not pending:
            return
        LOGGER.info("Cleaning custom routes for session %s", session_id)
        for route in applied:
            try:
                LOGGER.info(
                    "[%s] DISCONNECTED – removing overrides for %s",
                    route.interface,
                    route.destination,
                )
                delete_cmd = self._build_route_command(
                    "del",
                    route.destination,
                    route.interface,
                    route.family,
                )
                code, stdout, stderr = self._run_privileged(delete_cmd)
                message = stderr.strip() or stdout.strip()
                if code == 0:
                    LOGGER.info(
                        "[%s] DELETE %s – removed",
                        route.interface,
                        route.destination,
                    )
                elif message:
                    LOGGER.warning(
                        "[%s] DELETE %s failed: %s",
                        route.interface,
                        route.destination,
                        message,
                    )
                flush_cmd = ["ip"]
                if route.family == 6:
                    flush_cmd.append("-6")
                flush_cmd.extend(["route", "flush", "cache"])
                flush_code, flush_stdout, flush_stderr = self._run_privileged(flush_cmd)
                flush_message = flush_stderr.strip() or flush_stdout.strip()
                if flush_code == 0:
                    LOGGER.info("[system] FLUSH route cache")
                elif flush_message:
                    LOGGER.warning("[system] FLUSH route cache failed: %s", flush_message)

                restored = False
                normalized_destination = route.destination
                current_interfaces = set(psutil.net_if_addrs().keys())
                for other_session, routes in self._session_routes.items():
                    if restored:
                        break
                    for other_route in routes:
                        other_destination = self._normalize_destination(
                            other_route.destination,
                            other_route.family,
                        )
                        if other_destination != normalized_destination:
                            continue
                        if other_route.interface not in current_interfaces:
                            LOGGER.debug(
                                "[%s] RESTORE %s skipped – interface unavailable",
                                other_route.interface,
                                normalized_destination,
                            )
                            continue
                        add_cmd = self._build_route_command(
                            "add",
                            normalized_destination,
                            other_route.interface,
                            other_route.family,
                            0,
                        )
                        code, stdout, stderr = self._run_privileged(add_cmd)
                        message = stderr.strip() or stdout.strip()
                        if code == 0:
                            LOGGER.info(
                                "[%s] RESTORE %s metric 0 – success",
                                other_route.interface,
                                normalized_destination,
                            )
                            restored = True
                        elif message and "exists" in message.lower():
                            LOGGER.info(
                                "[%s] RESTORE %s metric 0 – already present",
                                other_route.interface,
                                normalized_destination,
                            )
                            restored = True
                        elif message:
                            LOGGER.error(
                                "[%s] RESTORE %s metric 0 failed: %s",
                                other_route.interface,
                                normalized_destination,
                                message,
                            )
                        retry_flush_code, retry_flush_stdout, retry_flush_stderr = self._run_privileged(flush_cmd)
                        retry_message = retry_flush_stderr.strip() or retry_flush_stdout.strip()
                        if retry_flush_code == 0:
                            LOGGER.info("[system] FLUSH route cache")
                        elif retry_message:
                            LOGGER.warning("[system] FLUSH route cache failed: %s", retry_message)
                        if restored:
                            other_route.replaced = False
                            break
                if restored:
                    continue
                for entry in route.removed:
                    if self._restore_previous_route(route, entry):
                        flush_code, flush_stdout, flush_stderr = self._run_privileged(flush_cmd)
                        flush_message = flush_stderr.strip() or flush_stdout.strip()
                        if flush_code == 0:
                            LOGGER.info("[system] FLUSH route cache")
                        elif flush_message:
                            LOGGER.warning("[system] FLUSH route cache failed: %s", flush_message)
                        restored = True
                        break
                if restored:
                    continue
                if route.previous and self._restore_previous_route(route):
                    flush_code, flush_stdout, flush_stderr = self._run_privileged(flush_cmd)
                    flush_message = flush_stderr.strip() or flush_stdout.strip()
                    if flush_code == 0:
                        LOGGER.info("[system] FLUSH route cache")
                    elif flush_message:
                        LOGGER.warning("[system] FLUSH route cache failed: %s", flush_message)
                    continue
                LOGGER.info(
                    "[%s] DISCONNECTED – no restoration target for %s",
                    route.interface,
                    route.destination,
                )
            except Exception as exc:
                LOGGER.exception("Exception while removing route %s: %s", route.destination, exc)
        if pending:
            LOGGER.info(
                "Session %s has %d pending restoration(s) for system routes; attempting to reinstate them",
                session_id,
                len(pending),
            )
            restored_families: set[int] = set()
            for family, entry in pending:
                restoration = AppliedRoute(
                    destination=entry["destination"],
                    interface=entry.get("dev", "system"),
                    family=family,
                )
                if self._restore_previous_route(restoration, entry):
                    restored_families.add(family)
            for family in restored_families:
                flush_cmd = ["ip"]
                if family == 6:
                    flush_cmd.append("-6")
                flush_cmd.extend(["route", "flush", "cache"])
                flush_code, flush_stdout, flush_stderr = self._run_privileged(flush_cmd)
                flush_message = flush_stderr.strip() or flush_stdout.strip()
                if flush_code == 0:
                    LOGGER.info("[system] FLUSH route cache")
                elif flush_message:
                    LOGGER.warning("[system] FLUSH route cache failed: %s", flush_message)
