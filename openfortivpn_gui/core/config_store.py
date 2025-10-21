"""Configuration storage and persistence utilities."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterable

import yaml

from .profile import VPNProfile, ProfileMap
from .secrets import SecretManager

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "openfortivpn-gui"
CONFIG_PATH = CONFIG_DIR / "config.json"
BACKUP_PATH = CONFIG_DIR / "config.backup.json"


class ConfigStore:
    """Handles persistence of application configuration."""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self.secret_manager = SecretManager(CONFIG_DIR)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def load_profiles(self) -> ProfileMap:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        profiles = {}
        for raw in data.get("profiles", []):
            profile = VPNProfile.from_dict(raw)
            if profile.password:
                profile.password = self.secret_manager.decrypt(profile.password)
            profiles[profile.name] = profile
        return profiles

    def save_profiles(self, profiles: Iterable[VPNProfile]) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        data = {
            "profiles": [self._serialize_profile(profile) for profile in profiles],
        }
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        tmp_path.replace(self.path)
        BACKUP_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _serialize_profile(self, profile: VPNProfile) -> Dict[str, object]:
        payload = profile.to_dict()
        if profile.password:
            payload["password"] = self.secret_manager.encrypt(profile.password)
        return payload

    def export_profiles(self, export_path: Path) -> None:
        data = {
            "profiles": [self._serialize_profile(profile) for profile in self.load_profiles().values()],
        }
        with export_path.open("w", encoding="utf-8") as fh:
            if export_path.suffix in {".yaml", ".yml"}:
                yaml.safe_dump(data, fh)
            else:
                json.dump(data, fh, indent=2)

    def import_profiles(self, import_path: Path) -> None:
        with import_path.open("r", encoding="utf-8") as fh:
            if import_path.suffix in {".yaml", ".yml"}:
                data = yaml.safe_load(fh) or {}
            else:
                data = json.load(fh)
        profiles = self.load_profiles()
        for raw in data.get("profiles", []):
            profile = VPNProfile.from_dict(raw)
            if profile.password:
                # We expect imported passwords to already be encrypted with this instance's key.
                # If they are not, store as plaintext which will be encrypted on next save.
                try:
                    profile.password = self.secret_manager.decrypt(profile.password)
                except Exception:
                    pass
            profiles[profile.name] = profile
        self.save_profiles(profiles.values())

