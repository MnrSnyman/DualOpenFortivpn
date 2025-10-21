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

OpenFortiVPN Manager targets modern Linux distributions with Python 3.9+ and a working `openfortivpn` binary. This guide walks through installing system prerequisites, setting up Python dependencies, launching the interface, and keeping everything current.

### Prerequisites

- Python 3.9 or newer with `pip` available (`python3 --version`, `python3 -m pip --version`).
- `openfortivpn` present on your `PATH` to establish tunnels.
- Ability to grant PolicyKit/`pkexec` privileges when routes, DNS, and PPP interfaces are configured.

### Install System Packages

Install the VPN client, PolicyKit components, Qt (PySide6) runtime libraries, and notification tooling provided by your distribution.

#### Debian / Ubuntu

- `openfortivpn` – Fortinet SSL VPN client executed for each tunnel.
- `policykit-1` – supplies `pkexec` dialogs for elevated actions.
- `libegl1`, `libgl1` – OpenGL/EGL libraries required by PySide6.
- `libnotify-bin` – enables desktop notifications.

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv openfortivpn policykit-1 libegl1 libgl1 libnotify-bin
```

#### Fedora / RHEL

- `openfortivpn` – Fortinet SSL VPN client.
- `polkit` – PolicyKit service providing `pkexec` authentication.
- `mesa-libEGL`, `mesa-libGL` – OpenGL/EGL support for PySide6.
- `libnotify` – desktop notification support.

```bash
sudo dnf install -y python3 python3-pip python3-virtualenv openfortivpn polkit mesa-libEGL mesa-libGL libnotify
```

#### Arch / Manjaro

- `openfortivpn` – Fortinet SSL VPN client.
- `polkit` – provides PolicyKit dialogs.
- `libegl`, `libglvnd` – OpenGL/EGL libraries for PySide6.
- `libnotify` – desktop notification support.

```bash
sudo pacman -Syu --needed python python-pip python-virtualenv openfortivpn polkit libegl libglvnd libnotify
```

### Install Python Dependencies

OpenFortiVPN Manager depends on:

- `PySide6` – modern Qt GUI bindings
- `aiohttp` – async HTTP client for update checks and SAML listeners
- `typer[all]` – CLI interface with rich completion support
- `rich` – styled CLI output
- `psutil` – process inspection and cleanup
- `PyYAML` – profile import/export
- `cryptography` – encrypted credential storage
- `notify2` – desktop notifications
- `distro` – Linux distribution detection
- `requests` – GitHub release checks and HTTP helpers

**Using a virtual environment (recommended):**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --upgrade PySide6 aiohttp 'typer[all]' rich psutil PyYAML cryptography notify2 distro requests
```

**Using per-user pip (without a virtual environment):**

```bash
python3 -m pip install --user --upgrade pip
python3 -m pip install --user --upgrade PySide6 aiohttp "typer[all]" rich psutil PyYAML cryptography notify2 distro requests
```

### Quick Install (Advanced Users)

Run this command to clone the repository anonymously, detect your distribution, install system prerequisites, and install Python dependencies using `pip --user`. The script standardises everything under `$HOME/OpenFortiVPN-Manager` and cleans up legacy folder names automatically:

