"""Unit tests for the RouteManager VPN route management helpers."""

from __future__ import annotations

from collections import namedtuple
from typing import Dict, Iterable, List, Tuple

import socket
import pytest

pytest.importorskip("psutil")

from core.routing import RouteManager


class DummyPrivilegeManager:
    """Minimal privilege manager stub for exercising RouteManager."""

    def build_command(self, command: List[str]) -> Tuple[List[str], None]:
        return command, None


@pytest.fixture(autouse=True)
def mock_interfaces(monkeypatch):
    """Ensure a predictable network interface list for the tests."""

    monkeypatch.setattr(
        "core.routing.psutil.net_if_addrs", lambda: {"ppp0": [], "lo": []}
    )


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Remove delays introduced by backoff and interface settling."""

    monkeypatch.setattr("core.routing.time.sleep", lambda *_: None)


@pytest.fixture()
def route_manager(monkeypatch):
    """Return a RouteManager instance with a stub privilege manager."""

    manager = RouteManager(DummyPrivilegeManager())
    monkeypatch.setattr(manager, "_capture_existing_route", lambda *_: [])
    return manager


def test_apply_routes_uses_ipv6_flag(route_manager, monkeypatch):
    """IPv6 targets should be managed using ``ip -6`` commands."""

    commands: List[List[str]] = []

    def fake_run(command: List[str]):
        commands.append(command)
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    route_manager.apply_routes("session", ["2001:db8::/32"], "ppp0")
    assert commands == [
        ["ip", "-6", "route", "add", "2001:db8::/32", "dev", "ppp0", "metric", "0"]
    ]
    applied_routes = route_manager._session_routes["session"]
    assert len(applied_routes) == 1
    assert applied_routes[0].family == 6

    commands.clear()
    route_manager.cleanup("session")
    assert commands == [
        ["ip", "-6", "route", "del", "2001:db8::/32", "dev", "ppp0"],
        ["ip", "-6", "route", "flush", "cache"],
    ]
    assert "session" not in route_manager._session_routes


def test_apply_routes_keeps_ipv4_commands(route_manager, monkeypatch):
    """IPv4 targets should keep the default ``ip route`` invocation."""

    commands: List[List[str]] = []

    def fake_run(command: List[str]):
        commands.append(command)
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    route_manager.apply_routes("session4", ["10.0.0.0/24"], "ppp0")
    assert commands == [
        ["ip", "route", "add", "10.0.0.0/24", "dev", "ppp0", "metric", "0"]
    ]
    applied_routes = route_manager._session_routes["session4"]
    assert len(applied_routes) == 1
    assert applied_routes[0].family == 4

    commands.clear()
    route_manager.cleanup("session4")
    assert commands == [
        ["ip", "route", "del", "10.0.0.0/24", "dev", "ppp0"],
        ["ip", "route", "flush", "cache"],
    ]
    assert "session4" not in route_manager._session_routes


def test_apply_routes_normalizes_host_targets(route_manager, monkeypatch):
    """Host addresses should be normalized to explicit /32 routes."""

    commands: List[List[str]] = []

    def fake_run(command: List[str]):
        commands.append(command)
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    route_manager.apply_routes("host", ["192.0.2.5"], "ppp0")
    assert commands == [
        ["ip", "route", "add", "192.0.2.5/32", "dev", "ppp0", "metric", "0"]
    ]
    commands.clear()

    route_manager.cleanup("host")
    assert commands == [
        ["ip", "route", "del", "192.0.2.5/32", "dev", "ppp0"],
        ["ip", "route", "flush", "cache"],
    ]
    assert "host" not in route_manager._session_routes


def test_apply_routes_removes_existing_duplicates(route_manager, monkeypatch):
    """Duplicate routes should be flushed before installing the override."""

    commands: List[List[str]] = []

    def fake_run(command: List[str]):
        commands.append(command)
        return 0, "", ""

    duplicates: List[Dict[str, str]] = [
        {
            "destination": "10.0.0.0/24",
            "dev": "eth0",
            "via": "192.168.1.1",
            "metric": "100",
        },
        {"destination": "10.0.0.0/24", "dev": "wlan0", "metric": "200"},
    ]

    captures: Iterable[List[Dict[str, str]]] = iter([duplicates, []])

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)
    monkeypatch.setattr(
        route_manager, "_capture_existing_route", lambda *_: next(captures, [])
    )

    route_manager.apply_routes("duplicates", ["10.0.0.0/24"], "ppp0")

    assert commands == [
        ["ip", "route", "del", "10.0.0.0/24"],
        ["ip", "route", "del", "10.0.0.0/24", "dev", "eth0"],
        ["ip", "route", "del", "10.0.0.0/24", "dev", "wlan0"],
        ["ip", "route", "flush", "cache"],
        ["ip", "route", "add", "10.0.0.0/24", "dev", "ppp0", "metric", "0"],
    ]

    applied_routes = route_manager._session_routes["duplicates"]
    assert len(applied_routes) == 1
    assert applied_routes[0].replaced
    assert applied_routes[0].previous == duplicates[0]
    assert applied_routes[0].removed == duplicates


def test_cleanup_restores_removed_routes(route_manager, monkeypatch):
    """Removed routes should be restored on cleanup."""

    commands: List[List[str]] = []

    def fake_run(command: List[str]):
        commands.append(command)
        return 0, "", ""

    duplicates: List[Dict[str, str]] = [
        {
            "destination": "203.0.113.0/24",
            "dev": "eth0",
            "via": "192.168.1.1",
            "metric": "100",
        },
        {"destination": "203.0.113.0/24", "dev": "wlan0", "metric": "200"},
    ]

    captures: Iterable[List[Dict[str, str]]] = iter([duplicates, []])

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)
    monkeypatch.setattr(
        route_manager, "_capture_existing_route", lambda *_: next(captures, [])
    )

    route_manager.apply_routes("restore", ["203.0.113.0/24"], "ppp0")
    commands.clear()

    route_manager.cleanup("restore")

    assert commands == [
        ["ip", "route", "del", "203.0.113.0/24", "dev", "ppp0"],
        ["ip", "route", "flush", "cache"],
        [
            "ip",
            "route",
            "replace",
            "203.0.113.0/24",
            "via",
            "192.168.1.1",
            "dev",
            "eth0",
            "metric",
            "100",
        ],
        ["ip", "route", "flush", "cache"],
    ]
    assert "restore" not in route_manager._session_routes


def test_apply_routes_skips_vpn_endpoint_addresses(route_manager, monkeypatch):
    """Host routes targeting VPN interface addresses should be ignored."""

    commands: List[List[str]] = []

    def fake_run(command: List[str]):
        commands.append(command)
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    Address = namedtuple("Address", ["family", "address", "netmask", "broadcast", "ptp"])

    def fake_addrs():
        return {
            "ppp0": [Address(socket.AF_INET, "10.0.0.2", None, None, None)],
            "ppp1": [Address(socket.AF_INET, "10.0.1.2", None, None, None)],
        }

    monkeypatch.setattr("core.routing.psutil.net_if_addrs", fake_addrs)

    route_manager.apply_routes(
        "vpn",
        ["10.0.0.2", "10.0.1.2", "198.51.100.10"],
        "ppp0",
    )

    assert commands == [
        ["ip", "route", "add", "198.51.100.10/32", "dev", "ppp0", "metric", "0"]
    ]
    applied_routes = route_manager._session_routes["vpn"]
    assert len(applied_routes) == 1
    assert applied_routes[0].destination == "198.51.100.10/32"

    commands.clear()
    route_manager.cleanup("vpn")
    assert commands == [
        ["ip", "route", "del", "198.51.100.10/32", "dev", "ppp0"],
        ["ip", "route", "flush", "cache"],
    ]
    assert "vpn" not in route_manager._session_routes


def test_cleanup_handles_failed_delete(route_manager, monkeypatch):
    """Cleanup should continue even when deleting the override fails."""

    commands: List[List[str]] = []

    def fake_run(command: List[str]):
        commands.append(command)
        if command[2] == "del":
            return 2, "", 'Cannot find device "ppp0"'
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    route_manager.apply_routes("missing", ["192.0.2.5"], "ppp0")
    commands.clear()

    route_manager.cleanup("missing")

    assert commands == [
        ["ip", "route", "del", "192.0.2.5/32", "dev", "ppp0"],
        ["ip", "route", "flush", "cache"],
    ]
    assert "missing" not in route_manager._session_routes
