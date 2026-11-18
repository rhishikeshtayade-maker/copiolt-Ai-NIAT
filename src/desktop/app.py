"""Main PySide6 application window for the NIAT CodePilot Worker."""

import asyncio
import base64
import io
import time
from typing import Optional
from PySide6.QtCore import QByteArray, QDateTime, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.common.config import settings
from src.common.constants import WorkerCommand, WorkerStatus
from src.common.logger import get_logger
from src.common.schemas import CodingAnalysisResult
from src.desktop.components.preview_widget import ScreenPreviewWidget
from src.desktop.components.status_bar import ConnectionStatusBar
from src.worker.ai_engine import AIEngineService
from src.worker.capture import ScreenCaptureService, list_capturable_windows
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


class AIAnalysisThread(QThread):
    """Background thread running async AI analysis without blocking the Qt GUI."""

    analysis_complete = Signal(object)  # CodingAnalysisResult
    analysis_error = Signal(str)
    analysis_started = Signal()

    def __init__(
        self,
        ai_engine: AIEngineService,
        image_base64: str,
        worker_id: str,
        additional_prompt: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.ai_engine = ai_engine
        self.image_base64 = image_base64
        self.worker_id = worker_id
        self.additional_prompt = additional_prompt

    def run(self) -> None:
        self.analysis_started.emit()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                self.ai_engine.analyze_screen(
                    image_base64=self.image_base64,
                    worker_id=self.worker_id,
                    additional_prompt=self.additional_prompt,
                )
            )
            self.analysis_complete.emit(result)
        except Exception as e:
            logger.error(f"AI analysis thread error: {e}")
            self.analysis_error.emit(str(e))
        finally:
            loop.close()


