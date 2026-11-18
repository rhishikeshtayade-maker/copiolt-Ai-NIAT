"""Unit and integration tests for AI Computer-Use Agent and Keyboard Interaction.

Verifies:
1. Native SendInput execution using KEYEVENTF_UNICODE (Zero clipboard paste).
2. Foreground focus verification with root ancestor tracking.
3. Controlled chunk typing and inter-chunk verification.
4. Editor focus loss detection and instant abort.
5. Emergency stop detection and instant abort.
6. Pause / resume suspension and timeline event emission.
7. Local practice editor code comparison utility.
"""

import time
from unittest.mock import MagicMock, patch, call
import pytest

from src.worker.interaction import (
    EditorFocusLostError,
    EmergencyStopError,
    KeyboardComputerUseAgent,
    TimelineEvent,
    TimelineEventType,
    TimelineEventStatus,
    activate_window,
    get_foreground_window_title,
    is_window_focused,
    send_backspace,
    send_unicode_char,
    VK_RETURN,
    VK_BACK,
    KEYEVENTF_UNICODE,
    KEYEVENTF_KEYUP,
)
from src.desktop.components.practice_editor import PracticeEditorWindow


# ---------------------------------------------------------------------------
# Focus Detection Tests
# ---------------------------------------------------------------------------

class TestFocusDetection:
    """Test target window and descendant focus detection."""

    @patch("win32gui.GetForegroundWindow", return_value=12345)
    def test_direct_window_focused(self, mock_fg):
        """When the foreground window exactly matches target HWND."""
        assert is_window_focused(12345) is True

    @patch("win32gui.GetForegroundWindow", return_value=99999)
    @patch("win32gui.GetAncestor", return_value=12345)
    def test_child_control_focused(self, mock_ancestor, mock_fg):
        """When a child control (e.g. inner edit control) has focus under target HWND."""
        assert is_window_focused(12345) is True
        mock_ancestor.assert_called_once_with(99999, 2)  # GA_ROOT = 2

    @patch("win32gui.GetForegroundWindow", return_value=88888)
    @patch("win32gui.GetAncestor", return_value=77777)
    def test_unrelated_window_focused(self, mock_ancestor, mock_fg):
        """When an unrelated external window has focus."""
        assert is_window_focused(12345) is False

    @patch("win32gui.GetForegroundWindow", side_effect=RuntimeError("HWND destroyed"))
    def test_focus_check_exception_handling(self, mock_fg):
        """Focus check must gracefully return False if Windows API fails."""
        assert is_window_focused(12345) is False

    @patch("win32gui.GetForegroundWindow", return_value=12345)
    @patch("win32gui.GetWindowText", return_value="  Chrome - NIAT Practice Portal  ")
    def test_get_foreground_window_title(self, mock_text, mock_fg):
        title = get_foreground_window_title()
        assert title == "Chrome - NIAT Practice Portal"

    @patch("win32gui.IsIconic", return_value=True)
    @patch("win32gui.ShowWindow")
    @patch("win32gui.SetForegroundWindow")
    @patch("src.worker.interaction.is_window_focused", return_value=True)
    def test_activate_window_iconic(self, mock_focused, mock_set_fg, mock_show, mock_iconic):
        """Should restore minimized window and bring to foreground."""
        success = activate_window(12345)
        assert success is True
        mock_iconic.assert_called_once_with(12345)
        mock_show.assert_called_once()
        mock_set_fg.assert_called_once_with(12345)


# ---------------------------------------------------------------------------
# Clipboard-Free Keystroke Tests
# ---------------------------------------------------------------------------

