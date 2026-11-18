"""Status indicator widget for the desktop application."""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt


class ConnectionStatusBar(QFrame):
    """Bottom status bar with visual pill indicators for connection and permission status."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            """
            ConnectionStatusBar {
                background-color: #252526;
                border-top: 1px solid #3c3c3c;
                padding: 4px;
            }
            QLabel {
                color: #cccccc;
                font-size: 12px;
            }
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)

        self.conn_label = QLabel("Controller: Disconnected")
        self.conn_label.setStyleSheet("color: #ffaa00; font-weight: bold;")
        layout.addWidget(self.conn_label)

        layout.addSpacing(20)

        self.permission_label = QLabel("Permission: Revoked")
        self.permission_label.setStyleSheet("color: #ff6666; font-weight: bold;")
        layout.addWidget(self.permission_label)

        layout.addSpacing(20)

        self.heartbeat_label = QLabel("Heartbeats: 0")
        layout.addWidget(self.heartbeat_label)

        layout.addStretch()

        self.time_label = QLabel("Ready")
        layout.addWidget(self.time_label)

    def set_connection_status(self, connected: bool, message: str = "") -> None:
        if connected:
            self.conn_label.setText(f"Controller: Connected ({message})" if message else "Controller: Connected")
            self.conn_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self.conn_label.setText(f"Controller: Disconnected ({message})" if message else "Controller: Disconnected")
            self.conn_label.setStyleSheet("color: #f44336; font-weight: bold;")

    def set_reconnecting_status(self, message: str = "") -> None:
        self.conn_label.setText(f"Controller: Reconnecting ({message})" if message else "Controller: Reconnecting...")
        self.conn_label.setStyleSheet("color: #ffaa00; font-weight: bold;")

    def set_permission_status(self, granted: bool) -> None:
        if granted:
            self.permission_label.setText("Permission: Active")
            self.permission_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self.permission_label.setText("Permission: Revoked")
            self.permission_label.setStyleSheet("color: #ff6666; font-weight: bold;")

    def update_heartbeat_count(self, count: int, latency_ms: float = 0.0) -> None:
        self.heartbeat_label.setText(f"Heartbeats: {count} ({latency_ms:.0f}ms)")
