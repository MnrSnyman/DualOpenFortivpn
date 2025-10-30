"""Compatibility helpers for running the GUI on either PyQt6 or PyQt5."""

from __future__ import annotations

from types import SimpleNamespace

QT_VERSION = 6

try:
    # Prefer PyQt6 when available to take advantage of the latest Qt APIs.
    from PyQt6 import QtCore, QtGui, QtWidgets  # type: ignore
    from PyQt6.QtGui import QAction  # type: ignore
except ImportError:  # pragma: no cover - executed only when PyQt6 missing
    # Fall back to PyQt5 so the application still works on distributions
    # where PyQt6 is not packaged yet (e.g. Fedora long term releases).
    from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore
    from PyQt5.QtWidgets import QAction  # type: ignore

    QT_VERSION = 5

# Re-export the modules and commonly used callables so all GUI modules can
# simply ``from core.qt_compat import ...`` and remain agnostic to the Qt version.
Qt = QtCore.Qt
Signal = QtCore.pyqtSignal
Slot = QtCore.pyqtSlot
QObject = QtCore.QObject
QThread = QtCore.QThread

QApplication = QtWidgets.QApplication
QMainWindow = QtWidgets.QMainWindow
QMessageBox = QtWidgets.QMessageBox
QToolBar = QtWidgets.QToolBar
QWidget = QtWidgets.QWidget
QHBoxLayout = QtWidgets.QHBoxLayout
QSplitter = QtWidgets.QSplitter
QPlainTextEdit = QtWidgets.QPlainTextEdit
QTableWidget = QtWidgets.QTableWidget
QTableWidgetItem = QtWidgets.QTableWidgetItem
QHeaderView = QtWidgets.QHeaderView
QPushButton = QtWidgets.QPushButton
QSizePolicy = QtWidgets.QSizePolicy

QDialog = QtWidgets.QDialog
QDialogButtonBox = QtWidgets.QDialogButtonBox
QComboBox = QtWidgets.QComboBox
QCheckBox = QtWidgets.QCheckBox
QFormLayout = QtWidgets.QFormLayout
QLabel = QtWidgets.QLabel
QLineEdit = QtWidgets.QLineEdit
QSpinBox = QtWidgets.QSpinBox
QTextEdit = QtWidgets.QTextEdit
QVBoxLayout = QtWidgets.QVBoxLayout

# When running on PyQt5 provide the modern attribute names introduced with PyQt6
# so the rest of the code can use a unified API surface.
if QT_VERSION == 5:  # pragma: no cover - only exercised on PyQt5 systems
    if not hasattr(Qt, "Orientation"):
        Qt.Orientation = SimpleNamespace(  # type: ignore[attr-defined]
            Horizontal=Qt.Horizontal,
            Vertical=Qt.Vertical,
        )
    if not hasattr(Qt, "ToolBarArea"):
        Qt.ToolBarArea = SimpleNamespace(  # type: ignore[attr-defined]
            TopToolBarArea=Qt.TopToolBarArea,
            LeftToolBarArea=Qt.LeftToolBarArea,
            RightToolBarArea=Qt.RightToolBarArea,
            BottomToolBarArea=Qt.BottomToolBarArea,
        )

    if not hasattr(QHeaderView, "ResizeMode"):
        QHeaderView.ResizeMode = SimpleNamespace(  # type: ignore[attr-defined]
            Interactive=QHeaderView.Interactive,
            Stretch=QHeaderView.Stretch,
            ResizeToContents=QHeaderView.ResizeToContents,
        )

    if not hasattr(QTableWidget, "SelectionBehavior"):
        QTableWidget.SelectionBehavior = QtWidgets.QAbstractItemView.SelectionBehavior  # type: ignore[attr-defined]
    if not hasattr(QTableWidget, "EditTrigger"):
        QTableWidget.EditTrigger = QtWidgets.QAbstractItemView.EditTrigger  # type: ignore[attr-defined]

    if not hasattr(QDialog, "DialogCode"):
        QDialog.DialogCode = SimpleNamespace(  # type: ignore[attr-defined]
            Accepted=QDialog.Accepted,
            Rejected=QDialog.Rejected,
        )

    if not hasattr(QDialogButtonBox, "StandardButton"):
        QDialogButtonBox.StandardButton = SimpleNamespace(  # type: ignore[attr-defined]
            Ok=QDialogButtonBox.Ok,
            Cancel=QDialogButtonBox.Cancel,
        )

    if not hasattr(QLineEdit, "EchoMode"):
        QLineEdit.EchoMode = SimpleNamespace(  # type: ignore[attr-defined]
            Normal=QLineEdit.Normal,
            Password=QLineEdit.Password,
        )

    if not hasattr(QMessageBox, "StandardButton"):
        QMessageBox.StandardButton = SimpleNamespace(  # type: ignore[attr-defined]
            Ok=QMessageBox.Ok,
            Cancel=QMessageBox.Cancel,
            Yes=QMessageBox.Yes,
            No=QMessageBox.No,
        )

    if not hasattr(QSizePolicy, "Policy"):
        QSizePolicy.Policy = SimpleNamespace(  # type: ignore[attr-defined]
            Fixed=QSizePolicy.Fixed,
            Preferred=QSizePolicy.Preferred,
            Expanding=QSizePolicy.Expanding,
            Minimum=QSizePolicy.Minimum,
        )

__all__ = [
    "QT_VERSION",
    "Qt",
    "Signal",
    "Slot",
    "QObject",
    "QThread",
    "QApplication",
    "QMainWindow",
    "QMessageBox",
    "QToolBar",
    "QWidget",
    "QHBoxLayout",
    "QSplitter",
    "QPlainTextEdit",
    "QTableWidget",
    "QTableWidgetItem",
    "QHeaderView",
    "QPushButton",
    "QSizePolicy",
    "QDialog",
    "QDialogButtonBox",
    "QComboBox",
    "QCheckBox",
    "QFormLayout",
    "QLabel",
    "QLineEdit",
    "QSpinBox",
    "QTextEdit",
    "QVBoxLayout",
    "QAction",
]
