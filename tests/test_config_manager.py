"""Regression tests for the configuration manager persistence layer."""

from __future__ import annotations

import importlib
import sys
import threading
from pathlib import Path

import pytest

from core.vpn_profile import VPNProfile

# Skip the suite if PyYAML is unavailable; the production code requires it and
# these tests exercise the same module imports.
pytest.importorskip("yaml")


@pytest.fixture()
def config_manager(tmp_path, monkeypatch):
    """Provide a ConfigManager instance rooted at a temporary config directory."""

    # Redirect Path.home() to the temporary directory so that all computed
    # configuration paths live under the pytest-provided sandbox.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Reload modules that cache configuration paths to ensure they pick up the
    # patched home directory for the duration of the test.
    for module_name in ["core.app_paths", "config.manager"]:
        sys.modules.pop(module_name, None)

    manager_module = importlib.import_module("config.manager")
    manager = manager_module.ConfigManager()

    yield manager

    # Cleanup cached modules so subsequent tests or application code reload the
    # real configuration paths.
    for module_name in ["config.manager", "core.app_paths"]:
        sys.modules.pop(module_name, None)


def test_upsert_saves_without_deadlock(config_manager):
    """upsert() should not deadlock even though it calls save() internally."""

    profile = VPNProfile(
        name="threaded",
        host="vpn.example.com",
        port=443,
        auth_type="password",
    )

    thread = threading.Thread(target=config_manager.upsert, args=(profile,), daemon=True)
    thread.start()
    thread.join(timeout=2)

    assert not thread.is_alive(), "upsert should complete without hanging"
    assert config_manager.get("threaded") is not None


def test_remove_saves_without_deadlock(config_manager):
    """remove() should persist changes without deadlocking the calling thread."""

    profile = VPNProfile(
        name="remove-me",
        host="vpn.example.com",
        port=443,
        auth_type="password",
    )

    # Seed the configuration file with an entry to remove.
    config_manager.upsert(profile)

    thread = threading.Thread(target=config_manager.remove, args=("remove-me",), daemon=True)
    thread.start()
    thread.join(timeout=2)

    assert not thread.is_alive(), "remove should complete without hanging"
    assert config_manager.get("remove-me") is None
