"""Process management helpers."""

from __future__ import annotations

import logging
from typing import Iterable

import psutil

from .logging import get_logger

logger = get_logger("processes")


def cleanup_stale_ppp() -> None:
    """Terminate stray pppd processes that were spawned by openfortivpn."""

    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.info.get("name") == "pppd" and any("openfortivpn" in (arg or "") for arg in proc.info.get("cmdline") or []):
                logger.warning("Found stale pppd process %s, terminating", proc.pid)
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def find_interface_for_process(pid: int) -> str | None:
    """Attempt to guess PPP interface name for the provided process."""

    for proc in psutil.process_iter(["pid", "name", "connections"]):
        if proc.pid == pid:
            for conn in proc.connections(kind="inet"):
                if conn.laddr and conn.laddr.ip.startswith("10."):
                    return f"ppp{conn.fd}"  # heuristic fallback
    return None