class MainWindow(QMainWindow):
    """Central graphical window for the NIAT CodePilot Worker laptop."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NIAT CodePilot - Distributed Worker & Screen Capture")
        self.resize(1200, 800)

        # Worker services
        self.capture_service = ScreenCaptureService(worker_id=settings.worker_id)
        self.worker_client = WorkerClient(
            worker_id=settings.worker_id,
            worker_name=settings.worker_name,
            controller_url=settings.controller_url,
            on_command_received=self.handle_controller_command,
        )
        self.ai_engine = AIEngineService()

        self.heartbeat_thread: Optional[HeartbeatWorkerThread] = None
        self.ai_thread: Optional[AIAnalysisThread] = None

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
        self.secret_key_edit = QLineEdit(settings.controller_secret_key)
        self.secret_key_edit.setEchoMode(QLineEdit.EchoMode.Password)

        form1 = QFormLayout()
        form1.addRow("Worker ID:", self.worker_id_edit)
        config_layout.addLayout(form1)

        form2 = QFormLayout()
        form2.addRow("Worker Name:", self.worker_name_edit)
        config_layout.addLayout(form2)

        form3 = QFormLayout()
        form3.addRow("Controller URL:", self.controller_url_edit)
        config_layout.addLayout(form3)

        form4 = QFormLayout()
        form4.addRow("Secret Key:", self.secret_key_edit)
        config_layout.addLayout(form4)

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

        # 3. Main Center Splitter (Left: Controls & Logs, Right: Preview + AI)
        content_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Column: Buttons & Logs
        left_widget = QWidget()
        left_column = QVBoxLayout(left_widget)
        left_column.setContentsMargins(0, 0, 0, 0)

        # Screen Capture Target Selection (Window / Region / Full Screen)
        target_group = QGroupBox("Screen Capture Target (Window / Region Selection)")
        target_layout = QVBoxLayout(target_group)

        # Target Mode combo
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Target:"))
        self.target_mode_combo = QComboBox()
        self.target_mode_combo.addItem("Full Screen (Primary Monitor)", "monitor")
        self.target_mode_combo.addItem("Application Window", "window")
        self.target_mode_combo.addItem("Rectangular Region", "region")
        self.target_mode_combo.currentIndexChanged.connect(self.on_target_mode_changed)
        mode_layout.addWidget(self.target_mode_combo, 1)
        target_layout.addLayout(mode_layout)

        # Window selection row
        self.window_selection_widget = QWidget()
        win_layout = QHBoxLayout(self.window_selection_widget)
        win_layout.setContentsMargins(0, 0, 0, 0)
        win_layout.addWidget(QLabel("Window:"))
        self.window_combo = QComboBox()
        self.window_combo.currentIndexChanged.connect(self.on_window_selected)
        win_layout.addWidget(self.window_combo, 1)
        self.refresh_windows_btn = QPushButton("🔄 Refresh")
        self.refresh_windows_btn.setFixedWidth(80)
        self.refresh_windows_btn.clicked.connect(self.refresh_window_list)
        win_layout.addWidget(self.refresh_windows_btn)
        self.window_selection_widget.setVisible(False)
        target_layout.addWidget(self.window_selection_widget)

        # Region selection row
        self.region_selection_widget = QWidget()
        reg_layout = QHBoxLayout(self.region_selection_widget)
        reg_layout.setContentsMargins(0, 0, 0, 0)
        reg_layout.addWidget(QLabel("X:"))
        self.region_x_spin = QSpinBox()
        self.region_x_spin.setRange(0, 10000)
        self.region_x_spin.setValue(0)
        self.region_x_spin.valueChanged.connect(lambda: self._apply_capture_targeting())
        reg_layout.addWidget(self.region_x_spin)

        reg_layout.addWidget(QLabel("Y:"))
        self.region_y_spin = QSpinBox()
        self.region_y_spin.setRange(0, 10000)
        self.region_y_spin.setValue(0)
        self.region_y_spin.valueChanged.connect(lambda: self._apply_capture_targeting())
        reg_layout.addWidget(self.region_y_spin)

        reg_layout.addWidget(QLabel("W:"))
        self.region_w_spin = QSpinBox()
        self.region_w_spin.setRange(10, 10000)
        self.region_w_spin.setValue(1280)
        self.region_w_spin.valueChanged.connect(lambda: self._apply_capture_targeting())
        reg_layout.addWidget(self.region_w_spin)

        reg_layout.addWidget(QLabel("H:"))
        self.region_h_spin = QSpinBox()
        self.region_h_spin.setRange(10, 10000)
        self.region_h_spin.setValue(720)
        self.region_h_spin.valueChanged.connect(lambda: self._apply_capture_targeting())
        reg_layout.addWidget(self.region_h_spin)
        self.region_selection_widget.setVisible(False)
        target_layout.addWidget(self.region_selection_widget)

        # Approved frame status label
        self.approved_frame_label = QLabel("Approved Frame: None (Click 'Capture Single Preview' to prepare)")
        self.approved_frame_label.setStyleSheet("color: #ffb74d; font-size: 11px;")
        target_layout.addWidget(self.approved_frame_label)

        left_column.addWidget(target_group)

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

        # Analyze Screen button
        self.analyze_btn = QPushButton("🧠  Analyze Screen with AI")
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setFixedHeight(42)
        self.analyze_btn.setStyleSheet(
            "background-color: #7b1fa2; color: white; font-weight: bold; font-size: 13px; border-radius: 4px;"
        )
        self.analyze_btn.clicked.connect(self.on_analyze_screen_clicked)
        btn_layout.addWidget(self.analyze_btn)

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

        # Additional prompt input
        prompt_group = QGroupBox("Additional Question (Optional)")
        prompt_layout = QVBoxLayout(prompt_group)
        self.additional_prompt_edit = QLineEdit()
        self.additional_prompt_edit.setPlaceholderText(
            "e.g. 'Explain the time complexity' or 'Show a recursive approach'"
        )
        prompt_layout.addWidget(self.additional_prompt_edit)
        left_column.addWidget(prompt_group)

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

        content_splitter.addWidget(left_widget)

        # Right Column: Tabbed Preview + AI Results
        right_widget = QWidget()
        right_column = QVBoxLayout(right_widget)
        right_column.setContentsMargins(0, 0, 0, 0)

        self.right_tabs = QTabWidget()
        self.right_tabs.setStyleSheet(
            """
            QTabWidget::pane { border: 1px solid #3c3c3c; background: #1e1e1e; }
            QTabBar::tab { background: #2d2d2d; color: #cccccc; padding: 6px 14px; border: 1px solid #3c3c3c; border-bottom: none; }
            QTabBar::tab:selected { background: #1e1e1e; color: #ffffff; }
            QTabBar::tab:hover { background: #3c3c3c; }
            """
        )

        # Tab 1: Screen Preview
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        self.preview_widget = ScreenPreviewWidget(self)
        preview_layout.addWidget(self.preview_widget)
        self.preview_info_label = QLabel("Frame status: Inactive")
        self.preview_info_label.setStyleSheet("color: #888888; font-size: 11px;")
        preview_layout.addWidget(self.preview_info_label)
        self.right_tabs.addTab(preview_tab, "📺 Screen Preview")

        # Tab 2: AI Analysis Results
        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)

        # Loading indicator
        self.ai_progress = QProgressBar()
        self.ai_progress.setRange(0, 0)  # Indeterminate
        self.ai_progress.setVisible(False)
        self.ai_progress.setFixedHeight(6)
        self.ai_progress.setStyleSheet(
            "QProgressBar { border: none; background: #2d2d2d; }"
            "QProgressBar::chunk { background: #7b1fa2; }"
        )
        ai_layout.addWidget(self.ai_progress)

        self.ai_loading_label = QLabel("")
        self.ai_loading_label.setStyleSheet("color: #bb86fc; font-weight: bold; font-size: 12px;")
        self.ai_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ai_layout.addWidget(self.ai_loading_label)

        # Scrollable results area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e1e; }")
        scroll_content = QWidget()
        self.ai_results_layout = QVBoxLayout(scroll_content)
        self.ai_results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Problem Description
        self.problem_title_label = QLabel("")
        self.problem_title_label.setStyleSheet(
            "color: #ffffff; font-size: 16px; font-weight: bold; padding: 4px 0;"
        )
        self.problem_title_label.setWordWrap(True)
        self.ai_results_layout.addWidget(self.problem_title_label)

        self.problem_desc_text = QTextEdit()
        self.problem_desc_text.setReadOnly(True)
        self.problem_desc_text.setMaximumHeight(120)
        self.problem_desc_text.setStyleSheet(
            "background-color: #252526; color: #d4d4d4; border: 1px solid #3c3c3c; "
            "border-radius: 4px; font-size: 12px; padding: 6px;"
        )
        self.ai_results_layout.addWidget(self.problem_desc_text)

        # Explanation
        expl_label = QLabel("Step-by-Step Explanation")
        expl_label.setStyleSheet("color: #4FC3F7; font-weight: bold; font-size: 13px; margin-top: 8px;")
        self.ai_results_layout.addWidget(expl_label)

        self.explanation_text = QTextEdit()
        self.explanation_text.setReadOnly(True)
        self.explanation_text.setMinimumHeight(120)
        self.explanation_text.setStyleSheet(
            "background-color: #252526; color: #d4d4d4; border: 1px solid #3c3c3c; "
            "border-radius: 4px; font-size: 12px; padding: 6px;"
        )
        self.ai_results_layout.addWidget(self.explanation_text)

        # Suggested Code
        code_label = QLabel("Suggested Code (Requires Student Review)")
        code_label.setStyleSheet("color: #81C784; font-weight: bold; font-size: 13px; margin-top: 8px;")
        self.ai_results_layout.addWidget(code_label)

        self.code_text = QTextEdit()
        self.code_text.setReadOnly(True)
        self.code_text.setMinimumHeight(140)
        self.code_text.setStyleSheet(
            "background-color: #1a1a2e; color: #a5d6a7; border: 1px solid #3c3c3c; "
            "border-radius: 4px; font-family: Consolas, 'Courier New', monospace; font-size: 12px; padding: 6px;"
        )
        self.ai_results_layout.addWidget(self.code_text)

        # Edge Cases & Concepts
        extra_label = QLabel("Concepts & Edge Cases")
        extra_label.setStyleSheet("color: #FFB74D; font-weight: bold; font-size: 13px; margin-top: 8px;")
        self.ai_results_layout.addWidget(extra_label)

        self.extra_info_text = QTextEdit()
        self.extra_info_text.setReadOnly(True)
        self.extra_info_text.setMinimumHeight(100)
        self.extra_info_text.setStyleSheet(
            "background-color: #252526; color: #d4d4d4; border: 1px solid #3c3c3c; "
            "border-radius: 4px; font-size: 12px; padding: 6px;"
        )
        self.ai_results_layout.addWidget(self.extra_info_text)

        # Error display
        self.ai_error_label = QLabel("")
        self.ai_error_label.setStyleSheet(
            "color: #ff5252; font-weight: bold; font-size: 12px; padding: 6px;"
        )
        self.ai_error_label.setWordWrap(True)
        self.ai_error_label.setVisible(False)
        self.ai_results_layout.addWidget(self.ai_error_label)

        # Student approval reminder
        self.approval_label = QLabel(
            "⚠ All suggestions require YOUR explicit review and approval before use. "
            "No automatic submissions will be made."
        )
        self.approval_label.setStyleSheet(
            "color: #FFD54F; font-size: 11px; font-weight: bold; padding: 6px; margin-top: 8px;"
        )
        self.approval_label.setWordWrap(True)
        self.ai_results_layout.addWidget(self.approval_label)

        scroll.setWidget(scroll_content)
        ai_layout.addWidget(scroll)
        self.right_tabs.addTab(ai_tab, "🧠 AI Analysis")

        right_column.addWidget(self.right_tabs)
        content_splitter.addWidget(right_widget)

        content_splitter.setStretchFactor(0, 4)
        content_splitter.setStretchFactor(1, 6)

        main_layout.addWidget(content_splitter)

        # 4. Status Bar
        self.status_bar = ConnectionStatusBar(self)
        main_layout.addWidget(self.status_bar)

        self.append_log("NIAT CodePilot Worker initialized. Awaiting explicit user consent.")
        api_status = "configured" if self.ai_engine.is_configured else "NOT configured (mock mode)"
        self.append_log(f"AI Engine: OpenAI API {api_status} | Model: {self.ai_engine.model}")

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
            self.analyze_btn.setEnabled(True)
            self.preview_widget.set_placeholder("Ready to capture. Click 'Start' or 'Capture Single Preview'.")
            self.approved_frame_label.setText("Approved Frame: None (Click 'Capture Single Preview' to prepare)")
            self.approved_frame_label.setStyleSheet("color: #ffb74d; font-size: 11px;")
            self.append_log("User GRANTED explicit screen capture permission.")
        else:
            self.start_btn.setEnabled(False)
            self.preview_btn.setEnabled(False)
            self.analyze_btn.setEnabled(False)
            self.capture_service.clear_approved_frame()
            self.approved_frame_label.setText("Approved Frame: Revoked (No Consent)")
            self.approved_frame_label.setStyleSheet("color: #888888; font-size: 11px;")
            if self.capture_service.has_permission:
                self.on_stop_clicked()
            self.preview_widget.set_placeholder("Screen Capture Inactive\n(Explicit user consent required)")
            self.append_log("User REVOKED screen capture permission.")

    def on_target_mode_changed(self, index: int) -> None:
        """Handle target mode switch between monitor, window, and custom region."""
        mode = self.target_mode_combo.currentData()
        self.window_selection_widget.setVisible(mode == "window")
        self.region_selection_widget.setVisible(mode == "region")
        if mode == "window":
            self.refresh_window_list()
        self._apply_capture_targeting()

    def refresh_window_list(self) -> None:
        """Populate the window dropdown with open capturable windows, excluding NIAT CodePilot."""
        self.window_combo.blockSignals(True)
        self.window_combo.clear()
        windows = list_capturable_windows(exclude_titles=("NIAT CodePilot",))
        if not windows:
            self.window_combo.addItem("No capturable windows found", None)
        else:
            for w in windows:
                title = w["title"]
                hwnd = w["hwnd"]
                rect = w["rect"]
                w_w = max(0, rect[2] - rect[0])
                w_h = max(0, rect[3] - rect[1])
                self.window_combo.addItem(f"{title[:40]} ({w_w}x{w_h})", hwnd)
        self.window_combo.blockSignals(False)
        self._apply_capture_targeting()

    def on_window_selected(self, index: int) -> None:
        """Handle selection of a different application window."""
        self._apply_capture_targeting()

    def _apply_capture_targeting(self) -> None:
        """Propagate current UI target selection into the ScreenCaptureService."""
        mode = self.target_mode_combo.currentData() or "monitor"
        if mode == "window":
            hwnd = self.window_combo.currentData()
            title = self.window_combo.currentText()
            self.capture_service.set_target_mode("window", window_hwnd=hwnd, window_title=title)
        elif mode == "region":
            x = self.region_x_spin.value()
            y = self.region_y_spin.value()
            w = self.region_w_spin.value()
            h = self.region_h_spin.value()
            self.capture_service.set_target_mode("region", region_rect=(x, y, w, h))
        else:
            self.capture_service.set_target_mode("monitor", monitor_index=1)

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
        user_secret = self.secret_key_edit.text().strip().strip("'\"")
        self.worker_client.secret_key = user_secret or settings.controller_secret_key
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
        self.analyze_btn.setEnabled(False)

        self.preview_widget.set_placeholder("EMERGENCY STOP ACTIVATED\nAll screen capture instantly terminated.", is_emergency=True)
        self.preview_info_label.setText("Status: EMERGENCY STOPPED")
        self.approved_frame_label.setText("Approved Frame: Cleared (Emergency Stop)")
        self.approved_frame_label.setStyleSheet("color: #d32f2f; font-size: 11px; font-weight: bold;")
        self.status_bar.set_permission_status(False)
        self.status_bar.set_connection_status(False, "Emergency Halted")

        self.append_log("EMERGENCY STOP TRIGGERED. All permissions and capture loops terminated immediately.")

    def on_single_preview_clicked(self) -> None:
        """Capture and display a single frame on-demand and register as approved frame."""
        self._apply_capture_targeting()
        try:
            b64_jpeg, meta = self.capture_service.capture_jpeg_base64(quality=settings.openai_jpeg_quality)
            raw_bytes = base64.b64decode(b64_jpeg)
            qimage = QImage.fromData(QByteArray(raw_bytes))
            pixmap = QPixmap.fromImage(qimage)
            self.preview_widget.update_frame(pixmap, f"Target: {self.capture_service.target_mode.upper()} | {meta.width}x{meta.height}")
            self.preview_info_label.setText(
                f"Mode: {self.capture_service.target_mode.upper()} | Resolution: {meta.width}x{meta.height} | "
                f"Size: {meta.frame_size_bytes / 1024:.1f} KB | Verified: Explicit Consent"
            )
            self.approved_frame_label.setText(
                f"Approved Frame: {meta.width}x{meta.height} ({self.capture_service.target_mode.upper()}) — Ready for AI"
            )
            self.approved_frame_label.setStyleSheet("color: #4CAF50; font-size: 11px; font-weight: bold;")
            self.append_log(f"Captured single frame preview ({self.capture_service.target_mode.upper()}, {meta.width}x{meta.height}, {meta.frame_size_bytes} bytes)")
        except PermissionError as pe:
            QMessageBox.warning(self, "Permission Denied", str(pe))
            self.append_log(f"Permission error: {pe}")
        except Exception as e:
            self.append_log(f"Preview capture failed: {e}")
            self.approved_frame_label.setText(f"Capture Failed: {e}")
            self.approved_frame_label.setStyleSheet("color: #f44336; font-size: 11px; font-weight: bold;")
            QMessageBox.warning(
                self,
                "Window Capture Failed",
                f"Could not capture application window:\n\n{e}\n\n"
                "Please ensure the application window is open, unminimized, and visible on your screen, then try again.",
            )

    def on_auto_preview_tick(self) -> None:
        """Periodically grab a preview frame when worker is actively running."""
        if not self.capture_service.has_permission:
            return
        self._apply_capture_targeting()
        try:
            b64_jpeg, meta = self.capture_service.capture_jpeg_base64(quality=settings.openai_jpeg_quality)
            raw_bytes = base64.b64decode(b64_jpeg)
            qimage = QImage.fromData(QByteArray(raw_bytes))
            pixmap = QPixmap.fromImage(qimage)
            self.preview_widget.update_frame(pixmap)
            self.preview_info_label.setText(
                f"Mode: {self.capture_service.target_mode.upper()} | Resolution: {meta.width}x{meta.height} | "
                f"Size: {meta.frame_size_bytes / 1024:.1f} KB | Active Preview"
            )
            self.approved_frame_label.setText(
                f"Approved Frame: {meta.width}x{meta.height} ({self.capture_service.target_mode.upper()}) — Auto Updated"
            )
            self.approved_frame_label.setStyleSheet("color: #4CAF50; font-size: 11px; font-weight: bold;")
        except Exception as e:
            self.append_log(f"Auto preview tick error: {e}")

    # ------------------------------------------------------------------
    # AI Screen Analysis
    # ------------------------------------------------------------------
    def on_analyze_screen_clicked(self) -> None:
        """Analyze the approved screen capture frame using the configured AI provider."""
        if not self.consent_checkbox.isChecked():
            QMessageBox.warning(
                self,
                "Permission Required",
                "Explicit user permission must be granted before screen analysis.",
            )
            return

        self._apply_capture_targeting()

        # Single source of truth: retrieve the current approved frame or capture one
        approved = self.capture_service.get_last_approved_frame()
        if approved is None:
            if not self.capture_service._is_active:
                try:
                    self.capture_service.start()
                except PermissionError as pe:
                    QMessageBox.warning(self, "Permission Denied", str(pe))
                    return

            try:
                b64_jpeg, meta = self.capture_service.capture_jpeg_base64(
                    quality=settings.openai_jpeg_quality,
                )
                approved = (b64_jpeg, meta)
                raw_bytes = base64.b64decode(b64_jpeg)
                qimage = QImage.fromData(QByteArray(raw_bytes))
                self.preview_widget.update_frame(QPixmap.fromImage(qimage), f"Captured: {meta.width}x{meta.height}")
                self.approved_frame_label.setText(
                    f"Approved Frame: {meta.width}x{meta.height} ({self.capture_service.target_mode.upper()}) — Ready for AI"
                )
                self.approved_frame_label.setStyleSheet("color: #4CAF50; font-size: 11px; font-weight: bold;")
            except Exception as e:
                self.append_log(f"Screenshot capture for AI failed: {e}")
                self.approved_frame_label.setText(f"Capture Failed: {e}")
                self.approved_frame_label.setStyleSheet("color: #f44336; font-size: 11px; font-weight: bold;")
                QMessageBox.critical(
                    self,
                    "Window Capture Failed",
                    f"Failed to capture application window for AI analysis:\n\n{e}\n\n"
                    "Please ensure the window is open, unminimized, and visible on your screen, or select another window.",
                )
                return

        b64_jpeg, meta = approved
        provider_name = settings.ai_provider.upper()

        # Confirm student intent referencing the exact frame and provider
        reply = QMessageBox.question(
            self,
            f"Confirm AI Screen Analysis ({provider_name})",
            f"This will send the approved screen capture ({meta.width}x{meta.height}, {meta.frame_size_bytes / 1024:.1f} KB)\n"
            f"to the configured AI provider ({provider_name}) for coding analysis.\n\n"
            "• Both the preview and AI analysis use this identical captured frame.\n"
            "• No passwords or personal data will be transmitted.\n"
            "• No automatic portal submissions will be made.\n"
            "• You must review all suggestions before using them.\n\n"
            "Do you want to proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self.append_log("AI analysis cancelled by student.")
            return

        self.append_log(
            f"Submitting approved frame ({meta.width}x{meta.height}, {meta.frame_size_bytes / 1024:.1f} KB) to {provider_name}..."
        )

        # Show loading state
        self._set_ai_loading(True)
        self.analyze_btn.setEnabled(False)

        # Switch to AI tab
        self.right_tabs.setCurrentIndex(1)

        # Launch analysis in background thread
        additional = self.additional_prompt_edit.text().strip()
        self.ai_thread = AIAnalysisThread(
            ai_engine=self.ai_engine,
            image_base64=b64_jpeg,
            worker_id=self.capture_service.worker_id,
            additional_prompt=additional,
            parent=self,
        )
        self.ai_thread.analysis_complete.connect(self.on_ai_analysis_complete)
        self.ai_thread.analysis_error.connect(self.on_ai_analysis_error)
        self.ai_thread.start()

    def _set_ai_loading(self, loading: bool) -> None:
        """Toggle the AI loading indicator visibility."""
        self.ai_progress.setVisible(loading)
        if loading:
            self.ai_loading_label.setText("🔄 Analyzing screen with AI... Please wait.")
            self.ai_error_label.setVisible(False)
        else:
            self.ai_loading_label.setText("")

    def on_ai_analysis_complete(self, result: CodingAnalysisResult) -> None:
        """Display structured AI analysis results in the UI."""
        self._set_ai_loading(False)
        self.analyze_btn.setEnabled(self.consent_checkbox.isChecked())

        # Problem title & description
        self.problem_title_label.setText(f"📋 {result.problem_title}")
        self.problem_desc_text.setPlainText(result.problem_description or "No problem description extracted.")
        if result.programming_language:
            self.problem_title_label.setText(
                f"📋 {result.problem_title}  [{result.programming_language}]"
            )

        # Step-by-step explanation
        explanation_parts = []
        if result.constraints:
            explanation_parts.append("Constraints:")
            for c in result.constraints:
                explanation_parts.append(f"  • {c}")
            explanation_parts.append("")

        if result.input_format:
            explanation_parts.append(f"Input Format: {result.input_format}")
        if result.output_format:
            explanation_parts.append(f"Output Format: {result.output_format}")
        if result.input_format or result.output_format:
            explanation_parts.append("")

        if result.sample_inputs or result.sample_outputs:
            for i, (si, so) in enumerate(
                zip(
                    result.sample_inputs or [],
                    result.sample_outputs or [],
                ),
                1,
            ):
                explanation_parts.append(f"Sample {i}:")
                explanation_parts.append(f"  Input:  {si}")
                explanation_parts.append(f"  Output: {so}")
            explanation_parts.append("")

        if result.step_by_step_explanation:
            explanation_parts.append("Explanation:")
            for step in result.step_by_step_explanation:
                explanation_parts.append(f"  {step}")

        if result.code_explanation:
            explanation_parts.append("")
            explanation_parts.append("Code Walkthrough:")
            explanation_parts.append(result.code_explanation)

        self.explanation_text.setPlainText("\n".join(explanation_parts) if explanation_parts else "No explanation available.")

        # Suggested code
        self.code_text.setPlainText(result.suggested_code or "# No code suggestion generated.")

        # Edge cases & concepts
        extra_parts = []
        if result.relevant_concepts:
            extra_parts.append("Relevant Concepts:")
            for concept in result.relevant_concepts:
                extra_parts.append(f"  • {concept}")
            extra_parts.append("")

        if result.edge_cases:
            extra_parts.append("Edge Cases:")
            for ec in result.edge_cases:
                line = f"  • {ec.description}"
                if ec.example_input:
                    line += f" (input: {ec.example_input})"
                if ec.expected_behavior:
                    line += f" → {ec.expected_behavior}"
                extra_parts.append(line)

        if result.confidence_note:
            extra_parts.append("")
            extra_parts.append(f"Confidence: {result.confidence_note}")

        self.extra_info_text.setPlainText("\n".join(extra_parts) if extra_parts else "No additional information.")

        self.append_log(f"AI analysis complete: '{result.problem_title}'")

    def on_ai_analysis_error(self, error: str) -> None:
        """Display AI analysis error in the UI."""
        self._set_ai_loading(False)
        self.analyze_btn.setEnabled(self.consent_checkbox.isChecked())
        self.ai_error_label.setText(f"❌ Analysis Error: {error}")
        self.ai_error_label.setVisible(True)
        self.append_log(f"AI analysis error: {error}")

    # ------------------------------------------------------------------
    # Heartbeat callbacks
    # ------------------------------------------------------------------
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