class TestSendInputKeystrokes:
    """Verify that SendInput sends hardware-level unicode inputs without clipboard paste."""

    @patch("ctypes.windll.user32.SendInput")
    def test_send_unicode_char_normal(self, mock_send_input):
        send_unicode_char("A")
        mock_send_input.assert_called_once()
        args = mock_send_input.call_args[0]
        assert args[0] == 2  # 2 events: key down and key up

    @patch("ctypes.windll.user32.SendInput")
    def test_send_unicode_newline(self, mock_send_input):
        send_unicode_char("\n")
        mock_send_input.assert_called_once()
        args = mock_send_input.call_args[0]
        assert args[0] == 2

    @patch("ctypes.windll.user32.SendInput")
    def test_send_carriage_return_ignored(self, mock_send_input):
        send_unicode_char("\r")
        mock_send_input.assert_not_called()

    @patch("ctypes.windll.user32.SendInput")
    def test_send_backspace(self, mock_send_input):
        send_backspace(count=3)
        assert mock_send_input.call_count == 3


# ---------------------------------------------------------------------------
# KeyboardComputerUseAgent Tests
# ---------------------------------------------------------------------------

class TestKeyboardComputerUseAgent:
    """Test chunked typing agent lifecycle, events, focus verification, and safety halts."""

    def test_empty_code_handling(self):
        timeline_events = []
        agent = KeyboardComputerUseAgent(
            target_hwnd=1000,
            target_title="Test Editor",
            on_timeline_event=timeline_events.append,
        )
        res = agent.type_code("")
        assert res is False
        assert len(timeline_events) == 1
        assert timeline_events[0].event_type == TimelineEventType.VERIFY
        assert timeline_events[0].status == TimelineEventStatus.WARNING

    @patch("src.worker.interaction.is_window_focused", return_value=True)
    @patch("src.worker.interaction.send_unicode_char")
    def test_successful_chunked_typing(self, mock_send_char, mock_focus):
        """Verify code is typed in chunks without clipboard and emits timeline events."""
        events: list[TimelineEvent] = []
        code_to_type = "def solution(nums):\n    return sum(nums)\n"

        agent = KeyboardComputerUseAgent(
            target_hwnd=1000,
            target_title="NIAT Coding Practice",
            chunk_size=10,
            delay_between_chunks=0.001,
            on_timeline_event=events.append,
        )

        completed = agent.type_code(code_to_type)
        assert completed is True

        # Verify every character was sent
        assert mock_send_char.call_count == len(code_to_type)
        sent_chars = "".join(call_args[0][0] for call_args in mock_send_char.call_args_list)
        assert sent_chars == code_to_type

        # Verify timeline events
        event_types = [e.event_type for e in events]
        assert TimelineEventType.FOCUS_CHECK in event_types
        assert TimelineEventType.TYPE_CHUNK in event_types
        assert TimelineEventType.VERIFY in event_types

        # Verify last event is success
        assert events[-1].event_type == TimelineEventType.VERIFY
        assert events[-1].status == TimelineEventStatus.SUCCESS
        assert events[-1].metadata.get("total_chars") == len(code_to_type)

    @patch("src.worker.interaction.is_window_focused", return_value=False)
    @patch("src.worker.interaction.activate_window", return_value=False)
    @patch("src.worker.interaction.get_foreground_window_title", return_value="Notepad")
    def test_aborts_if_focus_lost_at_start(self, mock_title, mock_activate, mock_focus):
        """If editor is not focused before typing, abort immediately with EditorFocusLostError."""
        events: list[TimelineEvent] = []
        agent = KeyboardComputerUseAgent(
            target_hwnd=1000,
            target_title="Target Practice",
            on_timeline_event=events.append,
        )

        with pytest.raises(EditorFocusLostError) as exc_info:
            agent.type_code("x = 10\n")

        assert "Target window is not in focus" in str(exc_info.value)
        assert any(e.event_type == TimelineEventType.ERROR for e in events)

    @patch("src.worker.interaction.send_unicode_char")
    def test_aborts_mid_stream_when_focus_is_lost(self, mock_send_char):
        """If focus shifts away during typing (after first chunk), immediately abort."""
        events: list[TimelineEvent] = []
        code_to_type = "chunk_one_here!chunk_two_here!"  # 30 chars, chunk size 15

        focus_states = [True, True, False]  # initial check: True, chunk 0 check: True, chunk 1 check: False

        with patch("src.worker.interaction.is_window_focused", side_effect=focus_states):
            with patch("src.worker.interaction.get_foreground_window_title", return_value="AltTabWindow"):
                agent = KeyboardComputerUseAgent(
                    target_hwnd=1000,
                    target_title="Target Editor",
                    chunk_size=15,
                    delay_between_chunks=0.001,
                    on_timeline_event=events.append,
                )

                with pytest.raises(EditorFocusLostError) as exc_info:
                    agent.type_code(code_to_type)

                assert "Editor lost focus at chunk" in str(exc_info.value)
                # Only first chunk was sent
                assert mock_send_char.call_count == 15

    @patch("src.worker.interaction.is_window_focused", return_value=True)
    @patch("src.worker.interaction.send_unicode_char")
    def test_emergency_stop_halts_typing(self, mock_send_char, mock_focus):
        """Triggering emergency stop must immediately abort typing."""
        events: list[TimelineEvent] = []
        stop_flag = [False]

        def is_stopped():
            return stop_flag[0]

        code_to_type = "line1\nline2\nline3\nline4\nline5\n"

        agent = KeyboardComputerUseAgent(
            target_hwnd=1000,
            target_title="Target Window",
            chunk_size=6,
            delay_between_chunks=0.001,
            on_timeline_event=events.append,
            is_stopped_check=is_stopped,
        )

        # Stop before second chunk
        def side_effect(char):
            if char == "2":
                stop_flag[0] = True

        mock_send_char.side_effect = side_effect

        with pytest.raises(EmergencyStopError):
            agent.type_code(code_to_type)

        stop_events = [e for e in events if e.event_type == TimelineEventType.EMERGENCY_STOP]
        assert len(stop_events) == 1
        assert stop_events[0].status == TimelineEventStatus.FAILED

    @patch("src.worker.interaction.is_window_focused", return_value=True)
    @patch("src.worker.interaction.send_unicode_char")
    def test_pause_suspends_and_resumes(self, mock_send_char, mock_focus):
        """Agent should pause when is_paused_check() is True, then resume when False."""
        events: list[TimelineEvent] = []
        pause_counter = [2]  # Pause for 2 checks, then unpause

        def is_paused():
            if pause_counter[0] > 0:
                pause_counter[0] -= 1
                return True
            return False

        agent = KeyboardComputerUseAgent(
            target_hwnd=1000,
            target_title="Target Window",
            chunk_size=5,
            delay_between_chunks=0.001,
            on_timeline_event=events.append,
            is_paused_check=is_paused,
        )

        code_to_type = "hello world"
        completed = agent.type_code(code_to_type)
        assert completed is True

        pause_events = [e for e in events if e.event_type == TimelineEventType.PAUSE]
        assert len(pause_events) >= 1


