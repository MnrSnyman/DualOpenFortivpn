"""Main application window implementing the VPN manager UI."""

from __future__ import annotations

from typing import Dict, Optional

from core.qt_compat import (
    QAction,
    QHBoxLayout,
    QHeaderView,
    QMainWindow,
    QMessageBox,
    QObject,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QWidget,
    Qt,
    QT_VERSION,
    Signal,
)

from config.keyring_manager import KeyringManager
from config.manager import ConfigManager
from core.browser_detection import BrowserInfo, detect_browsers
from core.logging_manager import get_logging_manager
from core.privilege import PrivilegeManager
from core.routing import RouteManager
from core.vpn_profile import VPNProfile
from core.vpn_session import VPNSession
from gui.dialogs import CredentialDialog, ProfileDialog, SudoPasswordDialog
from gui.styles import DARK_THEME_QSS


class _LogEmitter(QObject):
    log_received = Signal(str)


class MainWindow(QMainWindow):
    """High-level orchestration of the GUI and VPN session management."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenFortiVPN Manager")
        self.resize(1200, 720)
        self.setStyleSheet(DARK_THEME_QSS)

        self.config_manager = ConfigManager()
        self.keyring_manager = KeyringManager()
        self.logging_manager = get_logging_manager()
        self.logging_manager.logger.info("Using PyQt version: %s", QT_VERSION)
        self._log_emitter = _LogEmitter()
        self._log_emitter.log_received.connect(self._append_log)
        self._log_listener = lambda message: self._log_emitter.log_received.emit(message)
        self.logging_manager.add_listener(self._log_listener)

        self.browsers = detect_browsers()
        self.browser_catalog: Dict[str, BrowserInfo] = {browser.key: browser for browser in self.browsers}
        self.privilege_manager = PrivilegeManager(self._request_sudo_password)
        self.route_manager = RouteManager(self.privilege_manager)
        self.sessions: Dict[str, VPNSession] = {}
        self.session_status: Dict[str, str] = {}
        self.profile_rows: Dict[str, int] = {}

        if self.privilege_manager.has_pkexec():
            self.logging_manager.logger.info("pkexec detected; using pkexec for privileged operations.")
        else:
            self.logging_manager.logger.info("pkexec not found; sudo fallback will be used.")
        for browser in self.browsers:
            profile_count = len(browser.profiles)
            self.logging_manager.logger.info(
                "Browser available: %s (profiles: %s)",
                browser.name,
                profile_count,
            )

        self._build_ui()
        self._populate_table()
        for entry in self.logging_manager.history():
            self._append_log(entry)

    def _build_ui(self) -> None:
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        add_action = QAction("Add", self)
        add_action.triggered.connect(self._add_profile)
        toolbar.addAction(add_action)

        edit_action = QAction("Edit", self)
        edit_action.triggered.connect(self._edit_profile)
        toolbar.addAction(edit_action)

        remove_action = QAction("Remove", self)
        remove_action.triggered.connect(self._remove_profile)
        toolbar.addAction(remove_action)

        forget_action = QAction("Forget Password", self)
        forget_action.triggered.connect(self._forget_password)
        toolbar.addAction(forget_action)

        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self._populate_table)
        toolbar.addAction(refresh_action)

        central = QWidget()
        central_layout = QHBoxLayout(central)

        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            [
                "Name",
                "Host",
                "Port",
                "Auth",
                "Browser",
                "Profile",
                "Username",
                "Auto-Reconnect",
                "Status",
                "Actions",
            ]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        splitter.addWidget(self.table)

        self.log_viewer = QPlainTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setMaximumBlockCount(2000)
        splitter.addWidget(self.log_viewer)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        central_layout.addWidget(splitter)
        self.setCentralWidget(central)

    def _append_log(self, message: str) -> None:
        self.log_viewer.appendPlainText(message)
        self.log_viewer.verticalScrollBar().setValue(self.log_viewer.verticalScrollBar().maximum())

    def _populate_table(self) -> None:
        self.config_manager.reload()
        profiles = self.config_manager.profiles()
        self.table.setRowCount(0)
        self.profile_rows.clear()
        for profile in profiles:
            self._add_profile_row(profile)

    def _add_profile_row(self, profile: VPNProfile) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.profile_rows[profile.name] = row
        self.table.setItem(row, 0, QTableWidgetItem(profile.name))
        self.table.setItem(row, 1, QTableWidgetItem(profile.host))
        self.table.setItem(row, 2, QTableWidgetItem(str(profile.port)))
        self.table.setItem(row, 3, QTableWidgetItem(profile.auth_type.capitalize()))
        self.table.setItem(row, 4, QTableWidgetItem(self._browser_display(profile.browser)))
        self.table.setItem(row, 5, QTableWidgetItem(profile.browser_profile or ""))
        self.table.setItem(row, 6, QTableWidgetItem(profile.username or ""))
        self.table.setItem(row, 7, QTableWidgetItem("Yes" if profile.auto_reconnect else "No"))
        status_text = self.session_status.get(profile.name, "Idle")
        status_item = QTableWidgetItem(status_text)
        self.table.setItem(row, 8, status_item)
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        connect_button = QPushButton("Connect")
        connect_button.clicked.connect(lambda checked=False, name=profile.name: self._connect_profile(name))
        disconnect_button = QPushButton("Disconnect")
        disconnect_button.clicked.connect(lambda checked=False, name=profile.name: self._disconnect_profile(name))
        layout.addWidget(connect_button)
        layout.addWidget(disconnect_button)
        widget.setLayout(layout)
        self.table.setCellWidget(row, 9, widget)

    def _browser_display(self, key: str) -> str:
        info = self.browser_catalog.get(key)
        return info.name if info else key

    def _find_profile(self, name: str) -> Optional[VPNProfile]:
        return self.config_manager.get(name)

    def _add_profile(self) -> None:
        dialog = ProfileDialog(self.browsers, parent=self)
        profile = dialog.get_profile()
        if not profile:
            return
        if self.config_manager.get(profile.name):
            QMessageBox.warning(self, "Duplicate", "A profile with this name already exists.")
            return
        self.config_manager.upsert(profile)
        self._populate_table()

    def _edit_profile(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select", "Select a profile to edit.")
            return
        name = self.table.item(row, 0).text()
        profile = self.config_manager.get(name)
        if not profile:
            return
        if name in self.sessions:
            QMessageBox.warning(self, "Active", "Disconnect the VPN before editing this profile.")
            return
        dialog = ProfileDialog(self.browsers, profile=profile, parent=self)
        updated = dialog.get_profile()
        if not updated:
            return
        if updated.name != name and self.config_manager.get(updated.name):
            QMessageBox.warning(self, "Duplicate", "A profile with this name already exists.")
            return
        if updated.name != name:
            self.config_manager.remove(name)
            self.keyring_manager.delete_password(name)
            self.session_status.pop(name, None)
            self.sessions.pop(name, None)
        self.config_manager.upsert(updated)
        self._populate_table()

    def _remove_profile(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select", "Select a profile to remove.")
            return
        name = self.table.item(row, 0).text()
        if QMessageBox.question(self, "Confirm", f"Remove profile '{name}'?") != QMessageBox.StandardButton.Yes:
            return
        if name in self.sessions:
            self._disconnect_profile(name)
        self.config_manager.remove(name)
        self.keyring_manager.delete_password(name)
        self.session_status.pop(name, None)
        self._populate_table()

    def _forget_password(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select", "Select a profile.")
            return
        name = self.table.item(row, 0).text()
        if self.keyring_manager.delete_password(name):
            QMessageBox.information(self, "Keyring", "Password removed from keyring.")
        else:
            QMessageBox.warning(self, "Keyring", "No stored password or keyring unavailable.")

    def _connect_profile(self, name: str) -> None:
        if name in self.sessions:
            QMessageBox.information(self, "Active", "Connection already active.")
            return
        profile = self.config_manager.get(name)
        if not profile:
            QMessageBox.warning(self, "Missing", "Profile not found.")
            return
        credentials = None
        if profile.auth_type.lower() == "password":
            stored = self.keyring_manager.load_password(profile.name)
            if stored:
                credentials = stored
                profile.username = stored[0]
                self.config_manager.upsert(profile)
                self._update_table_username(profile.name, profile.username)
            else:
                dialog = CredentialDialog(profile.username or "", self)
                result = dialog.get_credentials()
                if not result:
                    return
                username, password, remember = result
                credentials = (username, password)
                profile.username = username
                if remember:
                    if not self.keyring_manager.save_password(profile.name, username, password):
                        QMessageBox.warning(self, "Keyring", "Failed to store password in keyring.")
                self.config_manager.upsert(profile)
                self._update_table_username(profile.name, username)
        if not self.privilege_manager.has_pkexec():
            try:
                self.privilege_manager.ensure_password_cached()
            except RuntimeError as exc:
                QMessageBox.warning(self, "Privilege", str(exc))
                return
        session = VPNSession(profile, self.privilege_manager, self.route_manager, self.browser_catalog, credentials)
        session.status_changed.connect(lambda status, profile=name: self._update_status(profile, status))
        session.log_line.connect(lambda message, profile=name: self._log_session_output(profile, message))
        session.connected.connect(lambda profile_name: self._on_connected(profile_name))
        session.disconnected.connect(lambda profile_name: self._on_disconnected(profile_name))
        self.sessions[name] = session
        session.start()
        self._update_status(name, "Connecting")

    def _disconnect_profile(self, name: str) -> None:
        session = self.sessions.get(name)
        if session:
            session.stop()
            session.wait(5000)
            del self.sessions[name]
            self._update_status(name, "Disconnected")
            if not self.sessions and not self.privilege_manager.cache_allowed():
                self.privilege_manager.clear_cached_password()

    def _log_session_output(self, profile: str, message: str) -> None:
        self.logging_manager.logger.info("[%s] %s", profile, message)

    def _on_connected(self, name: str) -> None:
        self._update_status(name, "Connected")

    def _on_disconnected(self, name: str) -> None:
        if name in self.sessions:
            session = self.sessions.pop(name)
            session.wait(1000)
        self._update_status(name, "Disconnected")
        if not self.sessions and not self.privilege_manager.cache_allowed():
            self.privilege_manager.clear_cached_password()

    def _update_status(self, name: str, status: str) -> None:
        self.session_status[name] = status
        row = self.profile_rows.get(name)
        if row is not None and row < self.table.rowCount():
            status_item = self.table.item(row, 8)
            if status_item:
                status_item.setText(status)
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text() == name:
                status_item = self.table.item(row, 8)
                if status_item:
                    status_item.setText(status)
                self.profile_rows[name] = row
                break

    def _update_table_username(self, name: str, username: str) -> None:
        row = self.profile_rows.get(name)
        if row is not None and row < self.table.rowCount():
            username_item = self.table.item(row, 6)
            if username_item:
                username_item.setText(username)
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text() == name:
                username_item = self.table.item(row, 6)
                if username_item:
                    username_item.setText(username)
                self.profile_rows[name] = row
                break

    def _request_sudo_password(self):
        dialog = SudoPasswordDialog(self)
        result = dialog.get_password()
        return result

    def closeEvent(self, event) -> None:  # type: ignore[override]
        for session in list(self.sessions.values()):
            session.stop()
            session.wait(5000)
        self.sessions.clear()
        self.logging_manager.remove_listener(self._log_listener)
        if not self.privilege_manager.cache_allowed():
            self.privilege_manager.clear_cached_password()
        super().closeEvent(event)
