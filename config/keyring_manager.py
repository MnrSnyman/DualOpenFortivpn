"""Secure password storage helper using python-keyring."""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError, NoKeyringError

from core.logging_manager import get_logging_manager

LOGGER = get_logging_manager().logger
SERVICE_NAME = "OpenFortiVPN-Manager"


class KeyringManager:
    """High-level wrapper providing error tolerant keyring operations."""

    def __init__(self) -> None:
        self._available = True
        try:
            keyring.get_keyring()
        except Exception as exc:
            LOGGER.warning("Keyring backend unavailable: %s", exc)
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def build_key(self, profile_name: str) -> str:
        return f"{SERVICE_NAME}:{profile_name}"

    def save_password(self, profile_name: str, username: str, password: str) -> bool:
        if not self._available:
            return False
        try:
            keyring.set_password(SERVICE_NAME, self.build_key(profile_name), f"{username}\n{password}")
            return True
        except (NoKeyringError, KeyringError) as exc:
            LOGGER.error("Failed to save password: %s", exc)
            return False

    def load_password(self, profile_name: str) -> tuple[str, str] | None:
        if not self._available:
            return None
        try:
            data = keyring.get_password(SERVICE_NAME, self.build_key(profile_name))
            if not data:
                return None
            username, password = data.split("\n", 1)
            return username, password
        except (NoKeyringError, KeyringError) as exc:
            LOGGER.error("Failed to read password: %s", exc)
            return None

    def delete_password(self, profile_name: str) -> bool:
        if not self._available:
            return False
        try:
            keyring.delete_password(SERVICE_NAME, self.build_key(profile_name))
            return True
        except (NoKeyringError, KeyringError) as exc:
            LOGGER.error("Failed to delete password: %s", exc)
            return False
