"""Unit and integration tests for NIAT CodePilot desktop application startup.

Verifies:
1. app.main() correctly checks/reuses QApplication without duplication.
2. app.main() instantiates MainWindow and calls show().
3. app.main() starts the Qt event loop with app.exec().
4. app.main() catches and logs startup exceptions, returning non-zero exit code.
5. main.py delegates cleanly to app.main().
6. MainWindow.closeEvent cleanly shuts down timers, services, and worker threads.
7. Startup entry point executes without hanging or opening physical windows.
"""

from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from src.desktop import app, main as desktop_main


class TestDesktopStartup:
    """Tests for the desktop entry points and application lifecycle."""

    def test_main_creates_qapplication_if_none_exists(self):
        """When no QApplication exists, main() creates one, shows MainWindow, and calls exec()."""
        with patch.object(app, "QApplication") as mock_qapp_cls, \
             patch.object(app, "MainWindow") as mock_window_cls:

            mock_qapp_cls.instance.return_value = None
            mock_app_instance = MagicMock()
            mock_app_instance.exec.return_value = 0
            mock_qapp_cls.return_value = mock_app_instance

            mock_window = MagicMock()
            mock_window_cls.return_value = mock_window

            exit_code = app.main()

            assert exit_code == 0
            mock_qapp_cls.assert_called_once()
            mock_app_instance.setApplicationName.assert_called_once_with("NIAT CodePilot")
            mock_app_instance.setOrganizationName.assert_called_once_with("NIAT")
            mock_window_cls.assert_called_once()
            mock_window.show.assert_called_once()
            mock_app_instance.exec.assert_called_once()

    def test_main_reuses_existing_qapplication(self):
        """When a QApplication instance already exists, main() does NOT create a new one."""
        existing_app = MagicMock()
        existing_app.exec.return_value = 0

        with patch.object(app, "QApplication") as mock_qapp_cls, \
             patch.object(app, "MainWindow") as mock_window_cls:

            mock_qapp_cls.instance.return_value = existing_app
            mock_window = MagicMock()
            mock_window_cls.return_value = mock_window

            exit_code = app.main()

            assert exit_code == 0
            # Ensure QApplication was NOT instantiated again
            mock_qapp_cls.assert_not_called()
            mock_window_cls.assert_called_once()
            mock_window.show.assert_called_once()
            existing_app.exec.assert_called_once()

    def test_main_handles_startup_exception_gracefully(self):
        """Startup errors should be caught, logged, and return exit code 1."""
        existing_app = MagicMock()

        with patch.object(app.QApplication, "instance", return_value=existing_app), \
             patch.object(app, "MainWindow", side_effect=RuntimeError("DirectX/DPI initialization failure")), \
             patch.object(app.logger, "exception") as mock_log_exc:

            exit_code = app.main()

            assert exit_code == 1
            mock_log_exc.assert_called_once()
            assert "DirectX/DPI initialization failure" in str(mock_log_exc.call_args)

    def test_desktop_main_delegates_to_app_main(self):
        """src/desktop/main.py delegates execution to src/desktop/app.py main()."""
        with patch.object(desktop_main, "app_main", return_value=42) as mock_app_main:
            exit_code = desktop_main.main()
            assert exit_code == 42
            mock_app_main.assert_called_once()

    def test_mainwindow_close_event_clean_shutdown(self):
        """MainWindow.closeEvent must stop timers, threads, and capture service."""
        # Ensure QApplication is initialized for widget tests
        qt_app = QApplication.instance() or QApplication([])

        with patch.object(app.MainWindow, "_auto_start_worker"), \
             patch.object(app.MainWindow, "_apply_capture_targeting"), \
             patch.object(app.MainWindow, "refresh_window_list"):

            window = app.MainWindow()

            # Attach mock threads and timers to verify they are stopped
            mock_preview_timer = MagicMock()
            mock_observe_timer = MagicMock()
            mock_typing_thread = MagicMock()
            mock_typing_thread.isRunning.return_value = True
            mock_ai_thread = MagicMock()
            mock_ai_thread.isRunning.return_value = True
            mock_heartbeat_thread = MagicMock()
            mock_heartbeat_thread.isRunning.return_value = True
            mock_capture_service = MagicMock()
            mock_practice_editor = MagicMock()

            window.preview_timer = mock_preview_timer
            window.observe_timer = mock_observe_timer
            window.typing_thread = mock_typing_thread
            window.ai_thread = mock_ai_thread
            window.heartbeat_thread = mock_heartbeat_thread
            window.capture_service = mock_capture_service
            window.practice_editor = mock_practice_editor

            mock_close_event = MagicMock()
            window.closeEvent(mock_close_event)

            mock_preview_timer.stop.assert_called_once()
            mock_observe_timer.stop.assert_called_once()
            mock_typing_thread.stop.assert_called_once()
            mock_typing_thread.wait.assert_called_once()
            mock_ai_thread.wait.assert_called_once()
            mock_heartbeat_thread.stop.assert_called_once()
            mock_heartbeat_thread.wait.assert_called_once()
            mock_capture_service.stop.assert_called_once()
            mock_practice_editor.close.assert_called_once()
            mock_close_event.accept.assert_called()
