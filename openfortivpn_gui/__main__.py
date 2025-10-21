"""Module entry point for running the OpenFortiVPN Manager package."""

from __future__ import annotations

import argparse
import asyncio
import sys

from . import __version__
from .cli import run_cli
from .ui.app import run_gui


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenFortiVPN Manager")
    parser.add_argument("--cli", action="store_true", help="Run in command-line interface mode")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    args, extra = parser.parse_known_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.cli:
        return asyncio.run(run_cli(extra))

    run_gui(extra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
