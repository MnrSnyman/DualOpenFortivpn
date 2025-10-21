"""Unit tests for the RouteManager IP family detection logic."""

from __future__ import annotations

from typing import List, Tuple

import pytest

pytest.importorskip("psutil")

from core.routing import RouteManager


class DummyPrivilegeManager:
    """Minimal privilege manager stub for exercising RouteManager."""

    def build_command(self, command: List[str]) -> Tuple[List[str], None]:
        return command, None


@pytest.fixture()
def route_manager():
    """Return a RouteManager instance with a stub privilege manager."""

    return RouteManager(DummyPrivilegeManager())


def test_apply_routes_uses_ipv6_flag(route_manager, monkeypatch):
    """IPv6 targets should be managed using ``ip -6`` commands."""

    commands = []

    def fake_run(command):
        commands.append(command)
        return 0, "", ""

    monkeypatch.setattr(route_manager, "_run_privileged", fake_run)

    route_manager.apply_routes("session", ["2001:db8::/32"], "ppp0")
    assert commands == [["ip", "-6", "route", "add", "2001:db8::/32", "dev", "ppp0"]]
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
    assert commands == [["ip", "route", "add", "10.0.0.0/24", "dev", "ppp0"]]
    applied_routes = route_manager._session_routes["session4"]
    assert len(applied_routes) == 1
    assert applied_routes[0].family == 4

    commands.clear()
    route_manager.cleanup("session4")
    assert commands == [["ip", "route", "del", "10.0.0.0/24", "dev", "ppp0"]]
    assert "session4" not in route_manager._session_routes
