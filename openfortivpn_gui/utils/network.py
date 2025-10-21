"""Networking helper functions for route and DNS management."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
from pathlib import Path
from typing import Iterable, List

from .logging import get_logger

logger = get_logger("network")


async def _run_command(*cmd: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode(), stderr.decode()


def _normalize_route(rule: str) -> str:
    try:
        ipaddress.ip_network(rule, strict=False)
        return rule
    except ValueError:
        # treat as hostname
        return rule


async def add_routes(interface: str, routes: Iterable[str]) -> None:
    for route in routes:
        normalized = _normalize_route(route)
        logger.info("Adding route %s via %s", normalized, interface)
        if ":" in normalized or any(ch.isalpha() for ch in normalized):
            # host route
            cmd = ("sudo", "ip", "route", "add", normalized, "dev", interface)
        else:
            cmd = ("sudo", "ip", "route", "add", normalized, "dev", interface)
        code, out, err = await _run_command(*cmd)
        if code != 0:
            logger.error("Failed to add route %s: %s", normalized, err.strip())


async def remove_routes(interface: str, routes: Iterable[str]) -> None:
    for route in routes:
        normalized = _normalize_route(route)
        logger.info("Removing route %s via %s", normalized, interface)
        cmd = ("sudo", "ip", "route", "del", normalized, "dev", interface)
        code, out, err = await _run_command(*cmd)
        if code != 0:
            logger.warning("Failed to remove route %s: %s", normalized, err.strip())


async def apply_dns(servers: Iterable[str], interface: str) -> None:
    resolvconf_path = Path("/etc/resolv.conf")
    if not servers:
        return
    content_lines = ["# Managed by OpenFortiVPN Manager", ""]
    for server in servers:
        content_lines.append(f"nameserver {server}")
    content_lines.append("")
    tmp_path = Path(f"/tmp/resolv.conf.{interface}")
    tmp_path.write_text("\n".join(content_lines), encoding="utf-8")
    logger.info("Applying DNS servers %s via resolvconf", ", ".join(servers))
    await _run_command("sudo", "resolvconf", "-a", interface, str(tmp_path))
    try:
        tmp_path.unlink()
    except FileNotFoundError:
        pass


async def remove_dns(interface: str) -> None:
    await _run_command("sudo", "resolvconf", "-d", interface)

