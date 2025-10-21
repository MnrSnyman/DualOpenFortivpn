# Multi-VPN Manager

The Multi-VPN Manager is a PyQt6 desktop application that orchestrates multiple
`openfortivpn` SAML connections. It provides a GUI for configuring VPN
endpoints, automatically opens the appropriate browser for SAML authentication,
and maintains optional auto-reconnect and split-routing rules per profile.

## Prerequisites

The application targets modern Linux desktops where `openfortivpn` is
available. Before running the manager make sure the following components are
installed:

### System packages (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install \
    python3 python3-pip python3-venv \
    openfortivpn policykit-1 \
    libegl1
```

* `python3`, `python3-pip`, and `python3-venv` provide the Python runtime and
  tooling for a virtual environment.
* `openfortivpn` is the CLI client launched by the manager.
* `policykit-1` supplies `pkexec` so privilege prompts appear as graphical
  dialogs.
* `libegl1` ensures Qt's OpenGL backend loads correctly when using the PyQt6
  wheels.

For other distributions install equivalent packages via `dnf`, `pacman`, or
`zypper`. Make sure that `openfortivpn` runs successfully from the terminal
before launching the GUI.

### Python dependencies

Create and activate a virtual environment (optional but recommended) and
install the Python dependencies with pip:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install PyQt6 PyYAML
```

If you prefer not to use a virtual environment replace the first two commands
with `pip3 install --user ...`.

## Running the application

1. Clone this repository and change into it:
   ```bash
   git clone https://github.com/your-org/DualOpenFortivpn.git
   cd DualOpenFortivpn
   ```
2. Ensure the virtual environment (if created) is activated.
3. Launch the GUI:
   ```bash
   python3 multi_vpn_manager.py
   ```

On first launch the application creates `~/.config/multi_vpn_manager/config.yaml`
and installs a `.desktop` entry in `~/.local/share/applications/` and on your
Desktop (if present) so you can start it from your system menu. The GUI prompts
for administrative privileges using your system's authentication dialog when it
needs to run `openfortivpn` or adjust routes.

## Configuration tips

* Use the **Add VPN** toolbar button to create profiles. Each profile can
  specify SAML usage, the browser and browser profile for the login, an optional
  custom port, and split-routing entries (CIDR, hostnames, or URLs) that will be
  forced through the VPN interface.
* The auto-reconnect toggle enables exponential backoff retries when the tunnel
  drops unexpectedly.
* Logs for each VPN appear in the lower pane. Errors and status changes are also
  reflected in the table.

## Updating

Whenever you update the repository, reinstall the virtual environment
requirements if `multi_vpn_manager.py` introduces new dependencies:

```bash
git pull
python3 -m pip install --upgrade PyQt6 PyYAML
```

## Troubleshooting

* If the GUI cannot find your browser executable, adjust the browser setting in
  the profile or ensure the browser is available in your `PATH`.
* For PKI or biometric prompts, follow the system dialog that appears after the
  manager requests elevated privileges.
* Remove `~/.local/share/applications/multi-vpn-manager.desktop` if you no
  longer want the desktop launcher.
