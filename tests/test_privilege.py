import io
import signal

from core.privilege import PrivilegeManager


def test_send_signal_uses_privileged_kill(monkeypatch):
    password_calls = []

    def password_provider():
        password_calls.append(True)
        return ("secret", True)

    manager = PrivilegeManager(password_provider)
    manager._pkexec_path = None  # force sudo path
    manager._sudo_path = "/usr/bin/sudo"
    manager.ensure_password_cached()

    monkeypatch.setattr(
        "core.privilege.shutil.which", lambda _: "/bin/kill",
    )

    popen_calls = {}

    class DummyProcess:
        def __init__(self):
            self.stdin = io.StringIO()
            self.returncode = 0

        def communicate(self, timeout=None):
            assert timeout == 5
            return "", ""

        def kill(self):
            popen_calls["killed"] = True

    def fake_popen(args, stdin=None, stdout=None, stderr=None, text=None):
        popen_calls["args"] = args
        popen_calls["stdin"] = stdin
        popen_calls["stdout"] = stdout
        popen_calls["stderr"] = stderr
        popen_calls["text"] = text
        return DummyProcess()

    monkeypatch.setattr("core.privilege.subprocess.Popen", fake_popen)

    assert manager.send_signal(1234, signal.SIGINT) is True
    assert popen_calls["args"] == [
        "/usr/bin/sudo",
        "-S",
        "/bin/kill",
        "-2",
        "1234",
    ]
    assert password_calls  # password provider invoked to cache credentials
