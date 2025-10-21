"""Generate README documentation for OpenFortiVPN Manager."""

from __future__ import annotations

from pathlib import Path

from .. import __version__

README_TEMPLATE = """# OpenFortiVPN Manager

OpenFortiVPN Manager is a cross-platform desktop and command-line companion for managing
multiple Fortinet VPN tunnels via [openfortivpn](https://github.com/adrienverge/openfortivpn).
It focuses on concurrent SAML and password-based sessions, per-profile routing, graceful
cleanup, and an elegant UI inspired by Uptime Kuma.

## Features

- Intuitive Qt-based dashboard with live status indicators and tray integration.
- Create, edit, duplicate, import, and export VPN profiles stored under
  `~/.config/openfortivpn-gui/` with secure credential encryption.
- Launch multiple simultaneous VPN sessions, each running in an isolated subprocess with
  dedicated logging under `/tmp/openfortivpn-gui/`.
- Automatic detection of SAML redirect issues (including 8020 fallback guidance) and
  browser launch to initiate authentication.
- Per-profile routing and DNS overrides that are cleaned up automatically on disconnect.
- Auto-reconnect timers with visible countdowns and configurable intervals.
- Native desktop notifications for connect/disconnect, reconnect retries, and errors.
- CLI companion for headless environments with `list`, `connect`, `disconnect`, and
  `status` commands.
- Dependency validation with distro-aware installation hints and GitHub release checks.

## Installation

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install python3 python3-pip openfortivpn resolvconf libnotify-bin
pip install -r requirements.txt
```

### Fedora / RHEL

```bash
sudo dnf install python3 python3-pip openfortivpn NetworkManager-openfortivpn
pip install -r requirements.txt
```

### Arch / Manjaro

```bash
sudo pacman -S python python-pip openfortivpn networkmanager-fortisslvpn
pip install -r requirements.txt
```

After installing dependencies, run the application with:

```bash
python -m openfortivpn_gui
```

To invoke the CLI companion, use:

```bash
python -m openfortivpn_gui --cli list
```

## Configuration

Profiles are stored at `~/.config/openfortivpn-gui/config.json` and are encrypted using a
Fernet key stored alongside the configuration (permissions are restricted to the owner).
You can import/export profiles via the UI or the config file directly using the CLI.

Each profile captures:

- Basic connection details (name, host, port)
- Authentication mode (SAML or username/password)
- Optional auto reconnect interval and persistent `--persistent` flag
- Optional routing rules and custom DNS servers

Logs are written to `/tmp/openfortivpn-gui/<profile>.log` and rotated when they exceed
10 MB. Use the "View Logs" button in the UI to inspect them.

## SAML Authentication & Port 8020 Fallback

When SAML is enabled on a profile, the manager starts a dedicated HTTP listener on the
configured port (default 8021) and opens the FortiGate SAML initiation URL in your browser.
Some FortiGate appliances ignore the custom listener port and always redirect to
`https://127.0.0.1:8020`. When the application detects traffic destined for the default
8020 port it will display a critical warning and automatically bring up a fallback
listener on 8020 (if available). If your device repeatedly forces the 8020 redirect,
update the URL in the browser to `https://127.0.0.1:<your_port>` before authenticating
or keep the fallback listener enabled in Settings.

## CLI Usage

```bash
python -m openfortivpn_gui --cli list
python -m openfortivpn_gui --cli connect <profile>
python -m openfortivpn_gui --cli status <profile>
python -m openfortivpn_gui --cli disconnect <profile>
```

The CLI streams live status updates and respects the same configuration files as the UI.

## Troubleshooting

- **Missing openfortivpn**: The dependency report in Settings displays the distro-specific
  command to install the package.
- **DNS not resolving**: Ensure `resolvconf` or `systemd-resolved` is installed. The manager
  applies DNS servers using `resolvconf` per interface.
- **SAML stuck on 8020**: Either enable the fallback listener or manually adjust the browser
  URL to match the configured listener port. The README section above details the steps.
- **Stale PPP interfaces**: The manager cleans up orphaned `pppd` processes during startup.

## Building Packages

- **Debian/Ubuntu (.deb)**: Use `fpm` or `dpkg-buildpackage` with an app bundle containing
  this project and a desktop file invoking `python -m openfortivpn_gui`.
- **Fedora (.rpm)**: Package with `rpmbuild` using similar layout, ensuring dependencies
  `openfortivpn`, `python3`, and `PySide6` are listed.
- **AppImage**: Bundle the Python runtime with the project via tools like `appimagetool`
  or `appimage-builder`.

## License

This project is released under the MIT License. See [LICENSE](LICENSE) for details.

"""


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    readme_path = root / "README.md"
    readme_path.write_text(README_TEMPLATE.format(version=__version__), encoding="utf-8")


if __name__ == "__main__":
    main()

