"""Main PySide6 application window for the NIAT CodePilot Worker.

Implements the Approved Premium UI & Computer-Use Agent:
- Balanced futuristic glass-and-midnight design.
- Central animated AI Assistant Orb (Idle, Listening, Thinking, Analyzing, Responding, Error).
- Floating assistant controls dock (Voice mic, text query, 1-click analyze, keyboard typing, practice bed, workspace toggle, pause, emergency stop).
- Live Action Timeline documenting observation, focus checks, keystroke chunks, and verifications.
- Expandable structured coding workspace (Overview, Approach, Code Review, Debugging & Edge Cases).
- Robust NIAT Portal Chrome window discovery, explicit consent, approved-frame synchronization, and emergency halt.
- Zero clipboard paste: keyboard input via Windows SendInput with intra-chunk focus verification and emergency stop abort.
"""

import asyncio
import base64
import sys
import time
from typing import Optional, Tuple
from PySide6.QtCore import QByteArray, QDateTime, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.common.config import settings
from src.common.constants import WorkerCommand, WorkerStatus
from src.common.logger import get_logger
from src.common.schemas import CodingAnalysisResult
from src.desktop.components.action_timeline import ActionTimelineWidget
from src.desktop.components.ai_orb import AIOrbContainer, OrbState
from src.desktop.components.coding_workspace import CodingWorkspaceWidget
from src.desktop.components.floating_controls import FloatingControlsDock
from src.desktop.components.practice_editor import PracticeEditorWindow
from src.desktop.components.preview_widget import ScreenPreviewWidget
from src.desktop.components.status_bar import ConnectionStatusBar
from src.worker.ai_engine import AIEngineService
from src.worker.capture import ScreenCaptureService, list_capturable_windows
from src.worker.client import WorkerClient
from src.worker.interaction import (
    EditorFocusLostError,
    EmergencyStopError,
    KeyboardComputerUseAgent,
    TimelineEvent,
    TimelineEventStatus,
    TimelineEventType,
)

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


