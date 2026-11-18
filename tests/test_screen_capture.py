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
