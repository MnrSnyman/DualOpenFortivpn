# Multi-VPN Manager

The Multi-VPN Manager is a PyQt6 desktop application that orchestrates multiple
`openfortivpn` SAML connections. It provides a GUI for configuring VPN
endpoints, automatically opens the appropriate browser for SAML authentication,
and maintains optional auto-reconnect and split-routing rules per profile.

## Prerequisites

The application targets modern Linux desktops where `openfortivpn` is
available. Before running the manager make sure the following components are
installed:

### System packages

Install the distribution packages that provide Python 3, `openfortivpn`, and a
PolicyKit helper so the application can elevate privileges through a graphical
prompt. Use the commands that match your platform:

#### Debian / Ubuntu / Linux Mint

```bash
sudo apt update
sudo apt install \
    python3 python3-pip python3-venv \
    openfortivpn policykit-1 \
    python3-keyring python3-secretstorage \
    libegl1
```

#### Fedora / RHEL / AlmaLinux / Rocky Linux

```bash
sudo dnf install \
    python3 python3-pip python3-virtualenv \
    openfortivpn polkit \
    python3-keyring python3-secretstorage \
    mesa-libEGL
```

> **Note:** On RHEL-like systems you may need to enable the EPEL repository
> before `openfortivpn` becomes available:
> ```bash
> sudo dnf install epel-release
> ```

#### Arch Linux / Manjaro

```bash
sudo pacman -Syu
sudo pacman -S \
    python python-pip python-virtualenv \
    openfortivpn polkit \
    python-keyring python-secretstorage \
    qt6-base
```

#### openSUSE Leap / Tumbleweed

```bash
sudo zypper refresh
sudo zypper install \
    python3 python3-pip python3-virtualenv \
    openfortivpn polkit \
    python3-keyring python3-secretstorage \
    Mesa-libEGL1
```

> Replace `python3-virtualenv` with the versioned package provided by your
> release (for example `python311-virtualenv`) if needed.

* `python3`, `python3-pip`, and a virtual-env package provide the Python
  runtime and tooling for an isolated environment.
* `openfortivpn` is the CLI client launched by the manager.
* `polkit`/`policykit-1` supplies `pkexec` so privilege prompts appear as
  graphical dialogs.
* `libEGL` (packaged as `libegl1`, `mesa-libEGL`, `qt6-base`, or
  `Mesa-libEGL1`) ensures Qt's OpenGL backend loads correctly when using the
  PyQt6 wheels.

Make sure that `openfortivpn` runs successfully from the terminal before
launching the GUI.

### Python dependencies

Create and activate a virtual environment (optional but recommended) and
install the Python dependencies with pip:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install PyQt6 PyYAML keyring
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

### Using a downloaded copy (private repository)

If you cannot clone the repository directly (for example the project is private
and you only need the latest script), you can download `multi_vpn_manager.py`
and run it in place:

1. Create a folder to hold the script and change into it:
   ```bash
   mkdir -p ~/MultiVPNManager
   cd ~/MultiVPNManager
   ```
2. Download the Python file through your browser (GitHub ▸ *multi_vpn_manager.py*
   ▸ **Raw** ▸ Save As…) **or** use `curl` with a personal access token that has
   access to the repository:
   ```bash
   curl -H "Authorization: token <YOUR_TOKEN>" \
        -L https://raw.githubusercontent.com/your-org/DualOpenFortivpn/main/multi_vpn_manager.py \
        -o multi_vpn_manager.py
   ```
   Replace `<YOUR_TOKEN>` and the URL path with your organization/repository
   names as appropriate.
3. Ensure the prerequisites from the sections above are installed (system
   packages plus the `PyQt6` and `PyYAML` Python wheels).
4. Launch the application directly from the folder:
   ```bash
   python3 multi_vpn_manager.py
   ```

The script still creates the configuration directory and desktop launcher in
your home folder, so subsequent runs can be started from the desktop icon or
application menu without returning to the terminal.

## Desktop launcher installation

The first time you start the application it automatically writes
`multi-vpn-manager.desktop` to both `~/.local/share/applications/` and (if the
folder exists) `~/Desktop`. Most desktop environments require you to mark the
launcher as trusted the first time you double-click it.

To reinstall or refresh the launcher without opening the GUI, run the helper
from a terminal:

```bash
python3 - <<'PY'
import multi_vpn_manager
multi_vpn_manager.install_desktop_entry()
PY
```

After creating the launcher, run the following if your desktop environment
needs the file to be executable:

```bash
chmod +x ~/Desktop/multi-vpn-manager.desktop
```

## Password-based VPN profiles

Not every FortiGate deployment uses SAML. When the **Authentication** drop-down
is set to **Username & Password** for a profile, the editor exposes fields for a
VPN **Username** and an optional **Save password securely** toggle. When enabled,
the manager stores the password inside your system keyring via
[`python3-keyring`](https://pypi.org/project/keyring/), ensuring credentials are
never written to the YAML configuration file. If a keyring backend is not
available the GUI warns you and falls back to prompting for the password each
time you connect.

Switching a profile back to SAML or unchecking the save option automatically
removes any stored password from the keyring.

## Configuration tips

* Use the **Add VPN** toolbar button to create profiles. Each profile can
  specify the authentication mode, an optional browser profile (leave blank to use the
  browser's default), a custom port, split-routing entries (CIDR, hostnames, or
  URLs), and—for non-SAML deployments—the VPN username and whether the password
  should be stored in the keyring.
* The auto-reconnect toggle enables exponential backoff retries when the tunnel
  drops unexpectedly.
* Logs for each VPN appear in the lower pane. Errors and status changes are also
  reflected in the table.

## Updating

Whenever you update the repository, reinstall the virtual environment
requirements if `multi_vpn_manager.py` introduces new dependencies:

```bash
git pull
python3 -m pip install --upgrade PyQt6 PyYAML keyring
```

## Troubleshooting

* If the GUI cannot find your browser executable, adjust the browser setting in
  the profile or ensure the browser is available in your `PATH`.
* For PKI or biometric prompts, follow the system dialog that appears after the
  manager requests elevated privileges.
* Remove `~/.local/share/applications/multi-vpn-manager.desktop` (and the copy on
  your Desktop) if you no longer want the desktop launcher.
