"""Secret management utilities for encrypted credential storage."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Final

from cryptography.fernet import Fernet

_KEY_FILE: Final[str] = "key.bin"


class SecretManager:
    """Encrypts and decrypts sensitive strings using Fernet symmetric encryption."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = Path(config_dir)
        self.key_path = self.config_dir / _KEY_FILE
        self._fernet = Fernet(self._load_or_create_key())

    def encrypt(self, secret: str) -> str:
        token = self._fernet.encrypt(secret.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes()
        key = Fernet.generate_key()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.config_dir, 0o700)
        self.key_path.write_bytes(key)
        os.chmod(self.key_path, 0o600)
        return key

