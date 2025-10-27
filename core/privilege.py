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

    def ensure_password_cached(self, force_allow: bool = False) -> None:
        if self._pkexec_path or not self._sudo_path:
            return
        if self._cached_password:
            if force_allow and not self._cache_allowed:
                self._cache_allowed = True
            return
        if not self._password_provider:
            raise RuntimeError("A sudo password provider is required.")
        response = self._password_provider()
        if response is None:
            raise RuntimeError("Sudo password entry was cancelled by the user.")
        password, allow_cache = response
        self._cached_password = password
        self._cache_allowed = allow_cache or force_allow

    def cache_password_for_session(self) -> None:
        """Force caching of the sudo password for the current application run."""
        self.ensure_password_cached(force_allow=True)

    def build_command(self, base_command: List[str]) -> Tuple[List[str], Optional[str]]:
        """Return a command list and optional sudo password for execution."""
        if self._pkexec_path:
            return [self._pkexec_path, *base_command], None

        if not self._sudo_path:
            raise RuntimeError("Neither pkexec nor sudo is available on this system.")

        if self._cached_password and self._cache_allowed:
            return [self._sudo_path, "-S", *base_command], self._cached_password

        self.ensure_password_cached()
        if not self._cached_password:
            raise RuntimeError("Sudo password unavailable.")
        return [self._sudo_path, "-S", *base_command], self._cached_password

    def run_privileged(self, command: List[str], input_text: Optional[str] = None) -> Tuple[int, str, str]:
        """Execute a command with the configured privilege escalation helper."""
        argv, password = self.build_command(command)
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
        return process.returncode, stdout, stderr

    def terminate_process_group(self, pgid: int, sig: signal.Signals = signal.SIGTERM) -> bool:
        """Send a signal to a process group using elevated privileges."""
        try:
            argv, password = self.build_command([
                "/bin/sh",
                "-c",
                f"kill -{sig.value} -{pgid}",
            ])
        except RuntimeError as exc:
            from .logging_manager import get_logging_manager

            logger = get_logging_manager().logger
            logger.warning(
                "Unable to invoke privilege helper to signal group %s: %s",
                pgid,
                exc,
            )
            return False

        password_input = f"{password}\n" if password else None

        try:
            result = subprocess.run(
                argv,
                input=password_input,
                text=True,
                capture_output=True,
                timeout=5.0,
                check=False,
            )
        except Exception as exc:
            from .logging_manager import get_logging_manager

            logger = get_logging_manager().logger
            logger.warning(
                "Failed to deliver %s to process group %s via privilege helper: %s",
                sig.name,
                pgid,
                exc,
            )
            return False

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
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
