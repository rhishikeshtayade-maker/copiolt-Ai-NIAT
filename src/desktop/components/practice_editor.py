"""Local Practice Code Editor for testing computer-use keyboard interaction.

Provides an authorized local environment to verify:
1. Screen recognition
2. Editor focus detection
3. Real keyboard typing (no clipboard paste)
4. Code comparison
5. Focus-loss error recovery
6. Emergency Stop
"""

from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PracticeEditorWindow(QMainWindow):
    """Dedicated local practice editor window for safe, authorized computer-use testing."""

    text_changed_signal = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("NIAT Local Practice Editor — Authorized Practice Environment")
        self.resize(750, 520)
        self._init_ui()
        self._apply_editor_styles()

    def _init_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Top Control Bar
        top_bar = QHBoxLayout()

        status_dot = QLabel("●", self)
        status_dot.setObjectName("FocusDot")
        status_dot.setStyleSheet("color: #00E676; font-size: 14px;")
        top_bar.addWidget(status_dot)

        self.focus_label = QLabel("Focus Status: Active (Click here to focus)", self)
        self.focus_label.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 12px;")
        top_bar.addWidget(self.focus_label)

        top_bar.addStretch()

        self.clear_btn = QPushButton("Clear Editor", self)
        self.clear_btn.clicked.connect(self.clear_text)
        top_bar.addWidget(self.clear_btn)

        layout.addLayout(top_bar)

        # Main Code Text Area
        self.editor = QPlainTextEdit(self)
        self.editor.setPlaceholderText(
            "# NIAT Local Practice Editor\n"
            "# 1. Select this window in CodePilot Target Dropdown\n"
            "# 2. Click '🤖 Type into Editor'\n"
            "# 3. Watch CodePilot type the code line-by-line via SendInput (no clipboard paste)\n"
            "# 4. Click outside to test focus-loss safety stop"
        )
        self.editor.setFont(QFont("Consolas", 12))
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor, 1)

        # Bottom Info Bar
        bottom_bar = QHBoxLayout()

        self.stats_label = QLabel("Characters: 0 | Lines: 1", self)
        self.stats_label.setStyleSheet("color: #8E9DB8; font-size: 11px;")
        bottom_bar.addWidget(self.stats_label)

        bottom_bar.addStretch()

        policy_note = QLabel("✓ Authorized Local Test Bed • No assessment restrictions bypassed", self)
        policy_note.setStyleSheet("color: #00E676; font-size: 10px; font-weight: bold;")
        bottom_bar.addWidget(policy_note)

        layout.addLayout(bottom_bar)

    def _apply_editor_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #0B0E17;
            }
            QPlainTextEdit {
                background-color: #0D121F;
                color: #A7FFEB;
                border: 1px solid rgba(0, 229, 255, 0.25);
                border-radius: 8px;
                padding: 10px;
                font-family: 'Consolas', 'JetBrains Mono', monospace;
            }
            QPushButton {
                background-color: rgba(26, 34, 52, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.15);
                color: #E2E8F0;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(41, 121, 255, 0.35);
                color: #FFFFFF;
                border-color: #00E5FF;
            }
            """
        )

    def _on_text_changed(self) -> None:
        text = self.editor.toPlainText()
        chars = len(text)
        lines = text.count("\n") + 1 if text else 1
        self.stats_label.setText(f"Characters: {chars} | Lines: {lines}")
        self.text_changed_signal.emit(text)

    def clear_text(self) -> None:
        self.editor.clear()

    def get_text(self) -> str:
        return self.editor.toPlainText()

    def set_text(self, text: str) -> None:
        self.editor.setPlainText(text)

    set_editor_text = set_text

    @property
    def character_count(self) -> int:
        return len(self.editor.toPlainText())

    @property
    def line_count(self) -> int:
        text = self.editor.toPlainText()
        return text.count("\n") + 1 if text else 1

    def compare_code(self, expected_code: str) -> dict:
        """Compare current editor content against expected code."""
        import difflib
        actual = self.editor.toPlainText().strip()
        expected = expected_code.strip()
        match = actual == expected
        similarity = 1.0 if match else difflib.SequenceMatcher(None, actual, expected).ratio()
        return {
            "exact_match": match,
            "match_ratio": similarity,
            "similarity_ratio": similarity,
            "actual_len": len(actual),
            "expected_len": len(expected),
            "editor_chars": len(actual),
            "expected_chars": len(expected),
            "diff": "" if match else f"Expected: {expected[:50]}... Actual: {actual[:50]}...",
        }
