"""Unit tests for the RouteManager IP family detection logic."""

from __future__ import annotations

from typing import Dict, List, Tuple

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


@pytest.fixture()
def route_manager(monkeypatch):
    """Return a RouteManager instance with a stub privilege manager."""

    manager = RouteManager(DummyPrivilegeManager())
    monkeypatch.setattr(manager, "_capture_existing_route", lambda *_: None)
    return manager


def test_apply_routes_uses_ipv6_flag(route_manager, monkeypatch):
    """IPv6 targets should be managed using ``ip -6`` commands."""

    commands = []

    def fake_run(command):
        commands.append(command)
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    route_manager.apply_routes("session", ["2001:db8::/32"], "ppp0")
    assert commands == [
        ["ip", "-6", "route", "add", "2001:db8::/32", "dev", "ppp0", "metric", "1"]
    ]
    applied_routes = route_manager._session_routes["session"]
    assert len(applied_routes) == 1
    assert applied_routes[0].family == 6

    commands.clear()
    route_manager.cleanup("session")
    assert commands == [["ip", "-6", "route", "del", "2001:db8::/32", "dev", "ppp0"]]
    assert "session" not in route_manager._session_routes


def test_apply_routes_keeps_ipv4_commands(route_manager, monkeypatch):
    """IPv4 targets should keep the default ``ip route`` invocation."""

    commands = []

    def fake_run(command):
        commands.append(command)
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    route_manager.apply_routes("session4", ["10.0.0.0/24"], "ppp0")
    assert commands == [["ip", "route", "add", "10.0.0.0/24", "dev", "ppp0", "metric", "1"]]
    applied_routes = route_manager._session_routes["session4"]
    assert len(applied_routes) == 1
    assert applied_routes[0].family == 4

    commands.clear()
    route_manager.cleanup("session4")
    assert commands == [["ip", "route", "del", "10.0.0.0/24", "dev", "ppp0"]]
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
        ["ip", "route", "add", "192.0.2.5/32", "dev", "ppp0", "metric", "1"]
    ]
    commands.clear()

    route_manager.cleanup("host")
    assert commands == [["ip", "route", "del", "192.0.2.5/32", "dev", "ppp0"]]
    assert "host" not in route_manager._session_routes


def test_apply_routes_prefers_more_specific_over_existing(route_manager, monkeypatch):
    """More specific routes should be installed alongside broader ones."""

    commands: List[List[str]] = []

    def fake_run(command: List[str]):
        commands.append(command)
        if command[2] == "add":
            return 2, "", "RTNETLINK answers: File exists"
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    existing_route: Dict[str, str] = {"destination": "10.0.0.0/16", "dev": "eth0", "metric": "100"}
    monkeypatch.setattr(route_manager, "_capture_existing_route", lambda *_: existing_route)

    route_manager.apply_routes("specific", ["10.0.0.0/24"], "ppp0")
    assert commands == [
        ["ip", "route", "add", "10.0.0.0/24", "dev", "ppp0", "metric", "1"],
        ["ip", "route", "replace", "10.0.0.0/24", "dev", "ppp0", "metric", "1"],
    ]

    applied_routes = route_manager._session_routes["specific"]
    assert len(applied_routes) == 1
    assert applied_routes[0].destination == "10.0.0.0/24"
    assert not applied_routes[0].replaced

    commands.clear()
    route_manager.cleanup("specific")
    assert commands == [["ip", "route", "del", "10.0.0.0/24", "dev", "ppp0"]]
    assert "specific" not in route_manager._session_routes


def test_apply_routes_replaces_matching_prefix_and_restores(route_manager, monkeypatch):
    """Routes sharing the same prefix should be replaced and restored on cleanup."""

    commands: List[List[str]] = []

    def fake_run(command: List[str]):
        commands.append(command)
        if command[2] == "add":
            return 2, "", "File exists"
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    previous_route: Dict[str, str] = {
        "destination": "10.0.0.0/24",
        "dev": "eth0",
        "via": "192.168.1.1",
        "metric": "100",
    }
    monkeypatch.setattr(route_manager, "_capture_existing_route", lambda *_: previous_route)

    route_manager.apply_routes("replace", ["10.0.0.0/24"], "ppp0")
    assert commands == [
        ["ip", "route", "add", "10.0.0.0/24", "dev", "ppp0", "metric", "1"],
        ["ip", "route", "replace", "10.0.0.0/24", "dev", "ppp0", "metric", "1"],
    ]

    applied_routes = route_manager._session_routes["replace"]
    assert len(applied_routes) == 1
    assert applied_routes[0].replaced
    assert applied_routes[0].previous == previous_route

    commands.clear()
    route_manager.cleanup("replace")
    assert commands == [
        [
            "ip",
            "route",
            "replace",
            "10.0.0.0/24",
            "via",
            "192.168.1.1",
            "dev",
            "eth0",
            "metric",
            "100",
        ]
    ]
    assert "replace" not in route_manager._session_routes


def test_cleanup_handles_missing_interface(route_manager, monkeypatch):
    """Cleaning up should succeed even if the VPN device has disappeared."""

    commands: List[List[str]] = []

    def fake_run(command: List[str]):
        commands.append(command)
        if command[2] == "add":
            return 0, "", ""
        if command[2] == "del" and len(command) > 4:
            return 2, "", 'Cannot find device "ppp0"'
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    route_manager.apply_routes("missing", ["192.0.2.5"], "ppp0")
    commands.clear()

    route_manager.cleanup("missing")
    assert commands == [
        ["ip", "route", "del", "192.0.2.5/32", "dev", "ppp0"],
        ["ip", "route", "del", "192.0.2.5/32"],
    ]
    assert "missing" not in route_manager._session_routes
