"""High-level manager orchestrating VPN connections."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict, Iterable

import aiohttp

from .. import __version__
from ..utils.logging import get_logger
from ..utils.notifications import notify
from ..utils.platform import check_dependencies, detect_platform
from ..utils.processes import cleanup_stale_ppp
from .config_store import ConfigStore
from .connection import VPNConnection
from .profile import VPNProfile

logger = get_logger("manager")


class ConnectionManager:
    """Coordinates persistence, subprocess lifecycle, and UI updates."""

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.loop = loop or asyncio.get_event_loop()
        self.config_store = ConfigStore()
        self.profiles: Dict[str, VPNProfile] = self.config_store.load_profiles()
        self.connections: Dict[str, VPNConnection] = {}
        cleanup_stale_ppp()

    def list_profiles(self) -> Iterable[VPNProfile]:
        return self.profiles.values()

    def add_or_update_profile(self, profile: VPNProfile) -> None:
        self.profiles[profile.name] = profile
        self.config_store.save_profiles(self.profiles.values())
        if profile.name in self.connections:
            self.connections[profile.name].profile = profile
        logger.info("Saved profile %s", profile.name)

    def delete_profile(self, name: str) -> None:
        if name in self.connections:
            raise RuntimeError("Profile is currently connected")
        if name in self.profiles:
            del self.profiles[name]
            self.config_store.save_profiles(self.profiles.values())
            logger.info("Deleted profile %s", name)

    async def connect(self, name: str) -> None:
        profile = self.profiles.get(name)
        if not profile:
            raise KeyError(f"Profile {name} not found")
        self._log_route_overlap(profile)
        connection = self.connections.get(name)
        if not connection:
            connection = VPNConnection(profile, loop=self.loop)
            self.connections[name] = connection
        await connection.connect()

    async def disconnect(self, name: str) -> None:
        connection = self.connections.get(name)
        if connection:
            await connection.disconnect()
            self.connections.pop(name, None)

    def get_status(self, name: str):
        connection = self.connections.get(name)
        if connection:
            return connection.status
        profile = self.profiles.get(name)
        if profile:
            from .connection import ConnectionStatus

            return ConnectionStatus(auto_reconnect=profile.auto_reconnect)
        return None

    async def disconnect_all(self) -> None:
        await asyncio.gather(*(conn.disconnect() for conn in list(self.connections.values())), return_exceptions=True)
        self.connections.clear()

    def export_profiles(self, path: Path) -> None:
        self.config_store.export_profiles(path)

    def import_profiles(self, path: Path) -> None:
        self.config_store.import_profiles(path)
        self.profiles = self.config_store.load_profiles()

    def _log_route_overlap(self, profile: VPNProfile) -> None:
        if not profile.routing_rules:
            return
        for other in self.connections.values():
            if other.profile.name == profile.name:
                continue
            overlap = set(profile.routing_rules) & set(other.profile.routing_rules)
            if overlap:
                logger.warning(
                    "Overlapping routes detected between %s and %s: %s",
                    profile.name,
                    other.profile.name,
                    ", ".join(overlap),
                )

    async def check_for_updates(self) -> dict[str, str] | None:
        url = "https://api.github.com/repos/openfortivpn/openfortivpn/releases/latest"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
            except Exception as exc:
                logger.warning("Update check failed: %s", exc)
                return None
        latest_version = data.get("tag_name")
        if latest_version and latest_version != __version__:
            notify("New version available", f"Version {latest_version} is available")
            return {"version": latest_version, "url": data.get("html_url", "")}
        return None

    def dependency_report(self) -> dict[str, object]:
        platform = detect_platform()
        deps = check_dependencies()
        missing = {name: cmd for name, cmd in platform.dependency_commands.items() if not deps.get(name)}
        return {
            "platform": platform,
            "dependencies": deps,
            "missing": missing,
        }

