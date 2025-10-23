# OpenFortiVPN Manager

OpenFortiVPN Manager is a desktop companion for the [`openfortivpn`](https://github.com/adrienverge/openfortivpn) CLI client. It provides a PyQt-based interface for creating Fortinet SSL VPN profiles, storing credentials in the system keyring, launching browser-assisted SAML logins, and monitoring sessions and logs in real time.

## Features

- Graphical profile editor with support for password and SAML authentication flows.
- Browser discovery for Firefox, Chromium, Chrome, and Edge profiles used in SAML handoffs.
- Keyring-backed credential storage with "forget password" tooling.
- Real-time session log viewer, auto-reconnect toggle, and custom per-profile route lists.
- Automated setup of configuration/log directories and a desktop launcher entry on first run.

## Requirements

- Python 3.9 or newer.
- The `openfortivpn` binary available on your `$PATH`.
- Qt bindings (PyQt6 preferred, PyQt5 supported).
- Supporting Python modules: `PyYAML`, `psutil`, and `keyring`.

The application prints friendly guidance if any requirement is missing. Common installation commands:

| Distribution | Command |
| --- | --- |
| Fedora | `sudo dnf install python3-qt5 python3-pyyaml python3-psutil python3-keyring openfortivpn` |
| Debian / Ubuntu | `sudo apt install python3-pyqt6 python3-yaml python3-psutil python3-keyring openfortivpn` |
| Arch | `sudo pacman -S python-pyqt6 python-yaml python-psutil python-keyring openfortivpn` |

To use a Python virtual environment instead, install the OS package for `openfortivpn` and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install PyQt6 PyYAML psutil keyring
```

## Installation

1. Clone the repository and enter it:
   ```bash
   git clone https://github.com/<your-account>/OpenFortiVPN-Manager.git
   cd OpenFortiVPN-Manager
   ```
2. Install the dependencies shown above.
3. (Optional) Run the unit tests:
   ```bash
   python -m compileall tests
   ```

## Running the application

Start the manager with:

```bash
python3 openfortivpn_manager.py
```

On the first launch the application will:

- Ensure configuration lives in `~/.config/OpenFortiVPN-Manager/` and logs in `~/.config/OpenFortiVPN-Manager/logs/`.
- Create `~/.config/OpenFortiVPN-Manager/README.txt` with runtime tips.
- Generate a desktop entry at `~/.local/share/applications/OpenFortiVPN-Manager.desktop` pointing to the current interpreter.

Profiles are stored in `~/.config/OpenFortiVPN-Manager/profiles.yaml`. Passwords saved through the GUI are written to the system keyring.

## Creating a desktop shortcut

1. Launch the application at least once so the desktop entry is generated.
2. Copy or link the launcher to your desktop:
   ```bash
   mkdir -p ~/Desktop
   cp ~/.local/share/applications/OpenFortiVPN-Manager.desktop ~/Desktop/
   chmod +x ~/Desktop/OpenFortiVPN-Manager.desktop
   ```
3. On GNOME, KDE, and most desktop environments you can now double-click the shortcut or add it to your favorites/app grid. Adjust the `Icon=` field in the `.desktop` file if you want to point at a custom icon (the default icon name is `network-vpn`).

## Auto-update options

The project does not update itself automatically, but you can wrap the launcher so that it pulls the latest Git changes before every start.

1. Create an updater script:
   ```bash
   mkdir -p ~/.local/bin
   cat <<'SCRIPT' > ~/.local/bin/openfortivpn-manager-launcher
   #!/usr/bin/env bash
   set -euo pipefail
   REPO_DIR="$HOME/path/to/OpenFortiVPN-Manager"
   cd "$REPO_DIR"
   git pull --ff-only
   exec python3 openfortivpn_manager.py
   SCRIPT
   chmod +x ~/.local/bin/openfortivpn-manager-launcher
   ```
2. Edit `~/.local/share/applications/OpenFortiVPN-Manager.desktop` and change the `Exec=` line to:
   ```
   Exec=/home/<you>/.local/bin/openfortivpn-manager-launcher
   ```
3. The shortcut will now fetch updates whenever you launch it from the desktop or application menu.

To turn off auto-update, revert the `Exec=` line back to `python3 /full/path/to/openfortivpn_manager.py` or delete the helper script.

## Uninstallation

1. Remove the clone:
   ```bash
   rm -rf /path/to/OpenFortiVPN-Manager
   ```
2. Delete the configuration, logs, and generated README:
   ```bash
   rm -rf ~/.config/OpenFortiVPN-Manager
   ```
3. Remove the desktop entry and any copied shortcuts:
   ```bash
   rm -f ~/.local/share/applications/OpenFortiVPN-Manager.desktop
   rm -f ~/Desktop/OpenFortiVPN-Manager.desktop
   ```
4. (Optional) Uninstall dependencies if they were installed solely for the manager, e.g. `sudo apt remove python3-pyqt6 python3-yaml python3-psutil python3-keyring`.

## Troubleshooting

- **Missing dependencies:** Rerun the installation commands for your distribution. The launcher prints detailed hints about what is missing.
- **`openfortivpn` not found:** Install the system package or ensure it is discoverable via `$PATH`.
- **Permission errors when adding routes:** Allow the application to elevate privileges via `pkexec` or `sudo` when prompted.
- **Keyring issues:** Use your desktop environment's secret service, or fall back to storing credentials in the profile dialog when the keyring is unavailable.

For further details inspect `~/.config/OpenFortiVPN-Manager/README.txt`, which the application keeps in sync with the current version.
