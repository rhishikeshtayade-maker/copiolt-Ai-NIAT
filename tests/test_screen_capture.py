"""Unit tests for the screen capture service and permission guards."""

import pytest
from unittest.mock import MagicMock, patch
from src.worker.capture import ScreenCaptureService


def test_permission_guard_default_state():
    """Service should refuse capture by default when permission has not been granted."""
    service = ScreenCaptureService(worker_id="test-worker")
    assert service.has_permission is False

    with pytest.raises(PermissionError) as exc_info:
        service.start()
    assert "Explicit user consent has not been granted" in str(exc_info.value)

    with pytest.raises(PermissionError) as exc_info:
        service.capture_frame_bytes()
    assert "without explicit user consent" in str(exc_info.value)


def test_permission_activation_and_revocation():
    """Toggling user permission should properly enable or block the capture engine."""
    service = ScreenCaptureService(worker_id="test-worker")

    # Grant permission
    service.set_user_permission(True)
    assert service.has_permission is True

    # Start service
    service.start()
    assert service._is_active is True

    # Revoke permission
    service.set_user_permission(False)
    assert service.has_permission is False
    assert service._is_active is False

    with pytest.raises(PermissionError):
        service.capture_frame_bytes()


def test_emergency_halt():
    """Emergency halt should instantly drop both permission and active status."""
    service = ScreenCaptureService(worker_id="test-worker")
    service.set_user_permission(True)
    service.start()
    assert service.has_permission is True
    assert service._is_active is True

    service.emergency_halt()
    assert service.has_permission is False
    assert service._is_active is False


def test_mocked_screen_capture():
    """Test frame capture with mock MSS output to test compression and metadata."""
    service = ScreenCaptureService(worker_id="test-worker")
    service.set_user_permission(True)
    service.start()

    # Mock MSS screenshot object
    mock_sct = MagicMock()
    mock_sct.__enter__.return_value = mock_sct
    mock_sct.monitors = [{"left": 0, "top": 0, "width": 800, "height": 600}]
    mock_frame = MagicMock()
    mock_frame.width = 800
    mock_frame.height = 600
    mock_frame.size = (800, 600)
    mock_frame.rgb = b"\x00" * (800 * 600 * 3)
    mock_sct.grab.return_value = mock_frame

    with patch("mss.mss", return_value=mock_sct):
        png_bytes, meta = service.capture_frame_bytes(monitor_index=0)
        assert len(png_bytes) > 0
        assert meta.worker_id == "test-worker"
        assert meta.explicit_permission_verified is True
        assert meta.format == "PNG"


def test_list_capturable_windows_excludes_niat_codepilot():
    """Verify that open window enumeration filters out NIAT CodePilot windows."""
    from src.worker.capture import list_capturable_windows

    # Mock EnumWindows callback behavior
    def fake_enum_windows(callback, extra):
        # callback(hwnd, extra)
        callback(101, extra)  # "Visual Studio Code"
        callback(102, extra)  # "NIAT CodePilot - Distributed Worker"
        callback(103, extra)  # "Chrome - LeetCode"
        callback(104, extra)  # "" (empty title)

    def fake_get_text(hwnd):
        mapping = {
            101: "Visual Studio Code - project.py",
            102: "NIAT CodePilot - Distributed Worker & Screen Capture",
            103: "Chrome - LeetCode Problem 1",
            104: "",
        }
        return mapping.get(hwnd, "")

    def fake_is_window_visible(hwnd):
        return True

    def fake_get_window_rect(hwnd):
        return (0, 0, 1280, 720)

    with patch("win32gui.EnumWindows", side_effect=fake_enum_windows), \
         patch("win32gui.GetWindowText", side_effect=fake_get_text), \
         patch("win32gui.IsWindowVisible", side_effect=fake_is_window_visible), \
         patch("win32gui.GetWindowRect", side_effect=fake_get_window_rect):

        windows = list_capturable_windows(exclude_titles=("NIAT CodePilot",))

        titles = [w["title"] for w in windows]
        assert "Visual Studio Code - project.py" in titles
        assert "Chrome - LeetCode Problem 1" in titles
        # Ensure NIAT CodePilot is excluded
        for t in titles:
            assert "NIAT CodePilot" not in t
        assert len(windows) == 2


def test_targeting_modes_and_approved_frame_single_source():
    """Verify monitor/window/region targeting and single approved frame retention."""
    service = ScreenCaptureService(worker_id="test-worker")
    service.set_user_permission(True)
    service.start()

    # Initial state: no approved frame
    assert service.get_last_approved_frame() is None

    # Test setting targeting modes
    service.set_target_mode("region", region_rect=(50, 60, 400, 300))
    assert service.target_mode == "region"
    assert service.region_rect == (50, 60, 400, 300)

    service.set_target_mode("window", window_hwnd=12345)
    assert service.target_mode == "window"
    assert service.window_hwnd == 12345

    service.set_target_mode("monitor", monitor_index=1)
    assert service.target_mode == "monitor"
    assert service.monitor_index == 1

    # Mock MSS to capture and verify approved frame caching
    mock_sct = MagicMock()
    mock_sct.__enter__.return_value = mock_sct
    mock_sct.monitors = [{"left": 0, "top": 0, "width": 800, "height": 600}]
    mock_frame = MagicMock()
    mock_frame.width = 800
    mock_frame.height = 600
    mock_frame.size = (800, 600)
    mock_frame.rgb = b"\x00" * (800 * 600 * 3)
    mock_sct.grab.return_value = mock_frame

    with patch("mss.mss", return_value=mock_sct):
        b64_jpeg, meta = service.capture_jpeg_base64()
        # Verify approved frame is recorded and matches
        approved = service.get_last_approved_frame()
        assert approved is not None
        assert approved[0] == b64_jpeg
        assert approved[1] == meta

    # Emergency halt must clear approved frame
    service.emergency_halt()
    assert service.get_last_approved_frame() is None
    assert service.has_permission is False