# ---------------------------------------------------------------------------
# Practice Editor Verification Tests
# ---------------------------------------------------------------------------

class TestPracticeEditorWindow:
    """Verify local practice editor code comparison and line/char tracking."""

    @pytest.fixture
    def qapp(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        return app

    def test_practice_editor_exact_match(self, qapp):
        editor = PracticeEditorWindow()
        editor.set_editor_text("def solve():\n    return 42\n")

        res = editor.compare_code("def solve():\n    return 42\n")
        assert res["exact_match"] is True
        assert res["similarity_ratio"] == 1.0
        assert res["editor_chars"] == res["expected_chars"]
        editor.close()

    def test_practice_editor_partial_match(self, qapp):
        editor = PracticeEditorWindow()
        editor.set_editor_text("def solve():\n    return 41\n")

        res = editor.compare_code("def solve():\n    return 42\n")
        assert res["exact_match"] is False
        assert 0.8 < res["similarity_ratio"] < 1.0
        assert "diff" in res
        editor.close()

    def test_practice_editor_line_and_char_counts(self, qapp):
        editor = PracticeEditorWindow()
        test_text = "line 1\nline 2\nline 3"
        editor.set_editor_text(test_text)
        assert editor.character_count == len(test_text)
        assert editor.line_count == 3
        editor.close()
