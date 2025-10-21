"""Native desktop notifications."""

from __future__ import annotations

import notify2

_notify_initialized = False


def _ensure_init() -> None:
    global _notify_initialized
    if not _notify_initialized:
        try:
            notify2.init("OpenFortiVPN Manager")
            _notify_initialized = True
        except Exception:
            _notify_initialized = False


def notify(title: str, message: str, urgency: str = "normal") -> None:
    _ensure_init()
    if _notify_initialized:
        n = notify2.Notification(title, message)
        if urgency == "critical":
            n.set_urgency(notify2.URGENCY_CRITICAL)
        elif urgency == "low":
            n.set_urgency(notify2.URGENCY_LOW)
        else:
            n.set_urgency(notify2.URGENCY_NORMAL)
        n.show()
    else:
        print(f"{title}: {message}")

