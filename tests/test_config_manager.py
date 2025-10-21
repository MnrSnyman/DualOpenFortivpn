"""Tests for the configuration manager locking behaviour."""

from __future__ import annotations

import importlib
import threading
import sys

import pytest

from core import app_paths as app_paths_module
from core.vpn_profile import VPNProfile


@pytest.fixture()
def config_manager(tmp_path, monkeypatch):
    """Provide a ``ConfigManager`` instance writing into a temporary directory."""
    config_root = tmp_path / "config"
    log_dir = config_root / "logs"
    config_file = config_root / "profiles.yaml"
    readme_file = config_root / "README.txt"
    desktop_file = tmp_path / "OpenFortiVPN-Manager.desktop"

    monkeypatch.setattr(app_paths_module, "CONFIG_ROOT", config_root, raising=False)
    monkeypatch.setattr(app_paths_module, "LOG_DIR", log_dir, raising=False)
    monkeypatch.setattr(app_paths_module, "CONFIG_FILE", config_file, raising=False)
    monkeypatch.setattr(app_paths_module, "README_FILE", readme_file, raising=False)
    monkeypatch.setattr(app_paths_module, "DESKTOP_FILE", desktop_file, raising=False)

    sys.modules.pop("config.manager", None)
    manager_module = importlib.import_module("config.manager")
    manager = manager_module.ConfigManager()

    try:
        yield manager
    finally:
        monkeypatch.undo()
        importlib.reload(manager_module)


def _run_in_thread(target, *args, timeout=1.0):
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    assert not thread.is_alive(), "operation did not finish before timeout"


def _create_profile(name: str = "test-profile") -> VPNProfile:
    return VPNProfile(
        name=name,
        host="vpn.example.com",
        port=443,
        auth_type="password",
    )


def test_upsert_does_not_deadlock(config_manager):
    profile = _create_profile()
    _run_in_thread(config_manager.upsert, profile)
    assert config_manager.get(profile.name) is not None


def test_remove_does_not_deadlock(config_manager):
    profile = _create_profile("removable")
    config_manager.upsert(profile)
    _run_in_thread(config_manager.remove, profile.name)
    assert config_manager.get(profile.name) is None
