"""Unit tests for the Approved Premium UI components and state transitions."""

import pytest
from PySide6.QtWidgets import QApplication

# Ensure single QApplication instance for Qt unit testing
_qapp = QApplication.instance() or QApplication([])

from src.desktop.components.ai_orb import AIOrbContainer, AIOrbWidget, OrbState
from src.desktop.components.floating_controls import FloatingControlsDock
from src.desktop.components.coding_workspace import CodingWorkspaceWidget
from src.common.schemas import CodingAnalysisResult, EdgeCase


class TestAIOrbWidget:
    def test_orb_state_transitions(self):
        """Verify the central AI Orb transitions smoothly across all required states."""
        orb = AIOrbWidget()
        assert orb.state == OrbState.IDLE

        for state in (
            OrbState.LISTENING,
            OrbState.THINKING,
            OrbState.ANALYZING_SCREEN,
            OrbState.RESPONDING,
            OrbState.ERROR,
            OrbState.IDLE,
        ):
            orb.set_state(state)
            assert orb.state == state

    def test_orb_container_synchronization(self):
        """Verify the container synchronizes badge text and subtitles with orb state."""
        container = AIOrbContainer()
        assert container.orb.state == OrbState.IDLE
        assert "READY" in container.status_badge.text()

        container.set_state(OrbState.LISTENING)
        assert container.orb.state == OrbState.LISTENING
        assert "LISTENING" in container.status_badge.text()

        container.set_state(OrbState.THINKING)
        assert container.orb.state == OrbState.THINKING
        assert "THINKING" in container.status_badge.text()

        container.set_state(OrbState.ANALYZING_SCREEN)
        assert container.orb.state == OrbState.ANALYZING_SCREEN
        assert "ANALYZING" in container.status_badge.text()

        container.set_state(OrbState.RESPONDING)
        assert container.orb.state == OrbState.RESPONDING
        assert "SOLUTION READY" in container.status_badge.text()

        container.set_state(OrbState.ERROR)
        assert container.orb.state == OrbState.ERROR
        assert "ALERT" in container.status_badge.text()


class TestFloatingControlsDock:
    def test_controls_signals_and_actions(self):
        """Verify the floating control dock buttons and signal dispatch."""
        dock = FloatingControlsDock()

        # 1. Voice toggle
        voice_events = []
        dock.voice_toggled.connect(lambda v: voice_events.append(v))
        dock.mic_btn.click()
        assert len(voice_events) == 1
        assert voice_events[0] is True
        dock.mic_btn.click()
        assert len(voice_events) == 2
        assert voice_events[1] is False

        # 2. Text prompt submission
        prompt_events = []
        dock.text_prompt_submitted.connect(lambda p: prompt_events.append(p))
        dock.prompt_edit.setText("Explain dynamic programming")
        dock.send_btn.click()
        assert prompt_events == ["Explain dynamic programming"]
        assert dock.prompt_edit.text() == ""

        # 3. Workspace toggle
        ws_events = []
        dock.toggle_workspace_clicked.connect(lambda: ws_events.append(True))
        dock.workspace_btn.click()
        assert len(ws_events) == 1
        assert "Hide Workspace" in dock.workspace_btn.text()

        # 4. Pause / Resume toggle
        pause_events = []
        dock.pause_resume_clicked.connect(lambda: pause_events.append(True))
        dock.pause_resume_btn.click()
        assert len(pause_events) == 1
        assert "Resume" in dock.pause_resume_btn.text()

        # 5. Emergency Stop
        stop_events = []
        dock.emergency_stop_clicked.connect(lambda: stop_events.append(True))
        dock.emergency_btn.click()
        assert len(stop_events) == 1


class TestCodingWorkspaceWidget:
    def test_workspace_population(self):
        """Verify the structured workspace renders all required problem and algorithmic sections."""
        workspace = CodingWorkspaceWidget()

        result = CodingAnalysisResult(
            problem_title="Median of Two Sorted Arrays",
            problem_description="Given two sorted arrays nums1 and nums2, return the median.",
            programming_language="Python 3",
            constraints=["nums1.length + nums2.length <= 2000", "-10^6 <= nums1[i] <= 10^6"],
            input_format="nums1 = [1,3], nums2 = [2]",
            output_format="2.00000",
            sample_inputs=["[1,3], [2]"],
            sample_outputs=["2.0"],
            relevant_concepts=["Binary Search", "Divide and Conquer"],
            step_by_step_explanation=[
                "Step 1: Partition arrays using binary search.",
                "Step 2: Ensure left partition elements are smaller than right.",
            ],
            suggested_code="def findMedianSortedArrays(nums1, nums2):\n    pass",
            code_explanation="Run binary search on the shorter array in O(log(min(M, N))) time.",
            edge_cases=[
                EdgeCase(
                    description="One array is empty",
                    example_input="nums1=[], nums2=[1]",
                    expected_behavior="Return median of single array",
                )
            ],
            confidence_note="High confidence algorithmic extraction",
        )

        workspace.populate_results(result)

        assert "Median of Two Sorted Arrays" in workspace.title_label.text()
        assert "Python 3" in workspace.lang_badge.text()
        assert "Given two sorted arrays" in workspace.desc_text.toPlainText()
        assert "Binary Search" in workspace.hints_text.toPlainText()
        assert "Step 1" in workspace.approach_text.toPlainText()
        assert "findMedianSortedArrays" in workspace.code_text.toPlainText()
        assert "One array is empty" in workspace.edge_cases_text.toPlainText()
