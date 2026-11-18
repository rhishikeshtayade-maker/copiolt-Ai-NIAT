"""Floating Assistant Controls Dock with glassmorphism design."""

from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class FloatingControlsDock(QFrame):
    """Compact, floating glass control dock providing instant access to CodePilot actions:
    - Microphone / Voice interaction toggle
    - Quick text prompt input bar
    - Analyze Current Coding Question (Primary 1-click trigger)
    - Keyboard-based Type into Editor (Computer-use agent)
    - Local Practice Editor (Safe test bed)
    - Expand / Collapse Coding Workspace
    - Continuous Screen Observation Toggle
    - Pause / Resume screen capture
    - Emergency Stop
    """

    voice_toggled = Signal(bool)                  # is_active
    text_prompt_submitted = Signal(str)            # prompt_text
    analyze_clicked = Signal()
    type_code_clicked = Signal()                   # Trigger keyboard text entry
    open_practice_editor_clicked = Signal()        # Open local test bed
    continuous_observe_toggled = Signal(bool)      # Toggle continuous observation
    toggle_workspace_clicked = Signal()
    pause_resume_clicked = Signal()
    emergency_stop_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("FloatingControlsDock")
        self._is_listening: bool = False
        self._is_paused: bool = False
        self._workspace_expanded: bool = False
        self._is_observing: bool = False

        self._init_ui()
        self._apply_glass_styles()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # -------------------------------------------------------------
        # Row 1: Quick Text Conversation Bar + Voice Mic
        # -------------------------------------------------------------
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        # Voice interaction button
        self.mic_btn = QPushButton("🎙️", self)
        self.mic_btn.setFixedSize(42, 42)
        self.mic_btn.setToolTip("Toggle Voice / Audio Interaction Mode")
        self.mic_btn.setCheckable(True)
        self.mic_btn.clicked.connect(self._on_mic_clicked)
        input_row.addWidget(self.mic_btn)

        # Text conversation input
        self.prompt_edit = QLineEdit(self)
        self.prompt_edit.setPlaceholderText("Ask CodePilot: e.g. 'Explain time complexity', 'Give a hint'...")
        self.prompt_edit.setFixedHeight(42)
        self.prompt_edit.returnPressed.connect(self._on_text_submitted)
        input_row.addWidget(self.prompt_edit, 1)

        # Send prompt button
        self.send_btn = QPushButton("Send", self)
        self.send_btn.setFixedHeight(42)
        self.send_btn.setFixedWidth(75)
        self.send_btn.clicked.connect(self._on_text_submitted)
        input_row.addWidget(self.send_btn)

        main_layout.addLayout(input_row)

        # -------------------------------------------------------------
        # Row 2: Action Control Pills
        # -------------------------------------------------------------
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        # 1. Primary Analyze Screen button
        self.analyze_btn = QPushButton("🧠  Analyze Question", self)
        self.analyze_btn.setFixedHeight(42)
        self.analyze_btn.setToolTip("Capture approved NIAT / Chrome window frame and run Gemini vision analysis")
        self.analyze_btn.clicked.connect(self.analyze_clicked.emit)
        action_row.addWidget(self.analyze_btn, 2)

        # 2. Type into Editor button (Keyboard Computer-Use Agent)
        self.type_btn = QPushButton("⌨️  Type Code", self)
        self.type_btn.setFixedHeight(42)
        self.type_btn.setToolTip("Type generated solution into focused practice editor via keyboard (no clipboard paste)")
        self.type_btn.clicked.connect(self.type_code_clicked.emit)
        action_row.addWidget(self.type_btn, 2)

        # 3. Practice Editor launcher
        self.practice_btn = QPushButton("🎯  Practice Bed", self)
        self.practice_btn.setFixedHeight(42)
        self.practice_btn.setToolTip("Open local practice editor to verify typing, focus loss & emergency stop")
        self.practice_btn.clicked.connect(self.open_practice_editor_clicked.emit)
        action_row.addWidget(self.practice_btn, 1)

        # 4. Continuous Observation toggle
        self.observe_btn = QPushButton("👁️  Observe: Off", self)
        self.observe_btn.setFixedHeight(42)
        self.observe_btn.setCheckable(True)
        self.observe_btn.setToolTip("Toggle continuous consent-based screen observation")
        self.observe_btn.clicked.connect(self._on_observe_clicked)
        action_row.addWidget(self.observe_btn, 1)

        # 5. Expand / Collapse Workspace button
        self.workspace_btn = QPushButton("📂  Workspace", self)
        self.workspace_btn.setFixedHeight(42)
        self.workspace_btn.setToolTip("Expand or collapse structured algorithmic workspace")
        self.workspace_btn.clicked.connect(self._on_toggle_workspace)
        action_row.addWidget(self.workspace_btn, 1)

        # 6. Pause / Resume Screen Capture button
        self.pause_resume_btn = QPushButton("⏸️  Pause", self)
        self.pause_resume_btn.setFixedHeight(42)
        self.pause_resume_btn.setToolTip("Temporarily pause screen capture without stopping worker")
        self.pause_resume_btn.clicked.connect(self._on_pause_resume)
        action_row.addWidget(self.pause_resume_btn, 1)

        # 7. Emergency Stop button
        self.emergency_btn = QPushButton("🚨  STOP", self)
        self.emergency_btn.setFixedHeight(42)
        self.emergency_btn.setFixedWidth(85)
        self.emergency_btn.setToolTip("EMERGENCY STOP: Instantly terminate all captures and revoke consent")
        self.emergency_btn.clicked.connect(self.emergency_stop_clicked.emit)
        action_row.addWidget(self.emergency_btn)

        main_layout.addLayout(action_row)

    def _apply_glass_styles(self) -> None:
        self.setStyleSheet(
            """
            #FloatingControlsDock {
                background-color: rgba(18, 24, 38, 0.85);
                border: 1px solid rgba(0, 229, 255, 0.20);
                border-radius: 16px;
            }
            QLineEdit {
                background-color: rgba(11, 15, 25, 0.75);
                border: 1px solid rgba(0, 229, 255, 0.25);
                border-radius: 10px;
                color: #FFFFFF;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 13px;
                padding: 0 14px;
            }
            QLineEdit:focus {
                border: 1px solid #00E5FF;
                background-color: rgba(16, 22, 38, 0.90);
            }
            QPushButton {
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 12px;
                font-weight: 600;
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: #E2E8F0;
                background-color: rgba(26, 34, 52, 0.80);
            }
            QPushButton:hover {
                background-color: rgba(38, 48, 74, 0.90);
                border-color: rgba(0, 229, 255, 0.40);
                color: #FFFFFF;
            }
            QPushButton:pressed {
                background-color: rgba(20, 26, 42, 0.95);
            }
            """
        )

        self.mic_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(26, 34, 52, 0.80);
                border: 1px solid rgba(0, 229, 255, 0.30);
                border-radius: 10px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 0.20);
                border-color: #00E5FF;
            }
            QPushButton:checked {
                background-color: rgba(0, 229, 255, 0.35);
                border: 2px solid #00E5FF;
            }
            """
        )

        self.send_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2979FF;
                border: 1px solid #82B1FF;
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: #1565C0;
                border-color: #00E5FF;
            }
            """
        )

        self.analyze_btn.setStyleSheet(
            """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2979FF, stop:1 #7C4DFF);
                border: 1px solid rgba(179, 136, 255, 0.60);
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 10px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E88E5, stop:1 #651FFF);
                border-color: #00E5FF;
            }
            """
        )

        self.type_btn.setStyleSheet(
            """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(0, 229, 255, 0.30), stop:1 rgba(41, 121, 255, 0.35));
                border: 1px solid rgba(0, 229, 255, 0.50);
                color: #00E5FF;
                font-weight: bold;
                border-radius: 10px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: rgba(0, 229, 255, 0.40);
                color: #FFFFFF;
                border-color: #00E5FF;
            }
            """
        )

        self.observe_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(26, 34, 52, 0.80);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 10px;
            }
            QPushButton:checked {
                background-color: rgba(0, 230, 118, 0.25);
                border: 1px solid #00E676;
                color: #00E676;
            }
            """
        )

        self.emergency_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(211, 47, 47, 0.85);
                border: 1px solid #FF5252;
                color: #FFFFFF;
                font-weight: bold;
                font-size: 11px;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: #C62828;
                border-color: #FF1744;
            }
            """
        )

    def _on_mic_clicked(self) -> None:
        self._is_listening = self.mic_btn.isChecked()
        self.voice_toggled.emit(self._is_listening)

    def _on_text_submitted(self) -> None:
        text = self.prompt_edit.text().strip()
        if text:
            self.text_prompt_submitted.emit(text)
            self.prompt_edit.clear()

    def _on_observe_clicked(self) -> None:
        self._is_observing = self.observe_btn.isChecked()
        self.observe_btn.setText("👁️  Observe: On" if self._is_observing else "👁️  Observe: Off")
        self.continuous_observe_toggled.emit(self._is_observing)

    def _on_toggle_workspace(self) -> None:
        self._workspace_expanded = not self._workspace_expanded
        self.workspace_btn.setText("📁  Hide Workspace" if self._workspace_expanded else "📂  Workspace")
        self.toggle_workspace_clicked.emit()

    def _on_pause_resume(self) -> None:
        self._is_paused = not self._is_paused
        self.pause_resume_btn.setText("▶️  Resume" if self._is_paused else "⏸️  Pause")
        self.pause_resume_clicked.emit()

    def set_paused_state(self, is_paused: bool) -> None:
        self._is_paused = is_paused
        self.pause_resume_btn.setText("▶️  Resume" if is_paused else "⏸️  Pause")

    def set_workspace_expanded(self, expanded: bool) -> None:
        self._workspace_expanded = expanded
        self.workspace_btn.setText("📁  Hide Workspace" if expanded else "📂  Workspace")

    def set_listening_state(self, listening: bool) -> None:
        self._is_listening = listening
        self.mic_btn.setChecked(listening)
