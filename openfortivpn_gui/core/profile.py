"""Data structures describing VPN profiles."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class VPNProfile:
    """Represents configuration for a single OpenFortiVPN connection."""

    name: str
    host: str
    port: int = 443
    enable_saml: bool = False
    saml_port: int = 8021
    browser: str | None = None
    browser_profile: str | None = None
    username: str | None = None
    password: str | None = None  # encrypted blob managed by :mod:`openfortivpn_gui.core.secrets`
    auto_reconnect: bool = False
    auto_reconnect_interval: int = 15
    routing_rules: list[str] = field(default_factory=list)
    custom_dns: list[str] = field(default_factory=list)
    persistent: bool = True

    def to_dict(self, include_password: bool = True) -> Dict[str, Any]:
        data = asdict(self)
        if not include_password:
            data.pop("password", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VPNProfile":
        return cls(
            name=data.get("name", "Unnamed"),
            host=data.get("host", ""),
            port=int(data.get("port", 443)),
            enable_saml=bool(data.get("enable_saml", False)),
            saml_port=int(data.get("saml_port", 8021)),
            browser=data.get("browser"),
            browser_profile=data.get("browser_profile"),
            username=data.get("username"),
            password=data.get("password"),
            auto_reconnect=bool(data.get("auto_reconnect", False)),
            auto_reconnect_interval=int(data.get("auto_reconnect_interval", 15)),
            routing_rules=list(data.get("routing_rules", [])),
            custom_dns=list(data.get("custom_dns", [])),
            persistent=bool(data.get("persistent", True)),
        )

    def display_name(self) -> str:
        return f"{self.name} ({self.host}:{self.port})"


ProfileMap = Dict[str, VPNProfile]

