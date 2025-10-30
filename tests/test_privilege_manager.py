"""Unit tests for the PrivilegeManager password caching behaviour."""

from __future__ import annotations

from typing import List, Optional

import pytest

from core.privilege import PrivilegeManager, PasswordResponse


class _Provider:
    """Test double for supplying sudo passwords."""

    def __init__(self, responses: List[Optional[PasswordResponse]]):
        self._responses = responses
        self.calls = 0

    def __call__(self) -> Optional[PasswordResponse]:
        if self.calls >= len(self._responses):
            raise AssertionError("Password provider called more times than expected")
        response = self._responses[self.calls]
        self.calls += 1
        return response


@pytest.fixture()
def sudo_capable_manager(monkeypatch):
    """Provide a PrivilegeManager configured to use sudo for privileged commands."""

    provider = _Provider([("secret", False)])
    manager = PrivilegeManager(provider)

    # Force the manager to use sudo without invoking the system lookup during tests.
    monkeypatch.setattr(manager, "_pkexec_path", None)
    monkeypatch.setattr(manager, "_sudo_path", "/usr/bin/sudo")

    return manager, provider


def test_force_allow_sets_cache_flag(sudo_capable_manager):
    """force_allow=True should permit reusing the cached sudo password."""

    manager, provider = sudo_capable_manager

    manager.ensure_password_cached(force_allow=True)

    assert manager.password_cached() is True
    assert manager.cache_allowed() is True
    assert provider.calls == 1


def test_cache_password_for_session_enables_reuse(monkeypatch):
    """cache_password_for_session should mark the stored password reusable."""

    provider = _Provider([("token", False)])
    manager = PrivilegeManager(provider)

    monkeypatch.setattr(manager, "_pkexec_path", None)
    monkeypatch.setattr(manager, "_sudo_path", "/usr/bin/sudo")

    manager.cache_password_for_session()

    assert manager.cache_allowed() is True
    assert manager.password_cached() is True
    assert provider.calls == 1


def test_build_command_returns_cached_password(sudo_capable_manager):
    """build_command should return the cached password when reuse is permitted."""

    manager, provider = sudo_capable_manager

    # First call enables caching, second ensures it can reuse the stored password.
    manager.ensure_password_cached(force_allow=True)

    argv, password = manager.build_command(["echo", "hello"])

    assert argv[:2] == ["/usr/bin/sudo", "-S"]
    assert argv[2:] == ["echo", "hello"]
    assert password == "secret"
    assert provider.calls == 1