class InteractiveTypingWorkerThread(QThread):
    """Background thread executing KeyboardComputerUseAgent without blocking the Qt GUI."""

    timeline_event_signal = Signal(object)  # TimelineEvent
    typing_complete = Signal(bool)
    typing_error = Signal(str)

    def __init__(
        self,
        target_hwnd: int,
        target_title: str,
        code_to_type: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.target_hwnd = target_hwnd
        self.target_title = target_title
        self.code_to_type = code_to_type
        self.is_paused = False
        self.is_stopped = False

    def run(self) -> None:
        agent = KeyboardComputerUseAgent(
            target_hwnd=self.target_hwnd,
            target_title=self.target_title,
            chunk_size=14,
            delay_between_chunks=0.035,
            on_timeline_event=lambda ev: self.timeline_event_signal.emit(ev),
            is_paused_check=lambda: self.is_paused,
            is_stopped_check=lambda: self.is_stopped,
        )
        try:
            ok = agent.type_code(self.code_to_type)
            self.typing_complete.emit(ok)
        except Exception as e:
            logger.error(f"Interactive typing error: {e}")
            self.typing_error.emit(str(e))

    def stop(self) -> None:
        self.is_stopped = True

    def toggle_pause(self) -> None:
        self.is_paused = not self.is_paused


class MainWindow(QMainWindow):
    """Approved Premium UI for NIAT CodePilot Worker with Computer-Use Agent."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NIAT CodePilot — Autonomous AI Coding Assistant")
        self.resize(1320, 860)
        self.setMinimumSize(1020, 720)

        # Worker core services
        self.capture_service = ScreenCaptureService(worker_id=settings.worker_id)
        self.worker_client = WorkerClient(
            worker_id=settings.worker_id,
            worker_name=settings.worker_name,
            controller_url=settings.controller_url,
            secret_key=settings.controller_secret_key,
            on_command_received=self.handle_controller_command,
        )
        self.ai_engine = AIEngineService()

        self.heartbeat_thread: Optional[HeartbeatWorkerThread] = None
        self.ai_thread: Optional[AIAnalysisThread] = None
        self.typing_thread: Optional[InteractiveTypingWorkerThread] = None
        self.practice_editor: Optional[PracticeEditorWindow] = None

        # Preview & Continuous Observation timers
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(2000)
        self.preview_timer.timeout.connect(self.on_auto_preview_tick)

        self.observe_timer = QTimer(self)
        self.observe_timer.setInterval(2500)
        self.observe_timer.timeout.connect(self.on_continuous_observe_tick)

        self._init_ui()
        self._apply_global_theme()
        self._auto_start_worker()

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(16, 12, 16, 10)
        root_layout.setSpacing(10)

        # -------------------------------------------------------------
        # 1. Top Glass Header Bar
        # -------------------------------------------------------------
        top_bar = QFrame(self)
        top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 8, 16, 8)
        top_layout.setSpacing(14)

        # Left: App Brand & Worker Pill
        brand_col = QVBoxLayout()
        brand_col.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        brand_dot = QLabel("●", self)
        brand_dot.setStyleSheet("color: #00E5FF; font-size: 14px;")
        title_row.addWidget(brand_dot)

        brand_title = QLabel("NIAT CodePilot", self)
        brand_title.setStyleSheet("color: #FFFFFF; font-size: 16px; font-weight: bold; letter-spacing: 0.5px;")
        title_row.addWidget(brand_title)
        brand_col.addLayout(title_row)

        self.worker_pill = QLabel(f"Laptop 2 • {settings.worker_id} ({settings.worker_name})", self)
        self.worker_pill.setStyleSheet("color: #8E9DB8; font-size: 11px;")
        brand_col.addWidget(self.worker_pill)
        top_layout.addLayout(brand_col)

        top_layout.addSpacing(10)

        # Center: Target Selector Pill & NIAT Chrome Selector
        target_box = QFrame(self)
        target_box.setObjectName("TargetBox")
        t_layout = QHBoxLayout(target_box)
        t_layout.setContentsMargins(10, 4, 10, 4)
        t_layout.setSpacing(8)

        t_lbl = QLabel("Target:", self)
        t_lbl.setStyleSheet("color: #A0AEC0; font-size: 11px; font-weight: bold;")
        t_layout.addWidget(t_lbl)

        self.target_mode_combo = QComboBox(self)
        self.target_mode_combo.addItem("Application Window", "window")
        self.target_mode_combo.addItem("Full Screen (Primary Monitor)", "monitor")
        self.target_mode_combo.addItem("Custom Region", "region")
        self.target_mode_combo.currentIndexChanged.connect(self.on_target_mode_changed)
        t_layout.addWidget(self.target_mode_combo)

        self.window_combo = QComboBox(self)
        self.window_combo.setMinimumWidth(280)
        self.window_combo.currentIndexChanged.connect(self.on_window_selected)
        t_layout.addWidget(self.window_combo)

        self.refresh_btn = QPushButton("🔄", self)
        self.refresh_btn.setFixedSize(28, 28)
        self.refresh_btn.setToolTip("Scan & Refresh open windows (Google Chrome NIAT portal, Practice Bed)")
        self.refresh_btn.clicked.connect(self.refresh_window_list)
        t_layout.addWidget(self.refresh_btn)

        # Region coordinates widgets (hidden by default)
        self.region_container = QWidget(self)
        reg_l = QHBoxLayout(self.region_container)
        reg_l.setContentsMargins(0, 0, 0, 0)
        reg_l.setSpacing(4)
        self.reg_x = QSpinBox(self); self.reg_x.setRange(0, 10000); self.reg_x.setValue(0)
        self.reg_y = QSpinBox(self); self.reg_y.setRange(0, 10000); self.reg_y.setValue(0)
        self.reg_w = QSpinBox(self); self.reg_w.setRange(50, 10000); self.reg_w.setValue(1280)
        self.reg_h = QSpinBox(self); self.reg_h.setRange(50, 10000); self.reg_h.setValue(720)
        for s in (self.reg_x, self.reg_y, self.reg_w, self.reg_h):
            s.valueChanged.connect(self._apply_capture_targeting)
            reg_l.addWidget(s)
        self.region_container.setVisible(False)
        t_layout.addWidget(self.region_container)

        top_layout.addWidget(target_box, 1)

        # Right: Explicit Consent Switch & AI Model Badge
        self.consent_checkbox = QCheckBox("Consent Active ✓", self)
        self.consent_checkbox.setChecked(True)
        self.consent_checkbox.setToolTip("Explicit Student Permission: Enables screen capture for coding analysis")
        self.consent_checkbox.toggled.connect(self.on_consent_toggled)
        top_layout.addWidget(self.consent_checkbox)

        self.ai_provider_pill = QLabel(f"Gemini • {settings.gemini_model}", self)
        self.ai_provider_pill.setObjectName("ProviderPill")
        top_layout.addWidget(self.ai_provider_pill)

        root_layout.addWidget(top_bar)

        # -------------------------------------------------------------
        # 2. Main Center Body (Splitter for Stage vs Expandable Workspace)
        # -------------------------------------------------------------
        self.body_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.body_splitter.setHandleWidth(8)

        # Left Stage: Center AI Orb + Floating Controls + Timeline + Preview Card
        self.stage_widget = QWidget(self)
        stage_layout = QVBoxLayout(self.stage_widget)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(10)
        stage_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Floating AI Orb
        self.orb_container = AIOrbContainer(self)
        stage_layout.addWidget(self.orb_container, alignment=Qt.AlignmentFlag.AlignCenter)

        # Floating Controls Dock
        self.controls_dock = FloatingControlsDock(self)
        self.controls_dock.voice_toggled.connect(self.on_voice_toggled)
        self.controls_dock.text_prompt_submitted.connect(self.on_text_submitted)
        self.controls_dock.analyze_clicked.connect(self.on_analyze_screen_clicked)
        self.controls_dock.type_code_clicked.connect(self.on_type_code_clicked)
        self.controls_dock.open_practice_editor_clicked.connect(self.on_open_practice_editor)
        self.controls_dock.continuous_observe_toggled.connect(self.on_continuous_observe_toggled)
        self.controls_dock.toggle_workspace_clicked.connect(self.on_toggle_workspace)
        self.controls_dock.pause_resume_clicked.connect(self.on_pause_resume_clicked)
        self.controls_dock.emergency_stop_clicked.connect(self.on_emergency_stop_clicked)
        stage_layout.addWidget(self.controls_dock)

        # Action Timeline
        self.timeline_widget = ActionTimelineWidget(self)
        stage_layout.addWidget(self.timeline_widget)

        # Target Preview & Approved Frame Card
        preview_card = QFrame(self)
        preview_card.setObjectName("PreviewCard")
        p_card_layout = QHBoxLayout(preview_card)
        p_card_layout.setContentsMargins(12, 6, 12, 6)
        p_card_layout.setSpacing(12)

        self.preview_widget = ScreenPreviewWidget(self)
        self.preview_widget.setFixedSize(140, 80)
        p_card_layout.addWidget(self.preview_widget)

        p_info_col = QVBoxLayout()
        p_info_col.setSpacing(2)
        self.approved_frame_label = QLabel("Approved Frame: None (Click 'Snapshot' or 'Analyze Question')", self)
        self.approved_frame_label.setStyleSheet("color: #FFB74D; font-size: 11px; font-weight: bold;")
        p_info_col.addWidget(self.approved_frame_label)

        self.target_desc_label = QLabel("Active Target: Auto-detecting Chrome NIAT Portal...", self)
        self.target_desc_label.setStyleSheet("color: #8E9DB8; font-size: 11px;")
        p_info_col.addWidget(self.target_desc_label)

        p_btn_row = QHBoxLayout()
        self.snapshot_btn = QPushButton("📷  Take Snapshot", self)
        self.snapshot_btn.setFixedHeight(26)
        self.snapshot_btn.clicked.connect(self.on_single_preview_clicked)
        p_btn_row.addWidget(self.snapshot_btn)
        p_btn_row.addStretch()
        p_info_col.addLayout(p_btn_row)

        p_card_layout.addLayout(p_info_col, 1)
        stage_layout.addWidget(preview_card)

        self.body_splitter.addWidget(self.stage_widget)

        # Right Stage: Expandable Structured Coding Workspace
        self.workspace_widget = CodingWorkspaceWidget(self)
        self.workspace_widget.close_requested.connect(self.on_toggle_workspace)
        self.workspace_widget.setVisible(False)  # Collapsed by default
        self.body_splitter.addWidget(self.workspace_widget)

        root_layout.addWidget(self.body_splitter, 1)

        # -------------------------------------------------------------
        # 3. Bottom Status Bar
        # -------------------------------------------------------------
        self.status_bar = ConnectionStatusBar(self)
        root_layout.addWidget(self.status_bar)

        # Populate initial window list
        self.refresh_window_list()

    def _apply_global_theme(self) -> None:
        """Apply the approved balanced futuristic midnight theme."""
        self.setStyleSheet(
            """
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0B0F19, stop:1 #060810);
            }
            #TopBar {
                background-color: rgba(18, 24, 38, 0.75);
                border: 1px solid rgba(0, 229, 255, 0.18);
                border-radius: 14px;
            }
            #TargetBox {
                background-color: rgba(11, 15, 25, 0.65);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 10px;
            }
            #ProviderPill {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(124, 77, 255, 0.25), stop:1 rgba(41, 121, 255, 0.25));
                color: #B388FF;
                border: 1px solid rgba(179, 136, 255, 0.40);
                border-radius: 12px;
                padding: 4px 14px;
                font-size: 11px;
                font-weight: bold;
            }
            #PreviewCard {
                background-color: rgba(18, 24, 38, 0.60);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
            QComboBox {
                background-color: rgba(22, 30, 48, 0.85);
                color: #E2E8F0;
                border: 1px solid rgba(0, 229, 255, 0.25);
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #0E1422;
                color: #E2E8F0;
                selection-background-color: #2979FF;
                border: 1px solid rgba(0, 229, 255, 0.30);
                border-radius: 8px;
                padding: 4px;
            }
            QCheckBox {
                color: #00E676;
                font-weight: bold;
                font-size: 12px;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid rgba(0, 230, 118, 0.50);
                background-color: rgba(0, 230, 118, 0.15);
            }
            QCheckBox::indicator:checked {
                background-color: #00E676;
            }
            QSpinBox {
                background-color: rgba(22, 30, 48, 0.85);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                padding: 2px 6px;
                font-size: 11px;
            }
            QSplitter::handle {
                background-color: rgba(0, 229, 255, 0.08);
                border-radius: 4px;
            }
            QSplitter::handle:hover {
                background-color: rgba(0, 229, 255, 0.30);
            }
            """
        )

    # -------------------------------------------------------------
    # Target Selection & Chrome Window Discovery
    # -------------------------------------------------------------
    def refresh_window_list(self) -> None:
        """Scan open desktop windows and populate dropdown, prioritizing Chrome and Practice Bed."""
        self.window_combo.blockSignals(True)
        self.window_combo.clear()
        windows = list_capturable_windows(exclude_titles=("NIAT CodePilot",))

        seen_hwnds = set()
        practice_hwnd = None

        # Check if local practice editor window is open
        if self.practice_editor and self.practice_editor.isVisible():
            try:
                practice_hwnd = int(self.practice_editor.winId())
                self.window_combo.addItem("🎯 NIAT Local Practice Editor (Authorized Test Bed)", practice_hwnd)
                seen_hwnds.add(practice_hwnd)
            except Exception as e:
                logger.debug(f"Could not retrieve PracticeEditor winId: {e}")

        chrome_index = -1
        for w in windows:
            hwnd = w["hwnd"]
            if hwnd in seen_hwnds:
                continue
            seen_hwnds.add(hwnd)

            title = w["title"]
            rect = w["rect"]
            width = max(0, rect[2] - rect[0])
            height = max(0, rect[3] - rect[1])

            is_chrome_or_niat = w.get("is_browser", False) or any(
                k in title.lower() for k in ("chrome", "niat", "leetcode", "problem")
            )
            prefix = "🌐 " if is_chrome_or_niat else "🪟 "
            display = f"{prefix}{title[:42]} ({width}x{height})"
            self.window_combo.addItem(display, hwnd)

            if is_chrome_or_niat and chrome_index == -1:
                chrome_index = self.window_combo.count() - 1

        if self.window_combo.count() == 0:
            self.window_combo.addItem("No capturable windows found", None)
            self.target_desc_label.setText("No active application window detected.")
        else:
            if practice_hwnd:
                idx = self.window_combo.findData(practice_hwnd)
                if idx >= 0:
                    self.window_combo.setCurrentIndex(idx)
            elif chrome_index >= 0:
                self.window_combo.setCurrentIndex(chrome_index)

        self.window_combo.blockSignals(False)
        self._apply_capture_targeting()

    def on_target_mode_changed(self, index: int) -> None:
        mode = self.target_mode_combo.currentData()
        self.window_combo.setVisible(mode == "window")
        self.refresh_btn.setVisible(mode == "window")
        self.region_container.setVisible(mode == "region")
        if mode == "window":
            self.refresh_window_list()
        self._apply_capture_targeting()

    def on_window_selected(self, index: int) -> None:
        self._apply_capture_targeting()

    def _apply_capture_targeting(self) -> None:
        """Synchronize UI selections into the ScreenCaptureService."""
        mode = self.target_mode_combo.currentData() or "window"
        if mode == "window":
            hwnd = self.window_combo.currentData()
            title = self.window_combo.currentText()
            self.capture_service.set_target_mode("window", window_hwnd=hwnd, window_title=title)
            self.target_desc_label.setText(f"Target: {title}")
        elif mode == "region":
            x, y = self.reg_x.value(), self.reg_y.value()
            w, h = self.reg_w.value(), self.reg_h.value()
            self.capture_service.set_target_mode("region", region_rect=(x, y, w, h))
            self.target_desc_label.setText(f"Target: Region ({x}, {y}, {w}x{h})")
        else:
            self.capture_service.set_target_mode("monitor", monitor_index=1)
            self.target_desc_label.setText("Target: Primary Monitor (Full Screen)")

    # -------------------------------------------------------------
    # Worker Lifecycle & Registration
    # -------------------------------------------------------------
    def _auto_start_worker(self) -> None:
        """Register worker, activate consent, and start heartbeats."""
        self.capture_service.set_user_permission(True)
        self.worker_client.set_permission_active(True)
        self.status_bar.set_permission_status(True)

        loop = asyncio.new_event_loop()
        try:
            resp = loop.run_until_complete(self.worker_client.register(explicit_consent=True))
            self.status_bar.set_connection_status(True, f"ID: {resp.worker_id}")
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.VERIFY,
                    title="Worker Registered",
                    description=f"Connected to controller with ID '{resp.worker_id}'",
                    status=TimelineEventStatus.SUCCESS,
                )
            )
        except Exception as e:
            logger.warning(f"Initial controller registration note: {e}")
            self.status_bar.set_connection_status(False, "Offline / Local Mode")
        finally:
            loop.close()

        try:
            self.capture_service.start()
        except Exception as e:
            logger.warning(f"Capture service start note: {e}")

        if self.heartbeat_thread is None or not self.heartbeat_thread.isRunning():
            self.heartbeat_thread = HeartbeatWorkerThread(self.worker_client, self)
            self.heartbeat_thread.heartbeat_success.connect(self.on_heartbeat_success)
            self.heartbeat_thread.heartbeat_error.connect(self.on_heartbeat_error)
            self.heartbeat_thread.command_received.connect(self.handle_controller_command)
            self.heartbeat_thread.start()

        self.preview_timer.start()

    def on_heartbeat_success(self, count: int, latency_ms: float) -> None:
        self.status_bar.heartbeat_label.setText(f"Heartbeats: {count} ({latency_ms:.1f}ms)")
        self.status_bar.set_connection_status(True, f"Online ({latency_ms:.1f}ms)")

    def on_heartbeat_error(self, err_msg: str) -> None:
        self.status_bar.set_reconnecting_status(err_msg)

    def handle_controller_command(self, cmd_value: str) -> None:
        """Handle remote commands from controller."""
        if cmd_value == WorkerCommand.EMERGENCY_STOP.value:
            self.on_emergency_stop_clicked()
        elif cmd_value == WorkerCommand.PAUSE.value:
            self.on_pause_resume_clicked()
        elif cmd_value == WorkerCommand.RESUME.value:
            if self.controls_dock._is_paused:
                self.on_pause_resume_clicked()

    # -------------------------------------------------------------
    # User Controls & Orb Interaction
    # -------------------------------------------------------------
    def on_consent_toggled(self, checked: bool) -> None:
        """Handle explicit permission checkbox toggle."""
        self.capture_service.set_user_permission(checked)
        self.worker_client.set_permission_active(checked)
        self.status_bar.set_permission_status(checked)

        if checked:
            self.approved_frame_label.setText("Consent Active • Standing by")
            self.approved_frame_label.setStyleSheet("color: #00E676; font-size: 11px; font-weight: bold;")
            self.orb_container.set_state(OrbState.IDLE)
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.VERIFY,
                    title="Consent Granted",
                    description="Student granted explicit screen capture permission",
                    status=TimelineEventStatus.SUCCESS,
                )
            )
        else:
            self.capture_service.clear_approved_frame()
            if self.typing_thread and self.typing_thread.isRunning():
                self.typing_thread.stop()
            self.approved_frame_label.setText("Approved Frame: Revoked (No Consent)")
            self.approved_frame_label.setStyleSheet("color: #FF5252; font-size: 11px; font-weight: bold;")
            self.preview_widget.set_placeholder("Screen Capture Inactive\n(Consent Revoked)")
            self.orb_container.set_state(OrbState.ERROR, "Consent revoked by user.")
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.ERROR,
                    title="Consent Revoked",
                    description="Screen capture permissions revoked. All interactions paused.",
                    status=TimelineEventStatus.WARNING,
                )
            )

    def on_voice_toggled(self, active: bool) -> None:
        if active:
            self.orb_container.set_state(OrbState.LISTENING)
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.OBSERVE,
                    title="Voice Mode Active",
                    description="Listening for student voice queries...",
                    status=TimelineEventStatus.IN_PROGRESS,
                )
            )
        else:
            self.orb_container.set_state(OrbState.IDLE)

    def on_text_submitted(self, prompt: str) -> None:
        self.orb_container.set_state(OrbState.THINKING, f"Consulting AI: '{prompt[:35]}...'")
        self.timeline_widget.add_event(
            TimelineEvent(
                event_type=TimelineEventType.ANALYZE,
                title="Student Query",
                description=f"Prompt: '{prompt}'",
                status=TimelineEventStatus.IN_PROGRESS,
            )
        )
        self.on_analyze_screen_clicked(additional_prompt=prompt)

    def on_toggle_workspace(self) -> None:
        is_visible = self.workspace_widget.isVisible()
        self.workspace_widget.setVisible(not is_visible)
        self.controls_dock.set_workspace_expanded(not is_visible)
        if not is_visible:
            self.body_splitter.setSizes([440, 880])
        else:
            self.body_splitter.setSizes([1200, 0])

    def on_open_practice_editor(self) -> None:
        """Open, restore, or focus the local practice editor test bed."""
        logger.info("MainWindow: '🎯 Practice Bed' action triggered.")
        try:
            # Check if existing instance is still valid (not destroyed by Qt)
            if self.practice_editor is not None:
                try:
                    _ = self.practice_editor.isVisible()
                except RuntimeError:
                    logger.info("Previous PracticeEditorWindow C++ instance was destroyed; creating fresh instance.")
                    self.practice_editor = None

            if self.practice_editor is None:
                logger.info("Instantiating new PracticeEditorWindow...")
                self.practice_editor = PracticeEditorWindow()
                self.practice_editor.closed_signal.connect(self._on_practice_editor_closed)

            # Ensure restored if minimized, then show, raise, and activate
            if self.practice_editor.isMinimized():
                logger.info("PracticeEditorWindow is minimized; restoring via showNormal().")
                self.practice_editor.showNormal()
            else:
                self.practice_editor.show()

            self.practice_editor.setVisible(True)
            self.practice_editor.raise_()
            self.practice_editor.activateWindow()

            hwnd = int(self.practice_editor.winId()) if hasattr(self.practice_editor, "winId") else 0
            logger.info(
                f"PracticeEditorWindow displayed successfully (HWND={hwnd}, visible={self.practice_editor.isVisible()})."
            )

            # Refresh windows so Practice Bed is listed and selected in dropdown
            self.refresh_window_list()
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.OBSERVE,
                    title="Practice Editor Launched",
                    description="Local test bed ready for focus detection, typing, and emergency stop testing",
                    status=TimelineEventStatus.SUCCESS,
                )
            )
        except Exception as e:
            logger.exception(f"Error opening or displaying Practice Editor: {e}")
            QMessageBox.warning(
                self,
                "Practice Editor Error",
                f"Could not open Practice Editor window:\n\n{e}",
            )

    def _on_practice_editor_closed(self) -> None:
        """Handle local practice editor window close: refresh window capture target list."""
        logger.info("PracticeEditorWindow closed. Refreshing window capture dropdown.")
        self.refresh_window_list()

    def on_continuous_observe_toggled(self, observing: bool) -> None:
        """Toggle continuous screen observation."""
        if observing:
            self.observe_timer.start()
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.OBSERVE,
                    title="Live Observation Started",
                    description="Monitoring target window continuously for coding questions and editor updates",
                    status=TimelineEventStatus.SUCCESS,
                )
            )
        else:
            self.observe_timer.stop()
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.OBSERVE,
                    title="Live Observation Stopped",
                    description="Continuous screen observation paused",
                    status=TimelineEventStatus.SUCCESS,
                )
            )

    def on_continuous_observe_tick(self) -> None:
        """Periodic observation loop."""
        if not self.consent_checkbox.isChecked() or self.controls_dock._is_paused:
            return
        try:
            b64_jpeg, meta = self.capture_service.capture_jpeg_base64(quality=settings.openai_jpeg_quality)
            raw_bytes = base64.b64decode(b64_jpeg)
            qimage = QImage.fromData(QByteArray(raw_bytes))
            self.preview_widget.update_frame(QPixmap.fromImage(qimage))
            self.approved_frame_label.setText(f"Approved Frame: {meta.width}x{meta.height} • Live")
        except Exception as e:
            logger.debug(f"Continuous observation tick notice: {e}")

    def on_pause_resume_clicked(self) -> None:
        """Toggle capture pause/resume."""
        if self.preview_timer.isActive():
            self.preview_timer.stop()
            self.observe_timer.stop()
            self.capture_service.stop()
            if self.typing_thread and self.typing_thread.isRunning():
                self.typing_thread.toggle_pause()
            self.controls_dock.set_paused_state(True)
            self.orb_container.set_state(OrbState.IDLE, "Capture paused. AI assistant standing by.")
            self.approved_frame_label.setText("Capture Paused")
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.PAUSE,
                    title="Interaction Paused",
                    description="Screen capture and agent keystrokes suspended by student",
                    status=TimelineEventStatus.WARNING,
                )
            )
        else:
            self.capture_service.start()
            self.preview_timer.start()
            if self.controls_dock._is_observing:
                self.observe_timer.start()
            if self.typing_thread and self.typing_thread.isRunning():
                self.typing_thread.toggle_pause()
            self.controls_dock.set_paused_state(False)
            self.orb_container.set_state(OrbState.IDLE, "Capture resumed.")
            self.approved_frame_label.setText("Capture Active")
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.PAUSE,
                    title="Interaction Resumed",
                    description="Screen capture and computer-use agent resumed",
                    status=TimelineEventStatus.SUCCESS,
                )
            )

    def on_emergency_stop_clicked(self) -> None:
        """Instantly terminate all screen captures, typing, and flush buffers."""
        self.preview_timer.stop()
        self.observe_timer.stop()
        self.capture_service.emergency_halt()

        if self.typing_thread and self.typing_thread.isRunning():
            self.typing_thread.stop()

        if self.heartbeat_thread and self.heartbeat_thread.isRunning():
            self.heartbeat_thread.stop()

        self.worker_client.status = WorkerStatus.EMERGENCY_STOPPED
        self.consent_checkbox.setChecked(False)

        self.orb_container.set_state(OrbState.ERROR, "EMERGENCY STOP ACTIVATED — All screen capture terminated.")
        self.preview_widget.set_placeholder("EMERGENCY STOP ACTIVATED", is_emergency=True)
        self.approved_frame_label.setText("Approved Frame: Cleared (Emergency Stop)")
        self.approved_frame_label.setStyleSheet("color: #FF1744; font-size: 11px; font-weight: bold;")
        self.status_bar.set_permission_status(False)
        self.status_bar.set_connection_status(False, "Emergency Halted")

        self.timeline_widget.add_event(
            TimelineEvent(
                event_type=TimelineEventType.EMERGENCY_STOP,
                title="EMERGENCY STOP TRIGGERED",
                description="Instant halt: Keystrokes, captures, and permissions revoked immediately.",
                status=TimelineEventStatus.FAILED,
            )
        )

    # -------------------------------------------------------------
    # Screen Capture & AI Analysis
    # -------------------------------------------------------------
    def on_single_preview_clicked(self) -> None:
        """Capture and display a single frame on-demand and register as approved frame."""
        self._apply_capture_targeting()
        try:
            b64_jpeg, meta = self.capture_service.capture_jpeg_base64(quality=settings.openai_jpeg_quality)
            raw_bytes = base64.b64decode(b64_jpeg)
            qimage = QImage.fromData(QByteArray(raw_bytes))
            pixmap = QPixmap.fromImage(qimage)
            self.preview_widget.update_frame(pixmap, f"Target: {self.capture_service.target_mode.upper()} | {meta.width}x{meta.height}")
            self.approved_frame_label.setText(
                f"Approved Frame: {meta.width}x{meta.height} ({self.capture_service.target_mode.upper()}) — Ready"
            )
            self.approved_frame_label.setStyleSheet("color: #00E676; font-size: 11px; font-weight: bold;")
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.OBSERVE,
                    title="Snapshot Captured",
                    description=f"Captured {meta.width}x{meta.height} frame ({meta.frame_size_bytes / 1024:.1f} KB)",
                    status=TimelineEventStatus.SUCCESS,
                )
            )
        except PermissionError as pe:
            QMessageBox.warning(self, "Permission Denied", str(pe))
        except Exception as e:
            self.approved_frame_label.setText(f"Capture Failed: {e}")
            self.approved_frame_label.setStyleSheet("color: #FF5252; font-size: 11px; font-weight: bold;")
            self.orb_container.set_state(OrbState.ERROR, str(e))
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.ERROR,
                    title="Capture Failed",
                    description=str(e),
                    status=TimelineEventStatus.FAILED,
                )
            )
            QMessageBox.warning(
                self,
                "Window Capture Failed",
                f"Could not capture selected window:\n\n{e}\n\n"
                "Please ensure the application window (e.g. Chrome NIAT Portal) is open, unminimized, and visible on your screen.",
            )

    def on_auto_preview_tick(self) -> None:
        """Periodically grab a preview frame when capture is active."""
        if not self.capture_service.has_permission:
            return
        self._apply_capture_targeting()
        try:
            b64_jpeg, meta = self.capture_service.capture_jpeg_base64(quality=settings.openai_jpeg_quality)
            raw_bytes = base64.b64decode(b64_jpeg)
            qimage = QImage.fromData(QByteArray(raw_bytes))
            pixmap = QPixmap.fromImage(qimage)
            self.preview_widget.update_frame(pixmap)
            self.approved_frame_label.setText(f"Approved Frame: {meta.width}x{meta.height} • Ready")
            self.approved_frame_label.setStyleSheet("color: #00E676; font-size: 11px; font-weight: bold;")
        except Exception:
            pass

    def on_analyze_screen_clicked(self, additional_prompt: str = "") -> None:
        """One-click trigger: captures approved frame from NIAT Chrome window and analyzes with Gemini."""
        if not self.consent_checkbox.isChecked():
            QMessageBox.warning(
                self,
                "Permission Required",
                "Explicit user permission must be active before screen analysis.",
            )
            return

        self._apply_capture_targeting()

        approved = self.capture_service.get_last_approved_frame()
        if approved is None:
            if not self.capture_service._is_active:
                try:
                    self.capture_service.start()
                except PermissionError as pe:
                    QMessageBox.warning(self, "Permission Denied", str(pe))
                    return

            self.orb_container.set_state(OrbState.ANALYZING_SCREEN)
            try:
                b64_jpeg, meta = self.capture_service.capture_jpeg_base64(
                    quality=settings.openai_jpeg_quality,
                )
                approved = (b64_jpeg, meta)
                raw_bytes = base64.b64decode(b64_jpeg)
                qimage = QImage.fromData(QByteArray(raw_bytes))
                self.preview_widget.update_frame(QPixmap.fromImage(qimage), f"Captured: {meta.width}x{meta.height}")
                self.approved_frame_label.setText(f"Approved Frame: {meta.width}x{meta.height} • Analyzed")
                self.approved_frame_label.setStyleSheet("color: #00E676; font-size: 11px; font-weight: bold;")
                self.timeline_widget.add_event(
                    TimelineEvent(
                        event_type=TimelineEventType.OBSERVE,
                        title="Screen Observed",
                        description=f"Approved {meta.width}x{meta.height} frame for analysis",
                        status=TimelineEventStatus.SUCCESS,
                    )
                )
            except Exception as e:
                self.orb_container.set_state(OrbState.ERROR, f"Capture failed: {e}")
                self.approved_frame_label.setText(f"Capture Failed: {e}")
                self.approved_frame_label.setStyleSheet("color: #FF5252; font-size: 11px; font-weight: bold;")
                self.timeline_widget.add_event(
                    TimelineEvent(
                        event_type=TimelineEventType.ERROR,
                        title="Window Capture Failed",
                        description=str(e),
                        status=TimelineEventStatus.FAILED,
                    )
                )
                QMessageBox.critical(
                    self,
                    "Window Capture Failed",
                    f"Failed to capture selected application window:\n\n{e}\n\n"
                    "Please ensure the application window is open, unminimized, and visible on your screen.",
                )
                return

        b64_jpeg, meta = approved
        provider_name = settings.ai_provider.upper()

        self.orb_container.set_state(OrbState.THINKING, f"Transmitting approved frame to {provider_name}...")
        self.timeline_widget.add_event(
            TimelineEvent(
                event_type=TimelineEventType.ANALYZE,
                title="AI Vision Analysis Started",
                description=f"Sending approved frame to {provider_name} ({settings.gemini_model})...",
                status=TimelineEventStatus.IN_PROGRESS,
            )
        )

        self.ai_thread = AIAnalysisThread(
            ai_engine=self.ai_engine,
            image_base64=b64_jpeg,
            worker_id=self.capture_service.worker_id,
            additional_prompt=additional_prompt,
            parent=self,
        )
        self.ai_thread.analysis_complete.connect(self.on_ai_analysis_complete)
        self.ai_thread.analysis_error.connect(self.on_ai_analysis_error)
        self.ai_thread.start()

    def on_ai_analysis_complete(self, result: CodingAnalysisResult) -> None:
        """Handle structured result: update orb to responding and populate coding workspace."""
        self.orb_container.set_state(OrbState.RESPONDING, f"Analysis complete: '{result.problem_title}'")
        self.workspace_widget.populate_results(result)

        self.timeline_widget.add_event(
            TimelineEvent(
                event_type=TimelineEventType.ANALYZE,
                title="Coding Task Recognized",
                description=f"'{result.problem_title}' [{result.programming_language or 'Python'}]. Concepts: {', '.join(result.relevant_concepts[:3])}",
                status=TimelineEventStatus.SUCCESS,
            )
        )

        if not self.workspace_widget.isVisible():
            self.on_toggle_workspace()

    def on_ai_analysis_error(self, error_message: str) -> None:
        """Handle AI analysis failure gracefully."""
        self.orb_container.set_state(OrbState.ERROR, f"AI Error: {error_message}")
        self.timeline_widget.add_event(
            TimelineEvent(
                event_type=TimelineEventType.ERROR,
                title="AI Analysis Error",
                description=error_message,
                status=TimelineEventStatus.FAILED,
            )
        )
        QMessageBox.critical(
            self,
            "AI Analysis Failed",
            f"An error occurred during Gemini AI screen analysis:\n\n{error_message}\n\n"
            "Please check your API key, network connection, or try again.",
        )
        QTimer.singleShot(4000, lambda: self.orb_container.set_state(OrbState.IDLE))

    # -------------------------------------------------------------
    # Keyboard Computer-Use Interaction (No Clipboard Paste)
    # -------------------------------------------------------------
    def on_type_code_clicked(self) -> None:
        """Authorize and execute keyboard code entry into the focused editor in controlled chunks."""
        if not self.consent_checkbox.isChecked():
            QMessageBox.warning(
                self,
                "Permission Required",
                "Explicit student permission must be active before typing code.",
            )
            return

        target_hwnd = self.capture_service.target_hwnd
        target_title = self.capture_service.target_window_title or self.window_combo.currentText()

        if not target_hwnd:
            QMessageBox.warning(
                self,
                "Target Required",
                "Please select an application window (e.g. Google Chrome or Practice Bed) first.",
            )
            return

        # Obtain code to type
        code_to_type = ""
        if self.workspace_widget._current_result and self.workspace_widget._current_result.suggested_code:
            code_to_type = self.workspace_widget._current_result.suggested_code
        else:
            # Default practice algorithm if workspace hasn't run yet
            code_to_type = (
                "def solve(nums):\n"
                "    \"\"\"Generated by NIAT CodePilot Computer-Use Agent.\"\"\"\n"
                "    total = 0\n"
                "    for x in nums:\n"
                "        total += x\n"
                "    return total\n"
            )

        # Safety Confirmation Dialog: Student retains 100% control
        reply = QMessageBox.question(
            self,
            "Authorize Keyboard Code Entry",
            f"Do you want NIAT CodePilot to type the solution into:\n'{target_title}'?\n\n"
            "• ZERO clipboard paste: Keystrokes are sent via Windows SendInput.\n"
            "• Controlled chunks: Verified focus before and after each chunk.\n"
            "• Instant stop: Typing halts immediately if editor loses focus or STOP is pressed.\n"
            "• Student control: Code execution and final portal submission are NEVER automated.\n\n"
            "Proceed with keyboard typing?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self.timeline_widget.add_event(
                TimelineEvent(
                    event_type=TimelineEventType.VERIFY,
                    title="Typing Cancelled",
                    description="Student declined keyboard code entry",
                    status=TimelineEventStatus.WARNING,
                )
            )
            return

        self.orb_container.set_state(OrbState.ANALYZING_SCREEN, "Focusing editor & initiating keyboard entry...")

        self.typing_thread = InteractiveTypingWorkerThread(
            target_hwnd=target_hwnd,
            target_title=target_title,
            code_to_type=code_to_type,
            parent=self,
        )
        self.typing_thread.timeline_event_signal.connect(self.on_typing_timeline_event)
        self.typing_thread.typing_complete.connect(self.on_typing_complete)
        self.typing_thread.typing_error.connect(self.on_typing_error)
        self.typing_thread.start()

    def on_typing_timeline_event(self, event: TimelineEvent) -> None:
        """Route typing events to the Action Timeline and update the Orb state."""
        self.timeline_widget.add_event(event)
        if event.event_type == TimelineEventType.TYPE_CHUNK:
            pct = event.metadata.get("progress_pct", 50)
            self.orb_container.set_state(OrbState.ANALYZING_SCREEN, f"Typing code via keyboard... ({pct}%)")

    def on_typing_complete(self, success: bool) -> None:
        if success:
            self.orb_container.set_state(OrbState.RESPONDING, "Keyboard entry completed. Ready for student review.")
            QMessageBox.information(
                self,
                "Keyboard Entry Complete",
                "CodePilot has finished typing the solution into your editor.\n\n"
                "• All code was typed directly via keyboard input.\n"
                "• Please review your code, run local test cases, and make any adjustments before submitting.",
            )
        else:
            self.orb_container.set_state(OrbState.IDLE)

    def on_typing_error(self, error_message: str) -> None:
        self.orb_container.set_state(OrbState.ERROR, f"Typing halted: {error_message}")
        self.timeline_widget.add_event(
            TimelineEvent(
                event_type=TimelineEventType.ERROR,
                title="Typing Interrupted",
                description=error_message,
                status=TimelineEventStatus.FAILED,
            )
        )
        QMessageBox.warning(
            self,
            "Typing Halted",
            f"Keyboard code entry was halted:\n\n{error_message}\n\n"
            "Safety invariant preserved: Typing stops whenever editor focus changes or an error occurs.",
        )

    def closeEvent(self, event) -> None:
        """Ensure all background worker threads and timers stop cleanly on close."""
        logger.info("Closing NIAT CodePilot Desktop Application...")
        try:
            self.preview_timer.stop()
            self.observe_timer.stop()

            if self.typing_thread and self.typing_thread.isRunning():
                self.typing_thread.stop()
                self.typing_thread.wait(1000)

            if self.ai_thread and self.ai_thread.isRunning():
                self.ai_thread.wait(1000)

            if self.heartbeat_thread and self.heartbeat_thread.isRunning():
                self.heartbeat_thread.stop()
                self.heartbeat_thread.wait(1000)

            self.capture_service.stop()

            if self.practice_editor is not None:
                self.practice_editor.close()
        except Exception as e:
            logger.warning(f"Error during clean shutdown: {e}")

        try:
            super().closeEvent(event)
        except TypeError:
            if hasattr(event, "accept"):
                event.accept()


def main() -> int:
    """Entry point to run the PySide6 desktop interface for NIAT CodePilot Worker."""
    logger.info("Initializing NIAT CodePilot Desktop Application...")
    try:
        # Reuse existing QApplication if already running (e.g. in test fixtures), otherwise create one
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        app.setApplicationName("NIAT CodePilot")
        app.setOrganizationName("NIAT")

        window = MainWindow()
        window.show()

        logger.info("NIAT CodePilot GUI event loop started.")
        return app.exec()
    except Exception as e:
        logger.exception(f"Fatal error during NIAT CodePilot desktop application startup: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
