"""Qt based desktop interface for OpenFortiVPN Manager."""

from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.connection import ConnectionState
from ..core.manager import ConnectionManager
from ..core.profile import VPNProfile
from ..utils import browsers
from ..utils.logging import session_log_path
from .themes import apply_stylesheet

COLUMN_NAME = 0
COLUMN_STATUS = 1
COLUMN_HOST = 2
COLUMN_IP = 3
COLUMN_INTERFACE = 4
COLUMN_RX = 5
COLUMN_TX = 6
COLUMN_AUTORECONNECT = 7
COLUMN_ACTIONS = 8


def _status_icon(color: str) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(16, 16)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QBrush(QtGui.QColor(color)))
    painter.drawEllipse(2, 2, 12, 12)
    painter.end()
    return QtGui.QIcon(pixmap)


def _action_icon(color: str) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(18, 18)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.setBrush(QtGui.QBrush(QtGui.QColor(color)))
    painter.drawEllipse(3, 3, 12, 12)
    painter.end()
    return QtGui.QIcon(pixmap)


def _theme_icon(theme: str) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(18, 18)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    if theme == "dark":
        painter.setBrush(QtGui.QColor("#F1C933"))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 14, 14)
        painter.setBrush(QtGui.QColor("#1E1E2F"))
        painter.drawEllipse(8, 2, 8, 14)
    else:
        painter.setBrush(QtGui.QColor("#1890F0"))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 14, 14)
        painter.setBrush(QtGui.QColor("#FFFFFF"))
        painter.drawEllipse(5, 5, 8, 8)
    painter.end()
    return QtGui.QIcon(pixmap)


