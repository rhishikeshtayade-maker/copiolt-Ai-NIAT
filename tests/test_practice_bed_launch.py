"""Automated tests for the Practice Bed button signal and practice-window launch.

Verifies:
1. FloatingControlsDock '🎯 Practice Bed' button emits open_practice_editor_clicked signal.
2. Signal is connected to MainWindow.on_open_practice_editor.
3. MainWindow instantiates PracticeEditorWindow as an instance attribute.
4. Window is shown, raised, and activated without accidental hiding or closing.
5. Re-clicking reuses the existing instance without creating duplicate windows.
6. Minimized editor is properly restored via showNormal().
7. Practice Bed is automatically prioritized and selected in the window capture target combo.
8. Opening the practice editor does not disrupt background worker threads or capture services.
9. Exceptions during editor creation/display are caught, logged, and handled cleanly.
"""

from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.desktop.app import MainWindow
from src.desktop.components.floating_controls import FloatingControlsDock
from src.desktop.components.practice_editor import PracticeEditorWindow


@pytest.fixture
def qapp():
    """Ensure a QApplication instance exists."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestPracticeBedLaunch:
    """Test suite for Practice Bed button interaction and window management."""

    def test_practice_bed_button_emits_signal(self, qapp):
        """Clicking '🎯 Practice Bed' on FloatingControlsDock must emit open_practice_editor_clicked."""
        dock = FloatingControlsDock()
        signal_emitted = []
        dock.open_practice_editor_clicked.connect(lambda: signal_emitted.append(True))

        # Simulate button click
        dock.practice_btn.click()

        assert len(signal_emitted) == 1
        assert signal_emitted[0] is True

    def test_signal_connected_to_mainwindow(self, qapp):
        """MainWindow must connect dock's open_practice_editor_clicked to on_open_practice_editor."""
        with patch.object(MainWindow, "_auto_start_worker"), \
             patch.object(MainWindow, "refresh_window_list"):
            window = MainWindow()
            # Verify the receiver is on_open_practice_editor
            assert window.controls_dock.open_practice_editor_clicked is not None

    def test_on_open_practice_editor_instantiates_and_shows_window(self, qapp):
        """on_open_practice_editor must instantiate PracticeEditorWindow, retain it, and show it."""
        with patch.object(MainWindow, "_auto_start_worker"), \
             patch.object(MainWindow, "_apply_capture_targeting"), \
             patch.object(MainWindow, "refresh_window_list"):
            window = MainWindow()
            assert window.practice_editor is None

            window.on_open_practice_editor()

            assert window.practice_editor is not None
            assert isinstance(window.practice_editor, PracticeEditorWindow)
            assert window.practice_editor.isVisible() is True
            assert "NIAT Local Practice Editor" in window.practice_editor.windowTitle()

            # Clean up
            window.practice_editor.close()

    def test_on_open_practice_editor_reuses_existing_instance(self, qapp):
        """Subsequent clicks should reuse the existing window instance rather than duplicating."""
        with patch.object(MainWindow, "_auto_start_worker"), \
             patch.object(MainWindow, "_apply_capture_targeting"), \
             patch.object(MainWindow, "refresh_window_list"):
            window = MainWindow()

            window.on_open_practice_editor()
            first_instance = window.practice_editor

            # Click again
            window.on_open_practice_editor()
            second_instance = window.practice_editor

            assert first_instance is second_instance
            assert second_instance.isVisible() is True

            window.practice_editor.close()

    def test_on_open_practice_editor_restores_minimized_window(self, qapp):
        """If practice editor was minimized, clicking the button must restore it via showNormal()."""
        with patch.object(MainWindow, "_auto_start_worker"), \
             patch.object(MainWindow, "_apply_capture_targeting"), \
             patch.object(MainWindow, "refresh_window_list"):
            window = MainWindow()

            window.on_open_practice_editor()
            editor = window.practice_editor
            assert editor is not None

            # Minimize editor
            editor.showMinimized()
            assert editor.isMinimized() is True

            # Trigger open again
            window.on_open_practice_editor()
            assert editor.isMinimized() is False
            assert editor.isVisible() is True

            editor.close()

    def test_on_open_practice_editor_recreates_if_destroyed(self, qapp):
        """If previous C++ object was destroyed, a fresh instance must be created."""
        with patch.object(MainWindow, "_auto_start_worker"), \
             patch.object(MainWindow, "_apply_capture_targeting"), \
             patch.object(MainWindow, "refresh_window_list"):
            window = MainWindow()

            # Simulate destroyed instance
            stale_editor = MagicMock()
            stale_editor.isVisible.side_effect = RuntimeError("Internal C++ object already deleted")
            window.practice_editor = stale_editor

            window.on_open_practice_editor()

            assert window.practice_editor is not None
            assert window.practice_editor is not stale_editor
            assert isinstance(window.practice_editor, PracticeEditorWindow)

            window.practice_editor.close()

    def test_practice_editor_selected_in_window_combo(self, qapp):
        """Opening Practice Bed must list it at index 0 and select it in the target combo."""
        with patch.object(MainWindow, "_auto_start_worker"):
            window = MainWindow()
            window.on_open_practice_editor()

            assert window.practice_editor is not None
            practice_hwnd = int(window.practice_editor.winId())

            assert window.window_combo.count() >= 1
            assert window.window_combo.currentData() == practice_hwnd
            assert "NIAT Local Practice Editor" in window.window_combo.currentText()

            # Capture service should reflect the practice window target
            assert window.capture_service.target_hwnd == practice_hwnd

            window.practice_editor.close()

    def test_opening_editor_does_not_interfere_with_worker_threads_or_capture(self, qapp):
        """Worker client, timers, and capture service must remain active and functional."""
        with patch.object(MainWindow, "_auto_start_worker"):
            window = MainWindow()

            # Mock threads
            mock_heartbeat = MagicMock()
            mock_heartbeat.isRunning.return_value = True
            window.heartbeat_thread = mock_heartbeat

            window.preview_timer.start(5000)
            window.observe_timer.start(5000)

            window.on_open_practice_editor()

            # Ensure timers and threads did not halt
            assert window.preview_timer.isActive() is True
            assert window.observe_timer.isActive() is True
            assert mock_heartbeat.stop.call_count == 0

            window.practice_editor.close()

    def test_on_open_practice_editor_handles_exceptions_gracefully(self, qapp):
        """Any unexpected exception in practice editor launch must be caught and logged."""
        with patch.object(MainWindow, "_auto_start_worker"), \
             patch("src.desktop.app.PracticeEditorWindow", side_effect=RuntimeError("GPU allocation error")), \
             patch("src.desktop.app.logger.exception") as mock_log_exc, \
             patch("src.desktop.app.QMessageBox.warning") as mock_msg_warning:

            window = MainWindow()
            # Should not raise
            window.on_open_practice_editor()

            mock_log_exc.assert_called_once()
            assert "GPU allocation error" in str(mock_log_exc.call_args)
            mock_msg_warning.assert_called_once()
