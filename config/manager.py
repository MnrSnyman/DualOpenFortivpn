"""Persistence layer for VPN profiles stored in YAML."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, List

import yaml

from core.app_paths import CONFIG_FILE, ensure_directories
from core.vpn_profile import VPNProfile


class ConfigManager:
    """Load and save VPN profiles from the configuration file."""

    def __init__(self) -> None:
        ensure_directories()
        self._lock = threading.Lock()
        self._profiles: Dict[str, VPNProfile] = {}
        self._load()

    def _load(self) -> None:
        if not Path(CONFIG_FILE).exists():
            self._profiles = {}
            return
        with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        profiles = {}
        for entry in data.get("profiles", []):
            profile = VPNProfile.from_dict(entry)
            profiles[profile.name] = profile
        self._profiles = profiles

    def save(self) -> None:
        with self._lock:
            data = {
                "profiles": [profile.to_dict() for profile in self._profiles.values()],
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
                yaml.safe_dump(data, handle, sort_keys=False)

    def profiles(self) -> List[VPNProfile]:
        with self._lock:
            return list(self._profiles.values())

    def get(self, name: str) -> VPNProfile | None:
        with self._lock:
            return self._profiles.get(name)

    def upsert(self, profile: VPNProfile) -> None:
        with self._lock:
            self._profiles[profile.name] = profile
            self.save()

    def remove(self, name: str) -> None:
        with self._lock:
            if name in self._profiles:
                del self._profiles[name]
                self.save()

    def reload(self) -> None:
        with self._lock:
            self._load()
