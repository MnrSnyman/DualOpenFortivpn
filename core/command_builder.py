"""Utilities for constructing openfortivpn command line arguments."""

from __future__ import annotations

from typing import List

from .vpn_profile import VPNProfile


def build_openfortivpn_command(profile: VPNProfile) -> List[str]:
    """Return the openfortivpn invocation for the given profile."""

    command = ["openfortivpn", f"{profile.host}:{profile.port}"]
    if profile.auth_type.lower() == "saml":
        if profile.saml_port:
            command.append(f"--saml-login={profile.saml_port}")
        else:
            command.append("--saml-login")
    else:
        if profile.username:
            command.append(f"--username={profile.username}")
    return command