# ---------------------------------------------------------------------------
# Window capture safety & anti-fallback regression tests
# ---------------------------------------------------------------------------
class TestWindowCaptureSafety:
    """Ensure that window capture NEVER falls back to full-screen or primary monitor
    when a window is minimized, hidden, closed, nonexistent, or invalid.
    """

    def _setup_service(self):
        service = ScreenCaptureService(worker_id="safety-test-worker")
        service.set_user_permission(True)
        service.start()
        return service

    def test_refuse_when_no_window_selected(self):
        """When in window mode with hwnd=None, raise RuntimeError and do NOT grab screen."""
        service = self._setup_service()
        service.set_target_mode("window", window_hwnd=None)

        mock_sct = MagicMock()
        mock_sct.__enter__.return_value = mock_sct

        with patch("mss.mss", return_value=mock_sct):
            with pytest.raises(RuntimeError, match="No application window selected"):
                service.capture_frame_bytes()

        # MSS grab must NEVER be called
        mock_sct.grab.assert_not_called()
        assert service.get_last_approved_frame() is None

    def test_refuse_when_window_closed_or_nonexistent(self):
        """When HWND is closed/nonexistent, raise RuntimeError and do NOT grab screen."""
        service = self._setup_service()
        service.set_target_mode("window", window_hwnd=99999, window_title="Closed App")

        mock_sct = MagicMock()
        mock_sct.__enter__.return_value = mock_sct

        with patch("mss.mss", return_value=mock_sct), \
             patch("win32gui.IsWindow", return_value=False):
            with pytest.raises(RuntimeError, match="closed or no longer exists"):
                service.capture_frame_bytes()

        mock_sct.grab.assert_not_called()
        assert service.get_last_approved_frame() is None

    def test_refuse_when_window_minimized(self):
        """When window is minimized (iconic), raise RuntimeError and do NOT grab monitor."""
        service = self._setup_service()
        service.set_target_mode("window", window_hwnd=88888, window_title="Minimized Browser")

        mock_sct = MagicMock()
        mock_sct.__enter__.return_value = mock_sct

        with patch("mss.mss", return_value=mock_sct), \
             patch("win32gui.IsWindow", return_value=True), \
             patch("win32gui.IsIconic", return_value=True):
            with pytest.raises(RuntimeError, match="is minimized"):
                service.capture_frame_bytes()

        mock_sct.grab.assert_not_called()
        assert service.get_last_approved_frame() is None

    def test_refuse_when_window_hidden(self):
        """When window is hidden, raise RuntimeError and do NOT grab monitor."""
        service = self._setup_service()
        service.set_target_mode("window", window_hwnd=77777, window_title="Hidden IDE")

        mock_sct = MagicMock()
        mock_sct.__enter__.return_value = mock_sct

        with patch("mss.mss", return_value=mock_sct), \
             patch("win32gui.IsWindow", return_value=True), \
             patch("win32gui.IsIconic", return_value=False), \
             patch("win32gui.IsWindowVisible", return_value=False):
            with pytest.raises(RuntimeError, match="hidden or not visible"):
                service.capture_frame_bytes()

        mock_sct.grab.assert_not_called()
        assert service.get_last_approved_frame() is None

    def test_refuse_when_window_has_zero_or_negative_geometry(self):
        """When window has 0 or negative width/height, raise RuntimeError and do NOT grab monitor."""
        service = self._setup_service()
        service.set_target_mode("window", window_hwnd=66666, window_title="Zero Rect Window")

        mock_sct = MagicMock()
        mock_sct.__enter__.return_value = mock_sct

        with patch("mss.mss", return_value=mock_sct), \
             patch("win32gui.IsWindow", return_value=True), \
             patch("win32gui.IsIconic", return_value=False), \
             patch("win32gui.IsWindowVisible", return_value=True), \
             patch("win32gui.GetWindowRect", return_value=(200, 200, 200, 200)):  # 0x0 size
            with pytest.raises(RuntimeError, match="invalid dimensions"):
                service.capture_frame_bytes()

        mock_sct.grab.assert_not_called()
        assert service.get_last_approved_frame() is None

    def test_valid_window_capture_only_grabs_window_rect(self):
        """When window is valid, visible, and unminimized, grab ONLY its bounding box."""
        service = self._setup_service()
        service.set_target_mode("window", window_hwnd=55555, window_title="Active Code Window")

        mock_sct = MagicMock()
        mock_sct.__enter__.return_value = mock_sct
        mock_sct.monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]
        mock_frame = MagicMock()
        mock_frame.width = 600
        mock_frame.height = 400
        mock_frame.rgb = b"\x10" * (600 * 400 * 3)
        mock_sct.grab.return_value = mock_frame

        with patch("mss.mss", return_value=mock_sct), \
             patch("win32gui.IsWindow", return_value=True), \
             patch("win32gui.IsIconic", return_value=False), \
             patch("win32gui.IsWindowVisible", return_value=True), \
             patch("win32gui.GetWindowRect", return_value=(100, 150, 700, 550)):  # w=600, h=400
            b64_jpeg, meta = service.capture_jpeg_base64()

        # Verified: grab was called ONLY with the window rect, never a full monitor!
        mock_sct.grab.assert_called_once_with({"left": 100, "top": 150, "width": 600, "height": 400})
        assert meta.width == 600
        assert meta.height == 400
        assert service.get_last_approved_frame() is not None
