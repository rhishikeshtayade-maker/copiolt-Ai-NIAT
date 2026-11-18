"""Main PySide6 application window for the NIAT CodePilot Worker."""

import asyncio
import io
import time
from typing import Optional
from PySide6.QtCore import QByteArray, QDateTime, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.common.config import settings
from src.common.constants import WorkerCommand, WorkerStatus
from src.common.logger import get_logger
from src.desktop.components.preview_widget import ScreenPreviewWidget
from src.desktop.components.status_bar import ConnectionStatusBar
from src.worker.capture import ScreenCaptureService
from src.worker.client import WorkerClient

logger = get_logger("Desktop.App")


class HeartbeatWorkerThread(QThread):
    """Background thread sending periodic heartbeats to avoid blocking the Qt GUI."""

    heartbeat_success = Signal(int, float)  # count, latency_ms
    heartbeat_error = Signal(str)
    command_received = Signal(str)

    def __init__(self, client: WorkerClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.running = True
        self.count = 0

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._heartbeat_loop())
        finally:
            loop.close()

    async def _heartbeat_loop(self) -> None:
        interval = settings.heartbeat_interval_seconds
        while self.running:
            if self.client.is_registered:
                t0 = time.time()
                try:
                    resp = await self.client.send_heartbeat()
                    latency = (time.time() - t0) * 1000.0
                    self.count += 1
                    self.heartbeat_success.emit(self.count, latency)
                    if resp.command != WorkerCommand.NONE:
                        self.command_received.emit(resp.command.value)
                except Exception as e:
                    self.heartbeat_error.emit(str(e))

            for _ in range(int(interval * 10)):
                if not self.running:
                    break
                await asyncio.sleep(0.1)

    def stop(self) -> None:
        self.running = False


