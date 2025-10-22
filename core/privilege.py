"""Privilege escalation helper that decides between pkexec and sudo."""

from __future__ import annotations

import shutil
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

    def ensure_password_cached(self) -> None:
        if self._pkexec_path or not self._sudo_path:
            return
        if self._cached_password:
            return
        if not self._password_provider:
            raise RuntimeError("A sudo password provider is required.")
        response = self._password_provider()
        if response is None:
            raise RuntimeError("Sudo password entry was cancelled by the user.")
        password, allow_cache = response
        self._cached_password = password
        self._cache_allowed = allow_cache

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

    def cache_allowed(self) -> bool:
        return self._cache_allowed

    def password_cached(self) -> bool:
        return self._cached_password is not None
