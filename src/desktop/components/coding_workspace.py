"""Expandable Structured Coding Workspace displaying AI analysis."""

from typing import Optional
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.common.schemas import CodingAnalysisResult


class CodingWorkspaceWidget(QFrame):
    """Clean, readable, structured coding workspace displaying deep algorithmic guidance:
    - Detected problem title & language tag
    - Problem description
    - Input / Output format
    - Constraints and sample cases
    - Solution approach & step-by-step walkthrough
    - Hints & concept tags
    - Code review & suggested solution with 1-click copy
    - Debugging guidance & edge case analysis
    - Time and space complexity metrics
    """

    close_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("CodingWorkspace")
        self._current_result: Optional[CodingAnalysisResult] = None
        self._init_ui()
        self._apply_glass_styles()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # -------------------------------------------------------------
        # Header: Problem Title & Language & Complexity Badges
        # -------------------------------------------------------------
        header_row = QHBoxLayout()

        self.title_label = QLabel("No Problem Analyzed Yet", self)
        self.title_label.setStyleSheet("color: #FFFFFF; font-size: 16px; font-weight: bold;")
        self.title_label.setWordWrap(True)
        header_row.addWidget(self.title_label, 1)

        self.lang_badge = QLabel("Language: Auto", self)
        self.lang_badge.setStyleSheet(
            """
            QLabel {
                background-color: rgba(41, 121, 255, 0.20);
                color: #82B1FF;
                border: 1px solid rgba(41, 121, 255, 0.40);
                border-radius: 8px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            """
        )
        header_row.addWidget(self.lang_badge)

        self.complexity_badge = QLabel("Complexity: Pending", self)
        self.complexity_badge.setStyleSheet(
            """
            QLabel {
                background-color: rgba(124, 77, 255, 0.20);
                color: #D1C4E9;
                border: 1px solid rgba(124, 77, 255, 0.40);
                border-radius: 8px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            """
        )
        header_row.addWidget(self.complexity_badge)

        # Close/Collapse workspace button
        self.close_btn = QPushButton("✕", self)
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setToolTip("Collapse Workspace")
        self.close_btn.clicked.connect(self.close_requested.emit)
        self.close_btn.setStyleSheet(
            """
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                color: #A0AEC0;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 23, 68, 0.35);
                color: #FFFFFF;
            }
            """
        )
        header_row.addWidget(self.close_btn)

        layout.addLayout(header_row)

        # -------------------------------------------------------------
        # Tabbed Workspace
        # -------------------------------------------------------------
        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: 1px solid rgba(0, 229, 255, 0.15);
                background: rgba(14, 19, 32, 0.85);
                border-radius: 10px;
            }
            QTabBar::tab {
                background: rgba(20, 26, 42, 0.70);
                color: #94A3B8;
                padding: 7px 16px;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 3px;
                font-weight: 600;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background: rgba(14, 19, 32, 0.95);
                color: #00E5FF;
                border: 1px solid rgba(0, 229, 255, 0.30);
                border-bottom: none;
            }
            QTabBar::tab:hover {
                background: rgba(30, 38, 60, 0.85);
                color: #FFFFFF;
            }
            """
        )

        # Tab 1: Overview & Format
        tab_overview = QWidget()
        v_over = QVBoxLayout(tab_overview)
        v_over.setContentsMargins(12, 12, 12, 12)
        v_over.setSpacing(8)

        v_over.addWidget(QLabel("Problem Statement & Requirements:", self))
        self.desc_text = QTextEdit(self)
        self.desc_text.setReadOnly(True)
        self.desc_text.setPlaceholderText("Select your NIAT portal Chrome window and click 'Analyze Question'...")
        v_over.addWidget(self.desc_text, 2)

        v_over.addWidget(QLabel("Input / Output Format & Constraints:", self))
        self.format_text = QTextEdit(self)
        self.format_text.setReadOnly(True)
        self.format_text.setMaximumHeight(140)
        v_over.addWidget(self.format_text, 1)

        self.tabs.addTab(tab_overview, "📋 Overview & Constraints")

        # Tab 2: Solution Approach & Hints
        tab_solution = QWidget()
        v_sol = QVBoxLayout(tab_solution)
        v_sol.setContentsMargins(12, 12, 12, 12)
        v_sol.setSpacing(8)

        v_sol.addWidget(QLabel("Step-by-Step Algorithmic Approach:", self))
        self.approach_text = QTextEdit(self)
        self.approach_text.setReadOnly(True)
        v_sol.addWidget(self.approach_text, 2)

        v_sol.addWidget(QLabel("Key Concepts & Hints:", self))
        self.hints_text = QTextEdit(self)
        self.hints_text.setReadOnly(True)
        self.hints_text.setMaximumHeight(120)
        v_sol.addWidget(self.hints_text, 1)

        self.tabs.addTab(tab_solution, "💡 Approach & Hints")

        # Tab 3: Code Review & Suggested Implementation
        tab_code = QWidget()
        v_code = QVBoxLayout(tab_code)
        v_code.setContentsMargins(12, 12, 12, 12)
        v_code.setSpacing(8)

        code_top = QHBoxLayout()
        code_top.addWidget(QLabel("Suggested Implementation (Review Before Using):", self), 1)

        self.copy_btn = QPushButton("📋 Copy Code", self)
        self.copy_btn.setFixedSize(100, 28)
        self.copy_btn.clicked.connect(self._copy_code)
        self.copy_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(41, 121, 255, 0.25);
                border: 1px solid rgba(41, 121, 255, 0.50);
                color: #82B1FF;
                font-size: 11px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #2979FF;
                color: #FFFFFF;
            }
            """
        )
        code_top.addWidget(self.copy_btn)
        v_code.addLayout(code_top)

        self.code_text = QTextEdit(self)
        self.code_text.setReadOnly(True)
        self.code_text.setFont(QFont("Consolas", 11))
        self.code_text.setStyleSheet(
            """
            QTextEdit {
                background-color: #0A0D14;
                color: #A7FFEB;
                border: 1px solid rgba(0, 229, 255, 0.20);
                border-radius: 8px;
                font-family: 'Consolas', 'JetBrains Mono', monospace;
                padding: 10px;
            }
            """
        )
        v_code.addWidget(self.code_text, 2)

        v_code.addWidget(QLabel("Code Explanation & Review Notes:", self))
        self.code_review_text = QTextEdit(self)
        self.code_review_text.setReadOnly(True)
        self.code_review_text.setMaximumHeight(110)
        v_code.addWidget(self.code_review_text, 1)

        self.tabs.addTab(tab_code, "💻 Code Review")

        # Tab 4: Debugging & Edge Cases
        tab_debug = QWidget()
        v_deb = QVBoxLayout(tab_debug)
        v_deb.setContentsMargins(12, 12, 12, 12)
        v_deb.setSpacing(8)

        v_deb.addWidget(QLabel("Critical Edge Cases & Boundary Conditions:", self))
        self.edge_cases_text = QTextEdit(self)
        self.edge_cases_text.setReadOnly(True)
        v_deb.addWidget(self.edge_cases_text, 2)

        v_deb.addWidget(QLabel("Debugging Advice & Verification Checklist:", self))
        self.debug_advice_text = QTextEdit(self)
        self.debug_advice_text.setReadOnly(True)
        self.debug_advice_text.setMaximumHeight(130)
        v_deb.addWidget(self.debug_advice_text, 1)

        self.tabs.addTab(tab_debug, "🐛 Edge Cases & Debugging")

        layout.addWidget(self.tabs, 1)

    def _apply_glass_styles(self) -> None:
        self.setStyleSheet(
            """
            #CodingWorkspace {
                background-color: rgba(12, 17, 28, 0.90);
                border: 1px solid rgba(0, 229, 255, 0.20);
                border-radius: 16px;
            }
            QLabel {
                color: #CBD5E1;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 12px;
                font-weight: 600;
            }
            QTextEdit {
                background-color: rgba(18, 24, 38, 0.70);
                color: #E2E8F0;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 12px;
                padding: 8px;
            }
            QTextEdit:focus {
                border: 1px solid rgba(0, 229, 255, 0.35);
            }
            """
        )

    def populate_results(self, result: CodingAnalysisResult) -> None:
        """Populate the workspace cards from structured AI results."""
        self._current_result = result

        # 1. Title & badges
        self.title_label.setText(f"📋 {result.problem_title}")
        lang = result.programming_language or "General"
        self.lang_badge.setText(f"Language: {lang}")

        # Complexity derivation from explanation or fallback
        time_c = "O(N)"
        space_c = "O(1)"
        if result.code_explanation and "O(" in result.code_explanation:
            parts = [p.strip() for p in result.code_explanation.split() if "O(" in p]
            if parts:
                time_c = parts[0]
        self.complexity_badge.setText(f"Complexity: {time_c} / {space_c}")

        # 2. Problem description
        self.desc_text.setPlainText(result.problem_description or "No problem description extracted.")

        # 3. Input / Output format & constraints
        format_lines = []
        if result.input_format:
            format_lines.append(f"Input Format: {result.input_format}")
        if result.output_format:
            format_lines.append(f"Output Format: {result.output_format}")
        if result.constraints:
            format_lines.append("\nConstraints:")
            for c in result.constraints:
                format_lines.append(f"  • {c}")
        if result.sample_inputs or result.sample_outputs:
            format_lines.append("\nSample Cases:")
            for i, (si, so) in enumerate(zip(result.sample_inputs or [], result.sample_outputs or [])):
                format_lines.append(f"  Sample {i+1}: Input = {si}  ->  Output = {so}")
        self.format_text.setPlainText("\n".join(format_lines) if format_lines else "Standard input/output.")

        # 4. Approach & hints
        if result.step_by_step_explanation:
            self.approach_text.setPlainText("\n\n".join(result.step_by_step_explanation))
        else:
            self.approach_text.setPlainText("Review the problem constraints and edge cases.")

        hints = []
        if result.relevant_concepts:
            hints.append("Relevant Concepts: " + ", ".join(result.relevant_concepts))
        hints.append(result.confidence_note or "Confidence: High")
        self.hints_text.setPlainText("\n\n".join(hints))

        # 5. Code & review
        self.code_text.setPlainText(result.suggested_code or "# No code provided")
        self.code_review_text.setPlainText(result.code_explanation or "Review algorithmic invariants.")

        # 6. Edge cases & debugging
        if result.edge_cases:
            edge_lines = []
            for ec in result.edge_cases:
                edge_lines.append(f"• {ec.description}: Input '{ec.example_input}' -> Expected: '{ec.expected_behavior}'")
            self.edge_cases_text.setPlainText("\n".join(edge_lines))
        else:
            self.edge_cases_text.setPlainText("Check single elements, empty inputs, and large inputs.")

        self.debug_advice_text.setPlainText(
            "Security Policy Reminder: Student must independently review, test, and type code. "
            "Automated portal submission is strictly disabled by policy."
        )

    def _copy_code(self) -> None:
        """Copy suggested code to clipboard."""
        code = self.code_text.toPlainText()
        if code:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(code)
            self.copy_btn.setText("✓ Copied!")
            QTimer.singleShot(1800, lambda: self.copy_btn.setText("📋 Copy Code"))
