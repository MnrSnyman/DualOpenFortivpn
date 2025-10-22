import importlib
import signal

import pytest

qt_available = False
for module_name in ("PyQt6", "PyQt5"):
    try:
        importlib.import_module(module_name)
        qt_available = True
        break
    except ImportError:
        continue

if not qt_available:
    pytest.skip("Qt bindings not installed", allow_module_level=True)

from core.vpn_profile import VPNProfile
from core.vpn_session import VPNSession


class DummyRouteManager:
    def __init__(self):
        self.cleaned = []

    def cleanup(self, name):
        self.cleaned.append(name)


class DummyPrivilegeManager:
    def __init__(self):
        self.calls = []
        self.process = None

    def send_signal(self, pid, sig):
        self.calls.append((pid, sig))
        if self.process is not None:
            self.process._running = False
        return True


class DummyProcess:
    def __init__(self):
        self.pid = 4321
        self._running = True
        self.stdin = DummyStream()

    def poll(self):
        return None if self._running else 0

    def wait(self, timeout=None):
        if not self._running:
            return 0
        raise RuntimeError("Process still running")

    def send_signal(self, sig):
        raise PermissionError


class DummyStream:
    def close(self):
        pass


def test_stop_uses_privileged_signal():
    profile = VPNProfile(
        name="test",
        host="vpn.example.com",
        port=443,
        auth_type="saml",
    )
    privilege = DummyPrivilegeManager()
    routes = DummyRouteManager()
    session = VPNSession(profile, privilege, routes, {}, None)
    process = DummyProcess()
    privilege.process = process
    session._process = process

    session.stop()

    assert privilege.calls == [(4321, signal.SIGINT)]
    assert routes.cleaned == ["test"]
    assert process._running is False
