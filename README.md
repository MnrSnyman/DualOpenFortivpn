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

Multi-VPN Manager ships as a Python 3.9+ application with a PyQt6 interface and targets modern Linux distributions that already provide the `openfortivpn` client. The steps below walk through installing dependencies, preparing Python, and running the desktop or CLI tools on Debian/Ubuntu, Fedora/RHEL, and Arch/Manjaro systems.

### Prerequisites

- Python 3.9 or newer and matching `pip` (check with `python3 --version` and `python3 -m pip --version`).
- `openfortivpn` available on your `PATH` so tunnels can be established.
- Ability to run `pkexec`/`sudo` for privileged routing and DNS updates during VPN connections.

### System Packages

Install the distribution packages that provide the VPN client, PolicyKit integration, Qt runtime dependencies, and desktop notification support.

#### Debian / Ubuntu

- `openfortivpn` – Fortinet SSL VPN client used for each tunnel.
- `policykit-1` – enables `pkexec` privilege prompts.
- `libegl1`, `libgl1` – Qt6 rendering backends for accelerated graphics.
- `libnotify-bin` – desktop notifications from the UI.

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv openfortivpn policykit-1 libegl1 libgl1 libnotify-bin
```

#### Fedora / RHEL

- `openfortivpn` – Fortinet SSL VPN client.
- `polkit` – PolicyKit agent for privilege escalation.
- `mesa-libEGL`, `mesa-libGL` – Qt6 OpenGL/EGL support.
- `libnotify` – desktop notifications.

```bash
sudo dnf install -y python3 python3-pip python3-virtualenv openfortivpn polkit mesa-libEGL mesa-libGL libnotify
```

#### Arch / Manjaro

- `openfortivpn` – Fortinet SSL VPN client.
- `polkit` – provides `pkexec` dialogs.
- `libegl`, `libglvnd` – Qt6 rendering libraries.
- `libnotify` – desktop notifications.

```bash
sudo pacman -Syu --needed python python-pip python-virtualenv openfortivpn polkit libegl libglvnd libnotify
```

### Python Environment Setup

- **Using a virtual environment (recommended):**

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install --upgrade -r requirements.txt
  ```

- **Using per-user pip (without a virtual environment):**

  ```bash
  python3 -m pip install --user --upgrade pip
  python3 -m pip install --user --upgrade -r requirements.txt
  ```

### Running the Application

```bash
git clone https://github.com/openfortivpn/openfortivpn-manager.git
cd openfortivpn-manager
source .venv/bin/activate  # omit if using --user installs
python3 -m openfortivpn_gui             # launch the PyQt6 GUI
python3 -m openfortivpn_gui --cli list  # list profiles via the CLI companion
```

### First Launch Behavior

- The first startup creates `~/.config/multi_vpn_manager/config.yaml` to store profiles and preferences.
- A desktop entry is written to `~/.local/share/applications/multi-vpn-manager.desktop` for quick relaunches.
- When connecting to a VPN, `pkexec` prompts for administrative credentials so routes, DNS, and PPP interfaces can be managed.

### Creating a Desktop Launcher (Optional)

- Ensure the helper script exists (created automatically on first launch):

  ```bash
  mkdir -p ~/.local/bin
  cat <<'EOF' > ~/.local/bin/multi-vpn-manager
  #!/usr/bin/env bash
  APPDIR="${APPDIR:-$HOME/openfortivpn-manager}"
  if [ -d "$APPDIR/.venv" ]; then
    source "$APPDIR/.venv/bin/activate"
  fi
  cd "$APPDIR"
  exec python3 -m openfortivpn_gui "$@"
  EOF
  chmod +x ~/.local/bin/multi-vpn-manager
  ```

- Recreate the launcher if it is deleted (`~/.local/share/applications/multi-vpn-manager.desktop`):

  ```bash
  mkdir -p ~/.local/share/applications
  cat <<'EOF' > ~/.local/share/applications/multi-vpn-manager.desktop
  [Desktop Entry]
  Type=Application
  Name=Multi-VPN Manager
  Exec=$HOME/.local/bin/multi-vpn-manager
  Icon=network-vpn
  Categories=Network;Security;
  Terminal=false
  EOF
  chmod +x ~/.local/share/applications/multi-vpn-manager.desktop
  update-desktop-database ~/.local/share/applications >/dev/null 2>&1 || true
  ```

- Remove the launcher manually when no longer needed:

  ```bash
  rm -f ~/.local/share/applications/multi-vpn-manager.desktop
  ```

### Updating

Activate your environment (if applicable) and refresh both the source code and Python packages:

```bash
cd openfortivpn-manager
git pull --ff-only
python -m pip install --upgrade -r requirements.txt
```

### Troubleshooting

- **`openfortivpn` not found:** Reinstall the package for your distribution and confirm `command -v openfortivpn` returns a path.
- **Browser not detected:** Install a supported browser (Firefox, Chromium, or Chrome) and ensure it is on your `PATH`.
- **Missing PolicyKit or EGL libraries:** Re-run the system package commands above to install `policykit-1`/`polkit` and the appropriate `libegl`/`libgl` libraries.
- **PKI authentication dialogs:** Accept the `pkexec` prompt that appears when connecting; denying or closing it will abort tunnel setup.
- **Configuration or permission issues:** Remove `~/.config/multi_vpn_manager/config.yaml` (after backing up) and relaunch to regenerate defaults, ensuring your user owns the configuration directory.
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

