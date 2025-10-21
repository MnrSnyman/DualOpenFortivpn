"""Platform detection and dependency helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Dict, List

import distro


@dataclass
class PlatformInfo:
    id: str
    name: str
    version: str
    dependency_commands: Dict[str, str]


def detect_platform() -> PlatformInfo:
    distro_id = distro.id() or "linux"
    distro_name = distro.name(pretty=True) or "Linux"
    version = distro.version() or ""
    commands = {
        "openfortivpn": "sudo apt install openfortivpn",
        "resolvconf": "sudo apt install resolvconf",
        "ip": "sudo apt install iproute2",
        "systemctl": "sudo apt install systemd",
    }
    if distro_id in {"fedora", "centos", "rhel"}:
        commands = {
            "openfortivpn": "sudo dnf install openfortivpn",
            "resolvconf": "sudo dnf install openresolv",
            "ip": "sudo dnf install iproute",
            "systemctl": "sudo dnf install systemd",
        }
    elif distro_id in {"arch", "manjaro"}:
        commands = {
            "openfortivpn": "sudo pacman -S openfortivpn",
            "resolvconf": "sudo pacman -S openresolv",
            "ip": "sudo pacman -S iproute2",
            "systemctl": "sudo pacman -S systemd",
        }
    return PlatformInfo(id=distro_id, name=distro_name, version=version, dependency_commands=commands)


def check_dependencies() -> Dict[str, bool]:
    dependencies = ["openfortivpn", "sudo", "ip", "systemctl", "resolvconf"]
    return {dep: shutil.which(dep) is not None for dep in dependencies}