```bash
bash -c '
set -euo pipefail

APPDIR="${APPDIR:-$HOME/OpenFortiVPN-Manager}"
LEGACY_DIRS=("$HOME/OpenFortiVPN_Manager" "$HOME/openfortivpn-manager" "$HOME/openfortivpn_manager")

for legacy in "${LEGACY_DIRS[@]}"; do
  if [ -d "$legacy" ] && [ "$legacy" != "$APPDIR" ]; then
    if [ ! -e "$APPDIR" ]; then
      echo "[WARN] Renaming legacy directory $legacy to $APPDIR"
      mv "$legacy" "$APPDIR"
    else
      echo "[WARN] Removing duplicate legacy directory $legacy"
      rm -rf "$legacy"
    fi
  fi
done

if [ -d "$APPDIR/.git" ]; then
  echo "[INFO] Repository already present at $APPDIR"
elif [ -d "$APPDIR" ]; then
  echo "[WARN] Existing non-git directory found at $APPDIR; removing before clone"
  rm -rf "$APPDIR"
fi

if [ ! -d "$APPDIR" ]; then
  echo "[INFO] Cloning OpenFortiVPN Manager into $APPDIR"
  if ! GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/true git clone --depth 1 https://github.com/MnrSnyman/OpenFortiVPN-Manager.git "$APPDIR"; then
    echo "[ERROR] Failed to clone repository anonymously." >&2
    exit 1
  fi
fi

cd "$APPDIR"
. /etc/os-release

case "$ID" in
  ubuntu|debian)
    echo "[INFO] Installing packages via apt"
    sudo apt update
    sudo apt install -y python3 python3-pip python3-venv openfortivpn policykit-1 libegl1 libgl1 libnotify-bin
    ;;
  fedora|rhel|centos)
    echo "[INFO] Installing packages via dnf"
    sudo dnf install -y python3 python3-pip python3-virtualenv openfortivpn polkit mesa-libEGL mesa-libGL libnotify
    ;;
  arch|manjaro)
    echo "[INFO] Installing packages via pacman"
    sudo pacman -Syu --needed python python-pip python-virtualenv openfortivpn polkit libegl libglvnd libnotify
    ;;
  *)
    echo "[ERROR] Unsupported distribution: $ID" >&2
    exit 1
    ;;
esac

python3 -m pip install --user --upgrade pip
python3 -m pip install --user --upgrade PySide6 aiohttp "typer[all]" rich psutil PyYAML cryptography notify2 distro requests

echo "[SUCCESS] Installation complete. Launch with: python3 -m openfortivpn_gui"
'
```

### Running the Application

```bash
git clone https://github.com/MnrSnyman/OpenFortiVPN-Manager.git "$HOME/OpenFortiVPN-Manager"
cd "$HOME/OpenFortiVPN-Manager"
# Activate the virtual environment if you created one:
source .venv/bin/activate 2>/dev/null || true
python3 -m openfortivpn_gui            # launch the PySide6 GUI
python3 -m openfortivpn_gui --cli list # list profiles via the CLI companion
```

### First Launch Behavior

- A configuration file is created at `~/.config/openfortivpn-gui/config.json` to store profiles and preferences.
- The optional desktop launcher is written to `~/.local/share/applications/openfortivpn-gui.desktop` for quick relaunches.
- When connecting to a VPN, `pkexec` prompts for administrative credentials so routes, DNS, and PPP interfaces can be managed.

### Troubleshooting

- **`openfortivpn` not found:** Reinstall the package for your distribution and confirm `command -v openfortivpn` returns a path.
- **Browser not detected:** Install a supported browser (Firefox, Chromium, Chrome, Brave, or Edge) and ensure it is on your `PATH`.
- **Missing PolicyKit or EGL libraries:** Re-run the system package commands above to install `policykit-1`/`polkit` and the appropriate `libegl`/`libgl` libraries.
- **PKI authentication dialogs:** Accept the `pkexec` prompt that appears when connecting; denying or closing it will abort tunnel setup.
- **Configuration or permission issues:** Remove `~/.config/openfortivpn-gui/config.json` (after backing up) and relaunch to regenerate defaults, ensuring your user owns the configuration directory.

### Cleanup / Uninstall

To remove OpenFortiVPN Manager completely, delete the application directory and its supporting assets:

```bash
rm -rf "$HOME/OpenFortiVPN-Manager"
rm -f "$HOME/.local/share/applications/openfortivpn-gui.desktop"
rm -rf "$HOME/.config/openfortivpn-gui"
```

If you previously experimented with legacy folder names such as `~/openfortivpn-manager` or `~/OpenFortiVPN_Manager`, remove them as well to avoid confusion.

### Updating

Refresh the source code and upgrade dependencies (activate your virtual environment first if you use one):

```bash
cd "$HOME/OpenFortiVPN-Manager"
git pull --ff-only
python -m pip install --upgrade PySide6 aiohttp 'typer[all]' rich psutil PyYAML cryptography notify2 distro requests
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

