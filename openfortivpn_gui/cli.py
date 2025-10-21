"""Command line interface for OpenFortiVPN Manager."""

from __future__ import annotations

import asyncio
from typing import List

import typer
from rich.console import Console
from rich.table import Table

from .core.manager import ConnectionManager
from .core.profile import VPNProfile

console = Console()
app = typer.Typer(add_completion=False, help="Manage OpenFortiVPN profiles from the terminal")


@app.command()
def list() -> None:
    """List configured VPN profiles."""

    async def _run() -> None:
        manager = ConnectionManager()
        table = Table(title="VPN Profiles")
        table.add_column("Name")
        table.add_column("Host")
        table.add_column("Auth")
        table.add_column("Auto Reconnect")
        for profile in manager.list_profiles():
            table.add_row(
                profile.name,
                f"{profile.host}:{profile.port}",
                "SAML" if profile.enable_saml else "Password",
                "Yes" if profile.auto_reconnect else "No",
            )
        console.print(table)

    asyncio.run(_run())


@app.command()
def status(name: str) -> None:
    """Display runtime status for a profile."""

    async def _run() -> None:
        manager = ConnectionManager()
        status = manager.get_status(name)
        if not status:
            console.print(f"[red]Profile {name} not found[/red]")
            raise typer.Exit(code=1)
        table = Table(title=f"Status for {name}")
        table.add_column("State")
        table.add_column("IP")
        table.add_column("Interface")
        table.add_column("RX bytes")
        table.add_column("TX bytes")
        table.add_row(
            status.state.value,
            status.ip_address or "-",
            status.interface or "-",
            f"{status.bandwidth_in:.0f}",
            f"{status.bandwidth_out:.0f}",
        )
        console.print(table)

    asyncio.run(_run())


@app.command()
def connect(name: str) -> None:
    """Connect a profile and stream logs to the console."""

    async def _run() -> None:
        manager = ConnectionManager()
        await manager.connect(name)
        console.print(f"[green]Connecting to {name}. Press Ctrl+C to disconnect[/green]")
        try:
            while True:
                status = manager.get_status(name)
                if status:
                    console.print(
                        f"Status: {status.state.value} | IP: {status.ip_address or '-'} | Interface: {status.interface or '-'}",
                        justify="left",
                    )
                await asyncio.sleep(2)
        except KeyboardInterrupt:
            console.print("Disconnecting...")
            await manager.disconnect(name)

    asyncio.run(_run())


@app.command()
def disconnect(name: str) -> None:
    """Disconnect a running VPN connection."""

    async def _run() -> None:
        manager = ConnectionManager()
        await manager.disconnect(name)
        console.print(f"Disconnected {name}")

    asyncio.run(_run())


def run_cli(argv: List[str] | None = None) -> int:
    try:
        app(args=argv, prog_name="openfortivpn-gui", standalone_mode=False)
        return 0
    except typer.Exit as exc:
        return exc.exit_code

