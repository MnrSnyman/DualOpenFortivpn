"""Qt based desktop interface for OpenFortiVPN Manager."""

from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.manager import ConnectionManager
from ..core.profile import VPNProfile
from ..core.connection import ConnectionState
from ..utils import browsers
from ..utils.logging import session_log_path


class ProfileEditorDialog(QtWidgets.QDialog):
    """Dialog for creating or editing VPN profiles."""

    def __init__(self, parent: QtWidgets.QWidget | None, profile: VPNProfile | None = None):
        super().__init__(parent)
        self.setWindowTitle("VPN Profile")
        self.profile = profile
        self._build_ui()
        if profile:
            self._populate(profile)

    def _build_ui(self) -> None:
        layout = QtWidgets.QFormLayout(self)
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
        for browser in browsers.detect_browsers():
            self.browser_combo.addItem(browser)
        self.browser_profile_combo = QtWidgets.QComboBox()
        self.username_edit = QtWidgets.QLineEdit()
        self.password_edit = QtWidgets.QLineEdit()
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.auto_reconnect_checkbox = QtWidgets.QCheckBox("Auto reconnect")
        self.reconnect_spin = QtWidgets.QSpinBox()
        self.reconnect_spin.setRange(5, 3600)
        self.reconnect_spin.setValue(15)
        self.routing_edit = QtWidgets.QPlainTextEdit()
        self.dns_edit = QtWidgets.QPlainTextEdit()
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

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.saml_checkbox.stateChanged.connect(self._update_auth_controls)
        self.browser_combo.currentTextChanged.connect(self._populate_browser_profiles)
        self._update_auth_controls()

    def _populate(self, profile: VPNProfile) -> None:
        self.name_edit.setText(profile.name)
        self.host_edit.setText(profile.host)
        self.port_spin.setValue(profile.port)
        self.saml_checkbox.setChecked(profile.enable_saml)
        self.saml_port_spin.setValue(profile.saml_port)
        if profile.browser:
            index = self.browser_combo.findText(profile.browser)
            if index >= 0:
                self.browser_combo.setCurrentIndex(index)
            self._populate_browser_profiles(profile.browser)
        if profile.browser_profile:
            index = self.browser_profile_combo.findText(profile.browser_profile)
            if index >= 0:
                self.browser_profile_combo.setCurrentIndex(index)
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
        saml = self.saml_checkbox.isChecked()
        for widget in [self.username_edit, self.password_edit]:
            widget.setEnabled(not saml)
        self.saml_port_spin.setEnabled(saml)
        self.browser_combo.setEnabled(saml)
        self.browser_profile_combo.setEnabled(saml)
        if saml:
            self._populate_browser_profiles(self.browser_combo.currentText())

    def get_profile(self) -> VPNProfile | None:
        if self.exec() != QtWidgets.QDialog.Accepted:
            return None
        browser_name = self.browser_combo.currentText() or None
        if browser_name == "default":
            browser_name = None
        profile = VPNProfile(
            name=self.name_edit.text().strip(),
            host=self.host_edit.text().strip(),
            port=self.port_spin.value(),
            enable_saml=self.saml_checkbox.isChecked(),
            saml_port=self.saml_port_spin.value(),
            browser=browser_name,
            browser_profile=self.browser_profile_combo.currentText() or None,
            username=self.username_edit.text().strip() or None,
            password=self.password_edit.text().strip() or None,
            auto_reconnect=self.auto_reconnect_checkbox.isChecked(),
            auto_reconnect_interval=self.reconnect_spin.value(),
            routing_rules=[line.strip() for line in self.routing_edit.toPlainText().splitlines() if line.strip()],
            custom_dns=[line.strip() for line in self.dns_edit.toPlainText().splitlines() if line.strip()],
            persistent=self.persistent_checkbox.isChecked(),
        )
        return profile

    def _populate_browser_profiles(self, browser_name: str | None = None) -> None:
        if browser_name is None:
            browser_name = self.browser_combo.currentText()
        self.browser_profile_combo.clear()
        if not browser_name or browser_name == "default":
            return
        for profile in browsers.detect_profiles(browser_name):
            self.browser_profile_combo.addItem(profile)