class ProfileEditorDialog(QtWidgets.QDialog):
    """Dialog for creating or editing VPN profiles."""

    def __init__(self, parent: QtWidgets.QWidget | None, profile: VPNProfile | None = None):
        super().__init__(parent)
        self.setWindowTitle("VPN Profile")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.profile = profile
        self._build_ui()
        if profile:
            self._populate(profile)

    def _build_ui(self) -> None:
        layout = QtWidgets.QFormLayout(self)
        layout.setSpacing(12)

        self.name_edit = QtWidgets.QLineEdit()
        self.host_edit = QtWidgets.QLineEdit()
        self.port_spin = QtWidgets.QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(443)

        self.saml_checkbox = QtWidgets.QCheckBox("Use SAML authentication")
        self.saml_port_spin = QtWidgets.QSpinBox()
        self.saml_port_spin.setRange(1024, 65000)
        self.saml_port_spin.setValue(8021)

        self.browser_combo = QtWidgets.QComboBox()
        self.browser_combo.addItem("System default", userData=None)
        for browser in browsers.detect_browsers():
            if browser == "default":
                continue
            display = browser.replace("-", " ").title()
            self.browser_combo.addItem(display, userData=browser)

        self.browser_profile_combo = QtWidgets.QComboBox()
        self.browser_profile_combo.addItem("Automatic", userData=None)

        self.username_edit = QtWidgets.QLineEdit()
        self.password_edit = QtWidgets.QLineEdit()
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)

        self.auto_reconnect_checkbox = QtWidgets.QCheckBox("Auto reconnect")
        self.reconnect_spin = QtWidgets.QSpinBox()
        self.reconnect_spin.setRange(5, 3600)
        self.reconnect_spin.setValue(15)

        self.routing_edit = QtWidgets.QPlainTextEdit()
        self.routing_edit.setPlaceholderText("10.10.0.0/24\ncorp.internal")
        self.dns_edit = QtWidgets.QPlainTextEdit()
        self.dns_edit.setPlaceholderText("1.1.1.1\n8.8.8.8")

        self.persistent_checkbox = QtWidgets.QCheckBox("Use --persistent reconnect mode")
        self.persistent_checkbox.setChecked(True)

        layout.addRow("Name", self.name_edit)
        layout.addRow("Host", self.host_edit)
        layout.addRow("Port", self.port_spin)
        layout.addRow(self.saml_checkbox)
        layout.addRow("SAML listener port", self.saml_port_spin)
        layout.addRow("Browser", self.browser_combo)
        layout.addRow("Browser profile", self.browser_profile_combo)
        layout.addRow("Username", self.username_edit)
        layout.addRow("Password", self.password_edit)
        layout.addRow(self.auto_reconnect_checkbox)
        layout.addRow("Reconnect delay (s)", self.reconnect_spin)
        layout.addRow("Routing rules (one per line)", self.routing_edit)
        layout.addRow("Custom DNS (one per line)", self.dns_edit)
        layout.addRow(self.persistent_checkbox)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

        self.saml_checkbox.stateChanged.connect(self._update_auth_controls)
        self.browser_combo.currentIndexChanged.connect(self._on_browser_changed)
        self._update_auth_controls()

    def _populate(self, profile: VPNProfile) -> None:
        self.name_edit.setText(profile.name)
        self.host_edit.setText(profile.host)
        self.port_spin.setValue(profile.port)
        self.saml_checkbox.setChecked(profile.enable_saml)
        self.saml_port_spin.setValue(profile.saml_port)

        if profile.browser:
            index = self.browser_combo.findData(profile.browser)
            if index >= 0:
                self.browser_combo.setCurrentIndex(index)
        else:
            self.browser_combo.setCurrentIndex(0)
        self._populate_browser_profiles(self.browser_combo.currentData(), profile.browser_profile)

        if profile.username:
            self.username_edit.setText(profile.username)
        if profile.password:
            self.password_edit.setText(profile.password)
        self.auto_reconnect_checkbox.setChecked(profile.auto_reconnect)
        self.reconnect_spin.setValue(profile.auto_reconnect_interval)
        self.routing_edit.setPlainText("\n".join(profile.routing_rules))
        self.dns_edit.setPlainText("\n".join(profile.custom_dns))
        self.persistent_checkbox.setChecked(profile.persistent)

    def _update_auth_controls(self) -> None:
        saml_enabled = self.saml_checkbox.isChecked()
        self.saml_port_spin.setEnabled(saml_enabled)
        self.browser_combo.setEnabled(saml_enabled)
        self.browser_profile_combo.setEnabled(saml_enabled)
        self.username_edit.setEnabled(not saml_enabled)
        self.password_edit.setEnabled(not saml_enabled)
        if saml_enabled:
            self._populate_browser_profiles(self.browser_combo.currentData())

    def _on_browser_changed(self) -> None:
        self._populate_browser_profiles(self.browser_combo.currentData())

    def _populate_browser_profiles(self, browser_name: str | None, selected: str | None = None) -> None:
        self.browser_profile_combo.blockSignals(True)
        self.browser_profile_combo.clear()
        self.browser_profile_combo.addItem("Automatic", userData=None)
        if browser_name:
            for profile_name in browsers.detect_profiles(browser_name):
                self.browser_profile_combo.addItem(profile_name, userData=profile_name)
        if selected:
            index = self.browser_profile_combo.findData(selected)
            if index >= 0:
                self.browser_profile_combo.setCurrentIndex(index)
            else:
                self.browser_profile_combo.addItem(selected, userData=selected)
                self.browser_profile_combo.setCurrentIndex(self.browser_profile_combo.count() - 1)
        self.browser_profile_combo.blockSignals(False)

    def get_profile(self) -> VPNProfile | None:
        if self.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None

        browser_name = self.browser_combo.currentData()
        browser_profile = self.browser_profile_combo.currentData()

        profile = VPNProfile(
            name=self.name_edit.text().strip(),
            host=self.host_edit.text().strip(),
            port=self.port_spin.value(),
            enable_saml=self.saml_checkbox.isChecked(),
            saml_port=self.saml_port_spin.value(),
            browser=browser_name,
            browser_profile=browser_profile,
            username=self.username_edit.text().strip() or None,
            password=self.password_edit.text().strip() or None,
            auto_reconnect=self.auto_reconnect_checkbox.isChecked(),
            auto_reconnect_interval=self.reconnect_spin.value(),
            routing_rules=[line.strip() for line in self.routing_edit.toPlainText().splitlines() if line.strip()],
            custom_dns=[line.strip() for line in self.dns_edit.toPlainText().splitlines() if line.strip()],
            persistent=self.persistent_checkbox.isChecked(),
        )
        if not profile.enable_saml:
            profile.browser = None
            profile.browser_profile = None
        return profile


