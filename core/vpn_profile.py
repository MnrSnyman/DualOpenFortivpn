"""Model objects describing VPN profile configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VPNProfile:
    name: str
    host: str
    port: int
    auth_type: str
    saml_port: Optional[int] = None
    browser: str = "system"
    browser_profile: Optional[str] = None
    username: Optional[str] = None
    auto_reconnect: bool = False
    routes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "auth_type": self.auth_type,
            "saml_port": self.saml_port,
            "browser": self.browser,
            "browser_profile": self.browser_profile,
            "username": self.username,
            "auto_reconnect": self.auto_reconnect,
            "routes": self.routes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VPNProfile":
        return cls(
            name=data.get("name", "Unnamed"),
            host=data.get("host", ""),
            port=int(data.get("port", 443)),
            auth_type=data.get("auth_type", "password"),
            saml_port=data.get("saml_port"),
            browser=data.get("browser", "system"),
            browser_profile=data.get("browser_profile"),
            username=data.get("username"),
            auto_reconnect=bool(data.get("auto_reconnect", False)),
            routes=list(data.get("routes", [])),
        )