class LogViewer(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None, log_path: Path) -> None:
        super().__init__(parent)
        self.setWindowTitle("Session Log")
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
        self.resize(900, 600)
        self._build_ui()
        self._setup_tray()
        self._refresh_profiles()
        self._show_dependency_warnings()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._refresh_statuses)
        self.timer.start(2000)
        self._update_future = asyncio.run_coroutine_threadsafe(self.manager.check_for_updates(), self.loop)
        self.update_check_timer = QtCore.QTimer(self)
        self.update_check_timer.setSingleShot(True)
        self.update_check_timer.timeout.connect(self._poll_update_future)
        self.update_check_timer.start(5000)

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        header_layout = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("Add")
        self.edit_button = QtWidgets.QPushButton("Edit")
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.duplicate_button = QtWidgets.QPushButton("Duplicate")
        self.connect_button = QtWidgets.QPushButton("Connect")
        self.disconnect_button = QtWidgets.QPushButton("Disconnect")
        self.export_button = QtWidgets.QPushButton("Export")
        self.import_button = QtWidgets.QPushButton("Import")
        self.theme_toggle = QtWidgets.QPushButton("Toggle Theme")

        for button in [
            self.add_button,
            self.edit_button,
            self.delete_button,
            self.duplicate_button,
            self.connect_button,
            self.disconnect_button,
            self.export_button,
            self.import_button,
            self.theme_toggle,
        ]:
            header_layout.addWidget(button)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        self.profile_view = QtWidgets.QTreeWidget()
        self.profile_view.setHeaderLabels([
            "Name",
            "Status",
            "Host",
            "IP",
            "Interface",
            "RX bytes",
            "TX bytes",
            "Auto reconnect",
        ])
        self.profile_view.header().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self.profile_view)

        self.log_button = QtWidgets.QPushButton("View Logs")
        layout.addWidget(self.log_button)

        self.add_button.clicked.connect(self._add_profile)
        self.edit_button.clicked.connect(self._edit_profile)
        self.delete_button.clicked.connect(self._delete_profile)
        self.duplicate_button.clicked.connect(self._duplicate_profile)
        self.connect_button.clicked.connect(self._connect_selected)
        self.disconnect_button.clicked.connect(self._disconnect_selected)
        self.log_button.clicked.connect(self._show_logs)
        self.export_button.clicked.connect(self._export_profiles)
        self.import_button.clicked.connect(self._import_profiles)
        self.theme_toggle.clicked.connect(self._toggle_theme)

    def _setup_tray(self) -> None:
        self.tray = QtWidgets.QSystemTrayIcon(QtGui.QIcon.fromTheme("network-vpn"), self)
        menu = QtWidgets.QMenu()
        show_action = menu.addAction("Show")
        quit_action = menu.addAction("Quit")
        show_action.triggered.connect(self.show)
        quit_action.triggered.connect(QtWidgets.QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _refresh_profiles(self) -> None:
        self.profile_view.clear()
        for profile in self.manager.list_profiles():
            item = QtWidgets.QTreeWidgetItem([
                profile.name,
                "Disconnected",
                f"{profile.host}:{profile.port}",
                "-",
                "-",
                "0",
                "0",
                "Yes" if profile.auto_reconnect else "No",
            ])
            self.profile_view.addTopLevelItem(item)
        self.profile_view.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)

    def _refresh_statuses(self) -> None:
        for row in range(self.profile_view.topLevelItemCount()):
            item = self.profile_view.topLevelItem(row)
            name = item.text(0)
            status = self.manager.get_status(name)
            if not status:
                continue
            state_text = status.state.value
            if status.state == ConnectionState.RECONNECTING and status.reconnect_in is not None:
                state_text = f"reconnecting ({status.reconnect_in}s)"
            item.setText(1, state_text)
            item.setText(3, status.ip_address or "-")
            item.setText(4, status.interface or "-")
            item.setText(5, f"{status.bandwidth_in:.0f}")
            item.setText(6, f"{status.bandwidth_out:.0f}")
            item.setText(7, "Yes" if status.auto_reconnect else "No")

    def _selected_profile_name(self) -> str | None:
        items = self.profile_view.selectedItems()
        if not items:
            return None
        return items[0].text(0)

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
            self.manager.add_or_update_profile(updated)
            self._refresh_profiles()

    def _delete_profile(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        reply = QtWidgets.QMessageBox.question(self, "Delete", f"Delete profile {name}?")
        if reply == QtWidgets.QMessageBox.Yes:
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
        new_name, ok = QtWidgets.QInputDialog.getText(self, "Duplicate profile", "New profile name:", text=f"{name} copy")
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
        asyncio.run_coroutine_threadsafe(self.manager.connect(name), self.loop)

    def _disconnect_selected(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        asyncio.run_coroutine_threadsafe(self.manager.disconnect(name), self.loop)

    def _show_logs(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        log_path = session_log_path(name)
        LogViewer(self, log_path).exec()

    def _export_profiles(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export profiles", "profiles.json", "JSON (*.json);;YAML (*.yml)")
        if path:
            self.manager.export_profiles(Path(path))

    def _import_profiles(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import profiles", "", "JSON/YAML (*.json *.yml)")
        if path:
            self.manager.import_profiles(Path(path))
            self._refresh_profiles()

    def _toggle_theme(self) -> None:
        palette = QtWidgets.QApplication.instance().palette()
        color_role = QtGui.QPalette.ColorRole.Window
        current_color = palette.color(color_role)
        if current_color.value() < 128:
            QtWidgets.QApplication.instance().setStyle("Fusion")
            palette = QtGui.QPalette()
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#ffffff"))
            palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#202020"))
        else:
            QtWidgets.QApplication.instance().setStyle("Fusion")
            palette = QtGui.QPalette()
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#1e1e1e"))
            palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#f0f0f0"))
        QtWidgets.QApplication.instance().setPalette(palette)

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