class LogViewer(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None, log_path: Path) -> None:
        super().__init__(parent)
        self.setWindowTitle("Session Log")
        self.setMinimumSize(640, 420)
        layout = QtWidgets.QVBoxLayout(self)
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        if log_path.exists():
            self.text.setPlainText(log_path.read_text(encoding="utf-8"))
        else:
            self.text.setPlainText("Log file not found")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, manager: ConnectionManager, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.manager = manager
        self.loop = loop
        self.setWindowTitle("OpenFortiVPN Manager")
        self.resize(1024, 640)
        self.settings = QtCore.QSettings("OpenFortiVPN", "Manager")
        self._row_buttons: dict[str, tuple[QtWidgets.QPushButton, QtWidgets.QPushButton]] = {}
        self.status_icons = {
            ConnectionState.CONNECTED: _status_icon("#3CC480"),
            ConnectionState.CONNECTING: _status_icon("#F1C933"),
            ConnectionState.DISCONNECTED: _status_icon("#FF616D"),
            ConnectionState.ERROR: _status_icon("#FF616D"),
            ConnectionState.RECONNECTING: _status_icon("#F1C933"),
        }
        self.action_icons = {
            "connect": _action_icon("#3CC480"),
            "connected": _action_icon("#3CC480"),
            "pending": _action_icon("#F1C933"),
            "disconnect": _action_icon("#FF616D"),
            "disabled": _action_icon("#8E8EA0"),
        }
        self._build_ui()
        stored_theme = self.settings.value("appearance/theme", "dark")
        self._apply_theme(stored_theme if stored_theme in {"dark", "light"} else "dark")
        self._setup_tray()
        self._refresh_profiles()
        self._show_dependency_warnings()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._refresh_statuses)
        self.timer.start(1500)
        self._update_future = asyncio.run_coroutine_threadsafe(self.manager.check_for_updates(), self.loop)
        self.update_check_timer = QtCore.QTimer(self)
        self.update_check_timer.setSingleShot(True)
        self.update_check_timer.timeout.connect(self._poll_update_future)
        self.update_check_timer.start(5000)

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setSpacing(20)
        layout.setContentsMargins(24, 24, 24, 24)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setSpacing(12)

        self.add_button = QtWidgets.QPushButton("Add")
        self.edit_button = QtWidgets.QPushButton("Edit")
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.duplicate_button = QtWidgets.QPushButton("Duplicate")
        self.connect_button = QtWidgets.QPushButton("Connect")
        self.disconnect_button = QtWidgets.QPushButton("Disconnect")
        self.export_button = QtWidgets.QPushButton("Export")
        self.import_button = QtWidgets.QPushButton("Import")
        self.log_button = QtWidgets.QPushButton("View Logs")
        self.theme_toggle = QtWidgets.QPushButton("Toggle Theme")
        self.theme_toggle.setIconSize(QtCore.QSize(18, 18))

        for button, tooltip in [
            (self.add_button, "Create a new VPN profile"),
            (self.edit_button, "Edit the selected profile"),
            (self.delete_button, "Delete the selected profile"),
            (self.duplicate_button, "Clone the selected profile"),
            (self.connect_button, "Connect the selected profile"),
            (self.disconnect_button, "Disconnect the selected profile"),
            (self.export_button, "Export all profiles"),
            (self.import_button, "Import profiles from file"),
            (self.log_button, "View logs for the selected profile"),
        ]:
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            button.setToolTip(tooltip)

        self.theme_toggle.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        header_layout.addWidget(self.add_button)
        header_layout.addWidget(self.edit_button)
        header_layout.addWidget(self.delete_button)
        header_layout.addWidget(self.duplicate_button)
        header_layout.addWidget(self.connect_button)
        header_layout.addWidget(self.disconnect_button)
        header_layout.addWidget(self.export_button)
        header_layout.addWidget(self.import_button)
        header_layout.addWidget(self.log_button)
        header_layout.addStretch(1)
        header_layout.addWidget(self.theme_toggle)

        layout.addLayout(header_layout)

        self.profile_view = QtWidgets.QTreeWidget()
        self.profile_view.setAlternatingRowColors(True)
        self.profile_view.setRootIsDecorated(False)
        self.profile_view.setIndentation(0)
        self.profile_view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.profile_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.profile_view.setUniformRowHeights(True)
        self.profile_view.setMouseTracking(True)
        self.profile_view.setColumnCount(9)
        self.profile_view.setHeaderLabels(
            [
                "Name",
                "Status",
                "Host",
                "IP",
                "Interface",
                "RX bytes",
                "TX bytes",
                "Auto reconnect",
                "Actions",
            ]
        )
        header = self.profile_view.header()
        header.setSectionResizeMode(COLUMN_NAME, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COLUMN_STATUS, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_HOST, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_IP, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_INTERFACE, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_RX, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_TX, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_AUTORECONNECT, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_ACTIONS, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.profile_view, stretch=1)

        footer_layout = QtWidgets.QHBoxLayout()
        footer_layout.addStretch(1)
        layout.addLayout(footer_layout)

        self.add_button.clicked.connect(self._add_profile)
        self.edit_button.clicked.connect(self._edit_profile)
        self.delete_button.clicked.connect(self._delete_profile)
        self.duplicate_button.clicked.connect(self._duplicate_profile)
        self.connect_button.clicked.connect(self._connect_selected)
        self.disconnect_button.clicked.connect(self._disconnect_selected)
        self.export_button.clicked.connect(self._export_profiles)
        self.import_button.clicked.connect(self._import_profiles)
        self.log_button.clicked.connect(self._show_logs)
        self.theme_toggle.clicked.connect(self._toggle_theme)
        self.profile_view.itemSelectionChanged.connect(self._update_toolbar_state)
        self.profile_view.itemDoubleClicked.connect(lambda *_: self._edit_profile())

    def _setup_tray(self) -> None:
        self.tray = QtWidgets.QSystemTrayIcon(QtGui.QIcon.fromTheme("network-vpn"), self)
        menu = QtWidgets.QMenu()
        show_action = menu.addAction("Show")
        quit_action = menu.addAction("Quit")
        show_action.triggered.connect(self.show)
        quit_action.triggered.connect(QtWidgets.QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _apply_theme(self, theme: str) -> None:
        theme_name = theme if theme in {"dark", "light"} else "dark"
        apply_stylesheet(QtWidgets.QApplication.instance(), theme_name)
        self.current_theme = theme_name
        self.settings.setValue("appearance/theme", theme_name)
        target = "light" if theme_name == "dark" else "dark"
        self.theme_toggle.setText("Toggle Theme")
        self.theme_toggle.setToolTip(f"Switch to {target} theme")
        self.theme_toggle.setIcon(_theme_icon(target))

    def _refresh_profiles(self) -> None:
        self.profile_view.clear()
        self._row_buttons.clear()
        profiles = sorted(self.manager.list_profiles(), key=lambda p: p.name.lower())
        for profile in profiles:
            item = QtWidgets.QTreeWidgetItem(
                [
                    profile.name,
                    "Disconnected",
                    f"{profile.host}:{profile.port}",
                    "-",
                    "-",
                    "0",
                    "0",
                    "Yes" if profile.auto_reconnect else "No",
                    "",
                ]
            )
            item.setData(COLUMN_NAME, QtCore.Qt.ItemDataRole.UserRole, profile.name)
            item.setIcon(COLUMN_STATUS, self.status_icons[ConnectionState.DISCONNECTED])
            item.setToolTip(COLUMN_NAME, profile.display_name())
            item.setSizeHint(COLUMN_NAME, QtCore.QSize(0, 48))
            self.profile_view.addTopLevelItem(item)
            self._add_row_actions(item, profile.name)
        self.profile_view.sortItems(COLUMN_NAME, QtCore.Qt.SortOrder.AscendingOrder)
        self._update_toolbar_state()

    def _add_row_actions(self, item: QtWidgets.QTreeWidgetItem, profile_name: str) -> None:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        connect_btn = QtWidgets.QPushButton("Connect")
        disconnect_btn = QtWidgets.QPushButton("Disconnect")
        connect_btn.setObjectName("connectButton")
        disconnect_btn.setObjectName("disconnectButton")
        connect_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        disconnect_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        connect_btn.setToolTip(f"Connect {profile_name}")
        disconnect_btn.setToolTip(f"Disconnect {profile_name}")
        disconnect_btn.setEnabled(False)
        connect_btn.setIcon(self.action_icons["connect"])
        connect_btn.setIconSize(QtCore.QSize(16, 16))
        disconnect_btn.setIcon(self.action_icons["disabled"])
        disconnect_btn.setIconSize(QtCore.QSize(16, 16))

        connect_btn.clicked.connect(lambda _, n=profile_name: self._connect_profile(n))
        disconnect_btn.clicked.connect(lambda _, n=profile_name: self._disconnect_profile(n))

        layout.addWidget(connect_btn)
        layout.addWidget(disconnect_btn)
        layout.addStretch(1)
        container.setLayout(layout)
        self.profile_view.setItemWidget(item, COLUMN_ACTIONS, container)
        self._row_buttons[profile_name] = (connect_btn, disconnect_btn)

    def _refresh_statuses(self) -> None:
        for row in range(self.profile_view.topLevelItemCount()):
            item = self.profile_view.topLevelItem(row)
            name = item.data(COLUMN_NAME, QtCore.Qt.ItemDataRole.UserRole)
            if not name:
                continue
            status = self.manager.get_status(name)
            if not status:
                continue
            state_text = status.state.value.capitalize()
            if status.state == ConnectionState.RECONNECTING and status.reconnect_in is not None:
                state_text = f"Reconnecting ({status.reconnect_in}s)"
            elif status.state == ConnectionState.ERROR and status.last_error:
                state_text = status.last_error

            icon = self.status_icons.get(status.state, self.status_icons[ConnectionState.DISCONNECTED])
            item.setText(COLUMN_STATUS, state_text)
            item.setIcon(COLUMN_STATUS, icon)
            item.setText(COLUMN_IP, status.ip_address or "-")
            item.setText(COLUMN_INTERFACE, status.interface or "-")
            item.setText(COLUMN_RX, f"{status.bandwidth_in:.0f}")
            item.setText(COLUMN_TX, f"{status.bandwidth_out:.0f}")
            item.setText(COLUMN_AUTORECONNECT, "Yes" if status.auto_reconnect else "No")
            self._update_row_buttons(name, status)
        self._update_toolbar_state()

    def _update_row_buttons(self, profile_name: str, status) -> None:
        buttons = self._row_buttons.get(profile_name)
        if not buttons:
            return
        connect_btn, disconnect_btn = buttons

        if status.state == ConnectionState.CONNECTED:
            connect_btn.setEnabled(False)
            connect_btn.setText("Connected")
            connect_btn.setIcon(self.action_icons["connected"])
            connect_btn.setToolTip(f"{profile_name} is connected")
            disconnect_btn.setEnabled(True)
            disconnect_btn.setIcon(self.action_icons["disconnect"])
            disconnect_btn.setToolTip(f"Disconnect {profile_name}")
        elif status.state in {ConnectionState.CONNECTING, ConnectionState.RECONNECTING}:
            connect_btn.setEnabled(False)
            connect_btn.setText("Connecting…")
            connect_btn.setIcon(self.action_icons["pending"])
            connect_btn.setToolTip(f"{profile_name} is establishing a tunnel")
            disconnect_btn.setEnabled(True)
            disconnect_btn.setIcon(self.action_icons["disconnect"])
            disconnect_btn.setToolTip(f"Cancel connection for {profile_name}")
        elif status.state == ConnectionState.ERROR:
            connect_btn.setEnabled(True)
            connect_btn.setText("Retry")
            connect_btn.setIcon(self.action_icons["connect"])
            connect_btn.setToolTip(status.last_error or f"Retry connection for {profile_name}")
            disconnect_btn.setEnabled(False)
            disconnect_btn.setIcon(self.action_icons["disabled"])
            disconnect_btn.setToolTip(f"{profile_name} is not connected")
        else:
            connect_btn.setEnabled(True)
            connect_btn.setText("Connect")
            connect_btn.setIcon(self.action_icons["connect"])
            connect_btn.setToolTip(f"Connect {profile_name}")
            disconnect_btn.setEnabled(False)
            disconnect_btn.setIcon(self.action_icons["disabled"])
            disconnect_btn.setToolTip(f"{profile_name} is not connected")

    def _selected_profile_name(self) -> str | None:
        items = self.profile_view.selectedItems()
        if not items:
            return None
        return items[0].data(COLUMN_NAME, QtCore.Qt.ItemDataRole.UserRole)

    def _connect_profile(self, name: str) -> None:
        asyncio.run_coroutine_threadsafe(self.manager.connect(name), self.loop)

    def _disconnect_profile(self, name: str) -> None:
        asyncio.run_coroutine_threadsafe(self.manager.disconnect(name), self.loop)

    def _add_profile(self) -> None:
        dialog = ProfileEditorDialog(self)
        profile = dialog.get_profile()
        if profile:
            self.manager.add_or_update_profile(profile)
            self._refresh_profiles()

    def _edit_profile(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        profile = self.manager.profiles.get(name)
        if not profile:
            return
        dialog = ProfileEditorDialog(self, profile)
        updated = dialog.get_profile()
        if updated:
            if updated.name != name and name in self.manager.connections:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Cannot rename profile",
                    "Disconnect the VPN before renaming the profile.",
                )
                return
            self.manager.add_or_update_profile(updated)
            self._refresh_profiles()

    def _delete_profile(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        reply = QtWidgets.QMessageBox.question(self, "Delete profile", f"Delete profile {name}?")
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                self.manager.delete_profile(name)
            except RuntimeError as exc:
                QtWidgets.QMessageBox.warning(self, "Error", str(exc))
            self._refresh_profiles()

    def _duplicate_profile(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        profile = self.manager.profiles.get(name)
        if not profile:
            return
        new_name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Duplicate profile",
            "New profile name:",
            text=f"{name} copy",
        )
        if not ok or not new_name.strip():
            return
        clone = VPNProfile.from_dict(profile.to_dict())
        clone.name = new_name.strip()
        self.manager.add_or_update_profile(clone)
        self._refresh_profiles()

    def _connect_selected(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        self._connect_profile(name)

    def _disconnect_selected(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        self._disconnect_profile(name)

    def _show_logs(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        log_path = session_log_path(name)
        LogViewer(self, log_path).exec()

    def _export_profiles(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export profiles",
            "profiles.json",
            "JSON (*.json);;YAML (*.yml)",
        )
        if path:
            self.manager.export_profiles(Path(path))

    def _import_profiles(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import profiles",
            "",
            "JSON/YAML (*.json *.yml)",
        )
        if path:
            self.manager.import_profiles(Path(path))
            self._refresh_profiles()

    def _toggle_theme(self) -> None:
        new_theme = "light" if getattr(self, "current_theme", "dark") == "dark" else "dark"
        self._apply_theme(new_theme)

    def _update_toolbar_state(self) -> None:
        name = self._selected_profile_name()
        if not name:
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(False)
            self.log_button.setEnabled(False)
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.duplicate_button.setEnabled(False)
            return
        status = self.manager.get_status(name)
        self.edit_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.duplicate_button.setEnabled(True)
        self.log_button.setEnabled(True)
        if not status or status.state in {ConnectionState.DISCONNECTED, ConnectionState.ERROR}:
            self.connect_button.setEnabled(True)
            self.disconnect_button.setEnabled(False)
        elif status.state == ConnectionState.CONNECTED:
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
        else:
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        asyncio.run_coroutine_threadsafe(self.manager.disconnect_all(), self.loop)
        super().closeEvent(event)

    def _poll_update_future(self) -> None:
        if self._update_future.done():
            try:
                result = self._update_future.result()
            except Exception:
                result = None
            if result:
                QtWidgets.QMessageBox.information(
                    self,
                    "Update available",
                    f"A new version ({result['version']}) is available.\n{result.get('url', '')}",
                )
        else:
            self.update_check_timer.start(2000)

    def _show_dependency_warnings(self) -> None:
        report = self.manager.dependency_report()
        missing = report.get("missing") or {}
        if missing:
            commands = "\n".join(f"{name}: {cmd}" for name, cmd in missing.items())
            QtWidgets.QMessageBox.warning(
                self,
                "Missing dependencies",
                "Some recommended dependencies are missing:\n" + commands,
            )
