import signal

from core.privilege import PrivilegeManager


def test_terminate_process_group_uses_privileged_kill(monkeypatch):
    password_calls = []

    def password_provider():
        password_calls.append(True)
        return ("secret", True)

    manager = PrivilegeManager(password_provider)
    manager._pkexec_path = None  # force sudo path
    manager._sudo_path = "/usr/bin/sudo"
    manager.ensure_password_cached()

    captured = {}

    class DummyResult:
        def __init__(self, returncode=0):
            self.returncode = returncode

    def fake_run(argv, input=None, text=None, capture_output=None, timeout=None, check=None):
        captured["argv"] = argv
        captured["input"] = input
        captured["text"] = text
        captured["capture_output"] = capture_output
        captured["timeout"] = timeout
        captured["check"] = check
        return DummyResult()

    monkeypatch.setattr("core.privilege.subprocess.run", fake_run)

    assert manager.terminate_process_group(1234, signal.SIGINT) is True
    assert captured["argv"] == [
        "/usr/bin/sudo",
        "-S",
        "/bin/sh",
        "-c",
        "kill -2 -1234",
    ]
    assert captured["input"] == "secret\n"
    assert captured["text"] is True
    assert captured["capture_output"] is True
    assert captured["timeout"] == 5.0
    assert captured["check"] is False
    assert password_calls  # password provider invoked to cache credentials


def test_cache_password_for_session_forces_allow():
    calls = []

    def password_provider():
        calls.append(True)
        return ("secret", False)

    manager = PrivilegeManager(password_provider)
    manager._pkexec_path = None
    manager._sudo_path = "/usr/bin/sudo"

    manager.cache_password_for_session()

    assert manager.password_cached() is True
    assert manager.cache_allowed() is True
    assert len(calls) == 1


def test_force_allow_upgrades_existing_cache():
    calls = []

    def password_provider():
        calls.append(True)
        return ("secret", False)

    manager = PrivilegeManager(password_provider)
    manager._pkexec_path = None
    manager._sudo_path = "/usr/bin/sudo"

    manager.ensure_password_cached()
    assert manager.cache_allowed() is False

    manager.ensure_password_cached(force_allow=True)

    assert manager.cache_allowed() is True
    assert len(calls) == 1
