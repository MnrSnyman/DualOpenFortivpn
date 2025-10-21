# OpenFortiVPN Manager

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

Prerequisites
Python 3.9 or newer with pip available (verify with python3 -V and pip3 -V).
The openfortivpn binary installed on your PATH (verify with openfortivpn --version).
Sudo access so the manager can configure tunnels, routing, and DNS when you connect.

Quick Install
Choose an installation directory and fetch the source:
APPDIR="$HOME/openfortivpn-manager"
git clone https://github.com/openfortivpn/openfortivpn-manager.git "$APPDIR"
cd "$APPDIR"
Keep APPDIR defined for later commands or substitute your chosen directory path if you open a new shell.

Install system packages required for Qt, notifications, and the VPN client:
Ubuntu / Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv openfortivpn resolvconf libnotify-bin

Fedora / RHEL
sudo dnf install -y python3 python3-pip python3-virtualenv openfortivpn NetworkManager-openfortivpn libnotify

Arch / Manjaro
sudo pacman -Syu --needed python python-pip python-virtualenv openfortivpn networkmanager-fortisslvpn libnotify

Create an isolated virtual environment (recommended):
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --upgrade -r requirements.txt

If you prefer a per-user install without a virtual environment, run:
python3 -m pip install --user --upgrade pip
python3 -m pip install --user --upgrade -r requirements.txt

First Run
Activate the virtual environment for each new shell with source "$APPDIR/.venv/bin/activate" (replace APPDIR with the directory you chose if the variable is not set).
Start the graphical interface:
python -m openfortivpn_gui
Start the CLI companion:
python -m openfortivpn_gui --cli list
The first time you connect to a VPN, sudo will prompt for your password so openfortivpn can create the tunnel.

Create Desktop Launcher (Optional)
Create a helper script that launches the manager from the installation directory:
mkdir -p "$HOME/.local/bin"
cat <<'EOF' > "$HOME/.local/bin/openfortivpn-gui"
#!/usr/bin/env bash
APPDIR="${APPDIR:-$HOME/openfortivpn-manager}"
if [ -d "$APPDIR/.venv" ]; then
  source "$APPDIR/.venv/bin/activate"
fi
cd "$APPDIR"
python -m openfortivpn_gui "$@"
EOF
chmod +x "$HOME/.local/bin/openfortivpn-gui"

Add a desktop entry so the GUI appears in your application menu:
mkdir -p "$HOME/.local/share/applications"
cat <<EOF > "$HOME/.local/share/applications/openfortivpn-gui.desktop"
[Desktop Entry]
Type=Application
Name=OpenFortiVPN Manager
Exec=$HOME/.local/bin/openfortivpn-gui
Icon=network-vpn
Categories=Network;Security;
Terminal=false
EOF
chmod +x "$HOME/.local/share/applications/openfortivpn-gui.desktop"
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true

Verify Installation
With the virtual environment active, run python -m openfortivpn_gui --cli list to ensure the CLI loads without errors.
Launch the GUI and confirm that no missing-dependency warning appears; if openfortivpn is not detected, the window will display the package manager command you need.
Double-check that command -v openfortivpn prints the path to the VPN client.

Troubleshooting Tip
If any step fails, review the Troubleshooting section below and make sure every dependency above is installed before launching the manager.

Advanced one-liner
bash -c '
set -euo pipefail
APPDIR="${APPDIR:-$HOME/openfortivpn-manager}"
if [ ! -d "$APPDIR" ]; then
  git clone https://github.com/openfortivpn/openfortivpn-manager.git "$APPDIR"
fi
cd "$APPDIR"
. /etc/os-release
case "$ID" in
  ubuntu|debian)
    sudo apt update
    sudo apt install -y python3 python3-pip python3-venv openfortivpn resolvconf libnotify-bin
    ;;
  fedora|rhel|centos)
    sudo dnf install -y python3 python3-pip python3-virtualenv openfortivpn NetworkManager-openfortivpn libnotify
    ;;
  arch|manjaro)
    sudo pacman -Syu --needed python python-pip python-virtualenv openfortivpn networkmanager-fortisslvpn libnotify
    ;;
  *)
    echo "Unsupported distribution: $ID" >&2
    exit 1
    ;;
esac
python3 -m pip install --user --upgrade pip
python3 -m pip install --user --upgrade -r requirements.txt
'

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

