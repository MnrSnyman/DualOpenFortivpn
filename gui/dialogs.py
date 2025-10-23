"""Reusable dialogs used across the GUI."""

from __future__ import annotations

from typing import List, Optional, Tuple

from core.qt_compat import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.browser_detection import BrowserInfo
from core.vpn_profile import VPNProfile


class ProfileDialog(QDialog):
    """Dialog allowing the user to add or edit VPN profiles."""

    def __init__(self, browsers: List[BrowserInfo], profile: Optional[VPNProfile] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VPN Profile")
        self.setModal(True)
        self._browsers = browsers
        self._profile = profile
        self._build_ui()
        if profile:
            self._populate(profile)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.host_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(443)
        self.auth_combo = QComboBox()
        self.auth_combo.addItems(["password", "saml"])
        self.auth_combo.currentTextChanged.connect(self._on_auth_changed)
        self.custom_saml_check = QCheckBox("Use custom SAML port")
        self.saml_port_spin = QSpinBox()
        self.saml_port_spin.setRange(1, 65535)
        self.saml_port_spin.setValue(8020)
        self.saml_port_spin.setEnabled(False)
        self.custom_saml_check.toggled.connect(self._update_saml_port_state)
        saml_port_container = QWidget()
        saml_layout = QHBoxLayout(saml_port_container)
        saml_layout.setContentsMargins(0, 0, 0, 0)
        saml_layout.addWidget(self.custom_saml_check)
        saml_layout.addWidget(self.saml_port_spin)
        self.browser_combo = QComboBox()
        for browser in self._browsers:
            self.browser_combo.addItem(browser.name, browser.key)
        self.profile_combo = QComboBox()
        self.username_edit = QLineEdit()
        self.auto_reconnect_check = QCheckBox("Auto reconnect")
        self.routes_edit = QTextEdit()
        self.routes_edit.setPlaceholderText("Enter one route per line (CIDR/IP/URL)")

        form.addRow("Name", self.name_edit)
        form.addRow("Host", self.host_edit)
        form.addRow("Port", self.port_spin)
        form.addRow("Auth Type", self.auth_combo)
        form.addRow("SAML Port", saml_port_container)
        form.addRow("Browser", self.browser_combo)
        form.addRow("Browser Profile", self.profile_combo)
        form.addRow("Username", self.username_edit)
        form.addRow("Auto Reconnect", self.auto_reconnect_check)
        form.addRow("Routes", self.routes_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.browser_combo.currentIndexChanged.connect(self._update_profile_combo)
        self._update_profile_combo()
        self._on_auth_changed(self.auth_combo.currentText())

    def _populate(self, profile: VPNProfile) -> None:
        self.name_edit.setText(profile.name)
        self.host_edit.setText(profile.host)
        self.port_spin.setValue(profile.port)
        index = self.auth_combo.findText(profile.auth_type.lower())
        if index >= 0:
            self.auth_combo.setCurrentIndex(index)
        if profile.saml_port:
            self.custom_saml_check.setChecked(True)
            self.saml_port_spin.setValue(profile.saml_port)
        else:
            self.custom_saml_check.setChecked(False)
        browser_index = self.browser_combo.findData(profile.browser)
        if browser_index >= 0:
            self.browser_combo.setCurrentIndex(browser_index)
        if profile.browser_profile:
            idx = self.profile_combo.findText(profile.browser_profile)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        if profile.username:
            self.username_edit.setText(profile.username)
        self.auto_reconnect_check.setChecked(profile.auto_reconnect)
        if profile.routes:
            self.routes_edit.setPlainText("\n".join(profile.routes))

    def _update_profile_combo(self) -> None:
        self.profile_combo.clear()
        browser_key = self.browser_combo.currentData()
        for browser in self._browsers:
            if browser.key == browser_key:
                self.profile_combo.addItem("(Default)", "")
                for profile in browser.profiles:
                    self.profile_combo.addItem(profile, profile)
                break

    def _on_auth_changed(self, value: str) -> None:
        is_saml = value.lower() == "saml"
        self.custom_saml_check.setEnabled(is_saml)
        self.browser_combo.setEnabled(is_saml)
        self.profile_combo.setEnabled(is_saml)
        self.username_edit.setEnabled(not is_saml)
        if not is_saml:
            self.custom_saml_check.setChecked(False)
        self._update_saml_port_state()

    def _update_saml_port_state(self) -> None:
        use_custom = (
            self.auth_combo.currentText().lower() == "saml"
            and self.custom_saml_check.isChecked()
        )
        self.saml_port_spin.setEnabled(use_custom)

    def _on_accept(self) -> None:
        if not self.name_edit.text().strip() or not self.host_edit.text().strip():
            QMessageBox.warning(self, "Validation", "Name and host are required.")
            return
        self.accept()

    def get_profile(self) -> Optional[VPNProfile]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        routes = [route.strip() for route in self.routes_edit.toPlainText().splitlines() if route.strip()]
        auth_type = self.auth_combo.currentText().lower()
        saml_port = None
        if auth_type == "saml" and self.custom_saml_check.isChecked():
            saml_port = self.saml_port_spin.value()
        profile = VPNProfile(
            name=self.name_edit.text().strip(),
            host=self.host_edit.text().strip(),
            port=self.port_spin.value(),
            auth_type=auth_type,
            saml_port=saml_port,
            browser=self.browser_combo.currentData(),
            browser_profile=self.profile_combo.currentData() or None,
            username=self.username_edit.text().strip() if auth_type != "saml" else None,
            auto_reconnect=self.auto_reconnect_check.isChecked(),
            routes=routes,
        )
        return profile


class CredentialDialog(QDialog):
    """Prompt for username and password when not stored."""

    def __init__(self, default_username: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Credentials Required")
        self.setModal(True)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.username_edit = QLineEdit(default_username)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.remember_check = QCheckBox("Save password to keyring")
        form.addRow("Username", self.username_edit)
        form.addRow("Password", self.password_edit)
        form.addRow("Remember", self.remember_check)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.username_edit.text().strip() or not self.password_edit.text():
            QMessageBox.warning(self, "Validation", "Username and password are required.")
            return
        self.accept()

    def get_credentials(self) -> Optional[Tuple[str, str, bool]]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return (
            self.username_edit.text().strip(),
            self.password_edit.text(),
            self.remember_check.isChecked(),
        )


class SudoPasswordDialog(QDialog):
    """Prompt for sudo password when pkexec is unavailable."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Administrator access required")
        layout = QVBoxLayout(self)
        label = QLabel(
            "Enter your sudo password to run openfortivpn. The password will be reused "
            "until you close OpenFortiVPN Manager."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.password_edit.text():
            QMessageBox.warning(self, "Validation", "Password is required.")
            return
        self.accept()

    def get_password(self) -> Optional[Tuple[str, bool]]:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return self.password_edit.text(), True
