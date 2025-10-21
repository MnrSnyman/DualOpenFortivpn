"""Asynchronous SAML HTTP callback listeners."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from aiohttp import web

from ..utils.logging import get_logger

logger = get_logger("saml")


@dataclass
class SAMLResult:
    success: bool
    message: str
    params: dict[str, str]


class SAMLListener:
    """Runs a lightweight HTTP server waiting for FortiGate SAML callbacks."""

    def __init__(self, port: int, fallback_port: int = 8020) -> None:
        self.port = port
        self.fallback_port = fallback_port
        self._queue: asyncio.Queue[SAMLResult] = asyncio.Queue()
        self._runner: web.AppRunner | None = None
        self._fallback_runner: web.AppRunner | None = None

    async def start(self) -> None:
        await self._start_app(self.port)
        if self.port != self.fallback_port:
            # Pre-emptively start fallback listener that informs users about redirect issues.
            await self._start_app(self.fallback_port, fallback=True)

    async def _start_app(self, port: int, fallback: bool = False) -> None:
        app = web.Application()
        app.router.add_get("/", self._handle_request)
        app.router.add_post("/", self._handle_request)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="127.0.0.1", port=port)
        try:
            await site.start()
            logger.info("SAML listener started on port %s (fallback=%s)", port, fallback)
        except OSError as exc:
            logger.error("Failed to start SAML listener on %s: %s", port, exc)
            if fallback:
                await runner.cleanup()
                return
            raise
        if fallback:
            self._fallback_runner = runner
        else:
            self._runner = runner

    async def stop(self) -> None:
        for runner in (self._runner, self._fallback_runner):
            if runner:
                await runner.cleanup()
        self._runner = None
        self._fallback_runner = None

    async def wait_for_result(self, timeout: float | None = 300) -> SAMLResult | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def _handle_request(self, request: web.Request) -> web.Response:
        params = dict(request.rel_url.query)
        params.update(await request.post())
        message = (
            "Authentication received. You may close this browser window."
            if params
            else "Received callback without parameters."
        )
        port = request.url.port
        if port == self.fallback_port and port != self.port:
            logger.warning(
                "Received SAML callback on fallback port %s; FortiGate likely ignored custom redirect.",
                port,
            )
            message += " FortiGate redirected to fallback port 8020."
        result = SAMLResult(success=bool(params), message=message, params=params)
        await self._queue.put(result)
        if params:
            body = (
                "<html><body><h2>OpenFortiVPN Manager</h2>"
                "<p>Authentication response captured. Return to the application.</p>"
                "</body></html>"
            )
        else:
            body = (
                "<html><body><h2>OpenFortiVPN Manager</h2>"
                "<p>No parameters received.</p></body></html>"
            )
        return web.Response(text=body, content_type="text/html")

    @property
    def active_ports(self) -> list[int]:
        ports = []
        if self._runner:
            ports.append(self.port)
        if self._fallback_runner:
            ports.append(self.fallback_port)
        return ports