class MainWindow(QMainWindow):
    """Central graphical window for the NIAT CodePilot Worker laptop."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NIAT CodePilot - Distributed Worker & Screen Capture")
        self.resize(1000, 720)

        # Worker services
        self.capture_service = ScreenCaptureService(worker_id=settings.worker_id)
        self.worker_client = WorkerClient(
            worker_id=settings.worker_id,
            worker_name=settings.worker_name,
            controller_url=settings.controller_url,
            on_command_received=self.handle_controller_command,
        )

        self.heartbeat_thread: Optional[HeartbeatWorkerThread] = None

        # Preview refresh timer
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(2000)  # Capture preview every 2s when active
        self.preview_timer.timeout.connect(self.on_auto_preview_tick)

        self._init_ui()
        self._apply_dark_styles()

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 10)

        # 1. Config & Connection Header
        config_group = QGroupBox("Worker & Controller Configuration")
        config_layout = QHBoxLayout(config_group)

        self.worker_id_edit = QLineEdit(settings.worker_id)
        self.worker_name_edit = QLineEdit(settings.worker_name)
        self.controller_url_edit = QLineEdit(settings.controller_url)

        form1 = QFormLayout()
        form1.addRow("Worker ID:", self.worker_id_edit)
        config_layout.addLayout(form1)

        form2 = QFormLayout()
        form2.addRow("Worker Name:", self.worker_name_edit)
        config_layout.addLayout(form2)

        form3 = QFormLayout()
        form3.addRow("Controller URL:", self.controller_url_edit)
        config_layout.addLayout(form3)

        main_layout.addWidget(config_group)

        # 2. Explicit Permission & Policy Verification Box
        permission_group = QGroupBox("Privacy, Safety & User Permission (Strict Policy)")
        perm_layout = QVBoxLayout(permission_group)

        self.consent_checkbox = QCheckBox(
            "I EXPLICITLY GRANT PERMISSION for NIAT CodePilot to capture my screen for coding guidance and analysis."
        )
        self.consent_checkbox.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: #4CAF50;"
        )
        self.consent_checkbox.toggled.connect(self.on_consent_toggled)
        perm_layout.addWidget(self.consent_checkbox)

        policy_text = QLabel(
            "Security Policy: No student passwords stored | No automatic portal submissions "
            "| Student approval required for all actions | Screen capture is never silent."
        )
        policy_text.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        perm_layout.addWidget(policy_text)

        main_layout.addWidget(permission_group)

        # 3. Main Center Split (Left: Controls & Logs, Right: Preview)
        content_layout = QHBoxLayout()

        # Left Column: Buttons & Logs
        left_column = QVBoxLayout()
        controls_group = QGroupBox("Execution Controls")
        btn_layout = QVBoxLayout(controls_group)

        self.start_btn = QPushButton("▶  Start Worker & Capture")
        self.start_btn.setEnabled(False)  # Requires consent
        self.start_btn.setFixedHeight(42)
        self.start_btn.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; font-size: 13px; border-radius: 4px;"
        )
        self.start_btn.clicked.connect(self.on_start_clicked)
        btn_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹  Stop Worker")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setFixedHeight(42)
        self.stop_btn.setStyleSheet(
            "background-color: #555555; color: white; font-weight: bold; font-size: 13px; border-radius: 4px;"
        )
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        btn_layout.addWidget(self.stop_btn)

        self.preview_btn = QPushButton("📷  Capture Single Preview")
        self.preview_btn.setEnabled(False)
        self.preview_btn.setFixedHeight(36)
        self.preview_btn.setStyleSheet(
            "background-color: #1976d2; color: white; font-weight: bold; border-radius: 4px;"
        )
        self.preview_btn.clicked.connect(self.on_single_preview_clicked)
        btn_layout.addWidget(self.preview_btn)

        self.emergency_btn = QPushButton("🚨  EMERGENCY STOP")
        self.emergency_btn.setFixedHeight(48)
        self.emergency_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #d32f2f;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border-radius: 4px;
                border: 2px solid #ff5252;
            }
            QPushButton:hover {
                background-color: #b71c1c;
            }
            """
        )
        self.emergency_btn.clicked.connect(self.on_emergency_stop_clicked)
        btn_layout.addWidget(self.emergency_btn)

        left_column.addWidget(controls_group)

        # Log box
        log_group = QGroupBox("Activity & Security Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "background-color: #121212; color: #cccccc; font-family: Consolas, monospace; font-size: 11px;"
        )
        log_layout.addWidget(self.log_text)
        left_column.addWidget(log_group)

        content_layout.addLayout(left_column, stretch=4)

        # Right Column: Screen Preview
        right_column = QVBoxLayout()
        preview_group = QGroupBox("Live Screen Capture Preview")
        preview_layout = QVBoxLayout(preview_group)

        self.preview_widget = ScreenPreviewWidget(self)
        preview_layout.addWidget(self.preview_widget)

        self.preview_info_label = QLabel("Frame status: Inactive")
        self.preview_info_label.setStyleSheet("color: #888888; font-size: 11px;")
        preview_layout.addWidget(self.preview_info_label)

        right_column.addWidget(preview_group)
        content_layout.addLayout(right_column, stretch=6)

        main_layout.addLayout(content_layout)

        # 4. Status Bar
        self.status_bar = ConnectionStatusBar(self)
        main_layout.addWidget(self.status_bar)

        self.append_log("NIAT CodePilot Worker initialized. Awaiting explicit user consent.")

    def _apply_dark_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #1e1e1e;
            }
            QGroupBox {
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                margin-top: 12px;
                font-weight: bold;
                color: #e0e0e0;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QLineEdit {
                background-color: #2d2d2d;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                color: #ffffff;
                padding: 4px 8px;
            }
            QLabel {
                color: #e0e0e0;
            }
            """
        )

    def append_log(self, text: str) -> None:
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.log_text.append(f"[{timestamp}] {text}")

    def on_consent_toggled(self, checked: bool) -> None:
        """Handle explicit permission checkbox toggle."""
        self.capture_service.set_user_permission(checked)
        self.worker_client.set_permission_active(checked)
        self.status_bar.set_permission_status(checked)

        if checked:
            self.start_btn.setEnabled(True)
            self.preview_btn.setEnabled(True)
            self.preview_widget.set_placeholder("Ready to capture. Click 'Start' or 'Capture Single Preview'.")
            self.append_log("User GRANTED explicit screen capture permission.")
        else:
            self.start_btn.setEnabled(False)
            self.preview_btn.setEnabled(False)
            if self.capture_service.has_permission:
                self.on_stop_clicked()
            self.preview_widget.set_placeholder("Screen Capture Inactive\n(Explicit user consent required)")
            self.append_log("User REVOKED screen capture permission.")

    def on_start_clicked(self) -> None:
        """Start worker registration, screen capture engine, and heartbeat loop."""
        if not self.consent_checkbox.isChecked():
            QMessageBox.warning(
                self,
                "Permission Required",
                "Explicit user permission must be granted before starting screen capture.",
            )
            return

        # Update client configurations from inputs
        self.worker_client.worker_id = self.worker_id_edit.text().strip()
        self.worker_client.worker_name = self.worker_name_edit.text().strip()
        self.worker_client.controller_url = self.controller_url_edit.text().strip()
        self.capture_service.worker_id = self.worker_client.worker_id

        self.append_log(f"Registering with controller at {self.worker_client.controller_url}...")

        # Register synchronously or via coroutine runner
        loop = asyncio.new_event_loop()
        try:
            resp = loop.run_until_complete(self.worker_client.register(explicit_consent=True))
            self.append_log(f"Registration acknowledged: {resp.message}")
            self.status_bar.set_connection_status(True, f"ID: {resp.worker_id}")
        except Exception as e:
            self.append_log(f"Registration error: {e}")
            self.status_bar.set_connection_status(False, "Registration Failed")
            QMessageBox.critical(
                self,
                "Registration Failed",
                f"Could not connect to controller:\n{e}\n\nPlease check Controller URL and ensure the central controller is running.",
            )
            loop.close()
            return
        finally:
            loop.close()

        # Start capture service
        try:
            self.capture_service.start()
        except Exception as e:
            self.append_log(f"Error starting capture service: {e}")
            return

        # Start heartbeats
        if self.heartbeat_thread is None or not self.heartbeat_thread.isRunning():
            self.heartbeat_thread = HeartbeatWorkerThread(self.worker_client, self)
            self.heartbeat_thread.heartbeat_success.connect(self.on_heartbeat_success)
            self.heartbeat_thread.heartbeat_error.connect(self.on_heartbeat_error)
            self.heartbeat_thread.command_received.connect(self.on_command_from_thread)
            self.heartbeat_thread.start()

        # Start auto preview timer
        self.preview_timer.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker_id_edit.setEnabled(False)
        self.controller_url_edit.setEnabled(False)

        self.append_log("Worker started successfully: Screen capture and heartbeats active.")

    def on_stop_clicked(self) -> None:
        """Stop worker operations gracefully."""
        self.preview_timer.stop()

        if self.heartbeat_thread and self.heartbeat_thread.isRunning():
            self.heartbeat_thread.stop()
            self.heartbeat_thread.wait(2000)

        self.capture_service.stop()
        self.worker_client.status = WorkerStatus.PAUSED

        self.start_btn.setEnabled(self.consent_checkbox.isChecked())
        self.stop_btn.setEnabled(False)
        self.worker_id_edit.setEnabled(True)
        self.controller_url_edit.setEnabled(True)

        self.preview_widget.set_placeholder("Screen Capture Paused")
        self.preview_info_label.setText("Frame status: Paused")
        self.append_log("Worker paused: Screen capture and heartbeats halted.")

    def on_emergency_stop_clicked(self) -> None:
        """Immediately abort all captures, revoke permissions, and halt."""
        self.preview_timer.stop()
        self.capture_service.emergency_halt()

        if self.heartbeat_thread and self.heartbeat_thread.isRunning():
            self.heartbeat_thread.stop()
            self.heartbeat_thread.wait(1000)

        self.worker_client.status = WorkerStatus.EMERGENCY_STOPPED
        self.consent_checkbox.setChecked(False)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)

        self.preview_widget.set_placeholder("EMERGENCY STOP ACTIVATED\nAll screen capture instantly terminated.", is_emergency=True)
        self.preview_info_label.setText("Status: EMERGENCY STOPPED")
        self.status_bar.set_permission_status(False)
        self.status_bar.set_connection_status(False, "Emergency Halted")

        self.append_log("EMERGENCY STOP TRIGGERED. All permissions and capture loops terminated immediately.")

    def on_single_preview_clicked(self) -> None:
        """Capture and display a single frame on-demand."""
        try:
            png_bytes, meta = self.capture_service.capture_frame_bytes()
            qimage = QImage.fromData(QByteArray(png_bytes))
            pixmap = QPixmap.fromImage(qimage)
            self.preview_widget.update_frame(pixmap, f"Frame: {meta.width}x{meta.height} ({meta.frame_size_bytes} bytes)")
            self.preview_info_label.setText(
                f"Resolution: {meta.width}x{meta.height} | Size: {meta.frame_size_bytes / 1024:.1f} KB | Verified: Explicit Consent"
            )
            self.append_log(f"Captured single frame preview ({meta.width}x{meta.height}, {meta.frame_size_bytes} bytes)")
        except PermissionError as pe:
            QMessageBox.warning(self, "Permission Denied", str(pe))
            self.append_log(f"Permission error: {pe}")
        except Exception as e:
            self.append_log(f"Preview capture failed: {e}")

    def on_auto_preview_tick(self) -> None:
        """Periodically grab a preview frame when worker is actively running."""
        if not self.capture_service.has_permission:
            return
        try:
            png_bytes, meta = self.capture_service.capture_frame_bytes()
            qimage = QImage.fromData(QByteArray(png_bytes))
            pixmap = QPixmap.fromImage(qimage)
            self.preview_widget.update_frame(pixmap)
            self.preview_info_label.setText(
                f"Resolution: {meta.width}x{meta.height} | Size: {meta.frame_size_bytes / 1024:.1f} KB | Active Preview"
            )
        except Exception as e:
            self.append_log(f"Auto preview tick error: {e}")

    def on_heartbeat_success(self, count: int, latency: float) -> None:
        self.status_bar.update_heartbeat_count(count, latency)

    def on_heartbeat_error(self, error: str) -> None:
        self.append_log(f"Heartbeat dispatch error: {error}")
        self.status_bar.set_connection_status(False, "Error")

    def on_command_from_thread(self, command: str) -> None:
        self.append_log(f"Controller command received: {command}")
        if command == WorkerCommand.EMERGENCY_STOP.value:
            self.on_emergency_stop_clicked()
        elif command == WorkerCommand.STOP.value:
            self.on_stop_clicked()

    def handle_controller_command(self, cmd: WorkerCommand) -> None:
        if cmd == WorkerCommand.EMERGENCY_STOP:
            self.on_emergency_stop_clicked()

    def closeEvent(self, event) -> None:
        """Cleanly shutdown threads on window close."""
        self.on_stop_clicked()
        event.accept()
