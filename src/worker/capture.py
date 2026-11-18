"""Screen capture service using MSS with explicit user permission guards."""

import io
from typing import Optional, Tuple
import mss
from PIL import Image
from src.common.logger import get_logger
from src.common.schemas import ScreenCaptureMetadata, current_utc_time

logger = get_logger("Worker.ScreenCapture")


class ScreenCaptureService:
    """Manages high-performance desktop screen capture with strict consent verification."""

    def __init__(self, worker_id: str = "worker-default") -> None:
        self.worker_id = worker_id
        self._user_permission_granted: bool = False
        self._is_active: bool = False

    @property
    def has_permission(self) -> bool:
        """Check whether explicit user permission is currently active."""
        return self._user_permission_granted

    def set_user_permission(self, granted: bool) -> None:
        """Update explicit user permission status.

        Screen capture operations will immediately fail if permission is revoked.
        """
        self._user_permission_granted = granted
        if not granted:
            self._is_active = False
            logger.warning(
                f"Screen capture permission REVOKED on worker '{self.worker_id}'."
            )
        else:
            logger.info(
                f"Screen capture permission ACTIVATED on worker '{self.worker_id}' by user."
            )

    def start(self) -> None:
        """Start capture engine if explicit consent has been verified."""
        if not self._user_permission_granted:
            raise PermissionError(
                "Cannot start screen capture: Explicit user consent has not been granted."
            )
        self._is_active = True
        logger.info(f"Screen capture service started on worker '{self.worker_id}'.")

    def stop(self) -> None:
        """Halt screen capture service."""
        self._is_active = False
        logger.info(f"Screen capture service stopped on worker '{self.worker_id}'.")

    def emergency_halt(self) -> None:
        """Immediately cut screen capture and revoke active status."""
        self._is_active = False
        self._user_permission_granted = False
        logger.critical(
            f"EMERGENCY HALT triggered on screen capture for worker '{self.worker_id}'."
        )

    def capture_frame_bytes(
        self, monitor_index: int = 1, max_size: Optional[Tuple[int, int]] = (1280, 720)
    ) -> Tuple[bytes, ScreenCaptureMetadata]:
        """Capture the permitted screen content and return compressed PNG bytes with metadata.

        Strictly enforces explicit user consent prior to reading any pixels.
        """
        if not self._user_permission_granted:
            raise PermissionError(
                "Access Denied: Screen capture attempted without explicit user consent."
            )

        if not self._is_active:
            raise RuntimeError(
                "Screen capture service is currently stopped. Activate service first."
            )

        try:
            with mss.mss() as sct:
                # monitor 0 is all monitors combined; monitor 1 is primary monitor
                monitors = sct.monitors
                target_monitor = (
                    monitors[monitor_index]
                    if monitor_index < len(monitors)
                    else monitors[0]
                )

                sct_img = sct.grab(target_monitor)

                # Convert to PIL Image
                img = Image.frombytes("RGB", (sct_img.width, sct_img.height), sct_img.rgb)

                # Optional thumbnail/resizing for bandwidth efficiency
                if max_size:
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)

                # Save to PNG byte stream
                buffer = io.BytesIO()
                img.save(buffer, format="PNG", optimize=True)
                png_bytes = buffer.getvalue()

                metadata = ScreenCaptureMetadata(
                    worker_id=self.worker_id,
                    width=img.width,
                    height=img.height,
                    captured_at=current_utc_time(),
                    explicit_permission_verified=True,
                    format="PNG",
                    frame_size_bytes=len(png_bytes),
                )

                return png_bytes, metadata

        except Exception as e:
            logger.error(f"Failed to capture screen frame: {e}")
            raise
