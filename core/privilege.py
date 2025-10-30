"""Privilege escalation helper that decides between pkexec and sudo."""

from __future__ import annotations

import shutil
import signal
import subprocess
from typing import Callable, List, Optional, Tuple

PasswordResponse = Tuple[str, bool]
PasswordProvider = Callable[[], Optional[PasswordResponse]]


class PrivilegeManager:
    """Encapsulates the logic required to run commands with elevated rights."""

    def __init__(self, password_provider: PasswordProvider) -> None:
        self._password_provider = password_provider
        self._cached_password: Optional[str] = None
        self._cache_allowed = False
        self._pkexec_path = shutil.which("pkexec")
        self._sudo_path = shutil.which("sudo")

    def clear_cached_password(self) -> None:
        self._cached_password = None
        self._cache_allowed = False

    def has_pkexec(self) -> bool:
        return self._pkexec_path is not None

    def ensure_password_cached(self, force: bool = False) -> None:
        """Populate the cached sudo password when sudo is preferred."""

        if not self._sudo_path:
            return
        if self._cached_password is not None:
            return
        if self._pkexec_path and not force:
            return
        if not self._password_provider:
            raise RuntimeError("A sudo password provider is required.")
        response = self._password_provider()
        if response is None:
            raise RuntimeError("Sudo password entry was cancelled by the user.")
        password, allow_cache = response
        self._cached_password = password
        self._cache_allowed = allow_cache

    def _build_sudo_command(self, base_command: List[str]) -> Tuple[List[str], Optional[str]]:
        self.ensure_password_cached(force=True)
        if not self._cached_password:
            raise RuntimeError("Sudo password unavailable.")
        return [self._sudo_path, "-S", *base_command], self._cached_password

    def build_command(
        self, base_command: List[str], prefer_sudo: bool = False
    ) -> Tuple[List[str], Optional[str]]:
        """Return a command list and optional sudo password for execution."""
        if prefer_sudo and self._sudo_path:
            return self._build_sudo_command(base_command)

        if self._pkexec_path and not prefer_sudo:
            return [self._pkexec_path, *base_command], None

        if self._sudo_path:
            return self._build_sudo_command(base_command)

        raise RuntimeError("Neither pkexec nor sudo is available on this system.")

    def run_privileged(
        self,
        command: List[str],
        input_text: Optional[str] = None,
        *,
        prefer_sudo: bool = False,
    ) -> Tuple[int, str, str]:
        """Execute a command with the configured privilege escalation helper."""
        argv, password = self.build_command(command, prefer_sudo=prefer_sudo)
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if (password or input_text) else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if password and process.stdin:
            process.stdin.write(password + "\n")
        if input_text and process.stdin:
            process.stdin.write(input_text)
        if (password or input_text) and process.stdin:
            process.stdin.flush()
        stdout, stderr = process.communicate()
        if password and not self._cache_allowed:
            self._cached_password = None
        return process.returncode, stdout, stderr

    def terminate_process_group(self, pgid: int, sig: signal.Signals = signal.SIGTERM) -> bool:
        """Send a signal to a process group using elevated privileges."""
        command = ["/bin/kill", f"-{sig.value}", "--", f"-{pgid}"]
        try:
            code, stdout, stderr = self.run_privileged(command)
        except RuntimeError as exc:
            from .logging_manager import get_logging_manager

            logger = get_logging_manager().logger
            logger.warning(
                "Unable to invoke privilege helper to signal group %s: %s",
                pgid,
                exc,
            )
            return False
        if code != 0:
            message = stderr.strip() or stdout.strip()
            # Returning False signals the caller to escalate further.
            if message:
                from .logging_manager import get_logging_manager

                logger = get_logging_manager().logger
                logger.warning(
                    "Failed to deliver %s to process group %s via privilege helper: %s",
                    sig.name,
                    pgid,
                    message,
                )
            return False
        return True

    def cache_allowed(self) -> bool:
        return self._cache_allowed

    def password_cached(self) -> bool:
        return self._cached_password is not None
