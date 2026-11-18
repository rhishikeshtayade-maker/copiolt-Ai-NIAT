"""Screen capture service using MSS with explicit user permission guards and flexible targeting."""

import base64
import io
from typing import Any, Dict, List, Optional, Tuple, Union
import mss
from PIL import Image

from src.common.logger import get_logger
from src.common.schemas import ScreenCaptureMetadata, current_utc_time

logger = get_logger("Worker.ScreenCapture")


def init_dpi_awareness() -> None:
    """Ensure process is DPI-aware so window capture coordinates align with physical pixels."""
    try:
        import ctypes
        try:
            # Per-Monitor DPI Aware v2 (Windows 10 1703+)
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    except Exception:
        pass


def list_capturable_windows(
    exclude_titles: Tuple[str, ...] = ("NIAT CodePilot",),
) -> List[Dict[str, Any]]:
    """Enumerate visible application windows on the desktop, excluding NIAT CodePilot and system shells.

    Uses dual enumeration (Default interactive desktop + standard EnumWindows) to reliably
    discover Google Chrome (NIAT portal), IDEs, and user applications regardless of background session context.

    Returns a list of dicts:
    [
        {
            "hwnd": int,
            "title": str,
            "rect": (left, top, right, bottom),
            "bounds": {"left": int, "top": int, "width": int, "height": int}
        }
    ]
    """
    init_dpi_awareness()
    windows: List[Dict[str, Any]] = []
    seen_hwnds = set()

    def process_hwnd(hwnd: int) -> None:
        if hwnd in seen_hwnds:
            return
        seen_hwnds.add(hwnd)

        try:
            import win32gui
            if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                return

            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return

            # Exclude NIAT CodePilot and desktop system shells
            if any(ex.lower() in title.lower() for ex in exclude_titles):
                return
            if title.lower() in ("program manager", "task switching", "windows input experience"):
                return

            # Check Windows DWM cloaking (e.g. apps on other virtual desktops)
            try:
                import ctypes
                dwmapi = ctypes.windll.dwmapi
                cloaked = ctypes.c_int(0)
                dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
                if cloaked.value != 0:
                    return
            except Exception:
                pass

            rect = win32gui.GetWindowRect(hwnd)  # (left, top, right, bottom)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]

            cls_name = ""
            try:
                cls_name = win32gui.GetClassName(hwnd)
            except Exception:
                pass

            is_browser = (
                "chrome" in cls_name.lower()
                or "chrome" in title.lower()
                or "niat" in title.lower()
                or "edge" in cls_name.lower()
            )

            if width > 50 and height > 50:
                windows.append(
                    {
                        "hwnd": hwnd,
                        "title": title,
                        "class_name": cls_name,
                        "is_browser": is_browser,
                        "rect": (rect[0], rect[1], rect[2], rect[3]),
                        "bounds": {
                            "left": rect[0],
                            "top": rect[1],
                            "width": width,
                            "height": height,
                        },
                    }
                )
        except Exception as e:
            logger.debug(f"Error checking window {hwnd}: {e}")

    # Method 1: EnumDesktopWindows on interactive 'default' desktop
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        h_desk = user32.OpenDesktopW("default", 0, False, 0x0100)  # DESKTOP_ENUMERATE
        if h_desk:
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

            def desk_cb(hwnd: int, _: int) -> bool:
                process_hwnd(hwnd)
                return True

            user32.EnumDesktopWindows(h_desk, WNDENUMPROC(desk_cb), 0)
            user32.CloseDesktop(h_desk)
    except Exception as e:
        logger.debug(f"Desktop enumeration notice: {e}")

    # Method 2: Standard EnumWindows fallback (also honors mocked win32gui in unit tests)
    try:
        import win32gui

        def std_cb(hwnd: int, _: Any) -> bool:
            process_hwnd(hwnd)
            return True

        win32gui.EnumWindows(std_cb, None)
    except Exception as e:
        logger.debug(f"Standard EnumWindows notice: {e}")

    # Prioritize coding practice, Chrome / NIAT portals, and editors at the top of the list
    windows.sort(
        key=lambda w: (
            not any(
                k in w["title"].lower() or k in w.get("class_name", "").lower()
                for k in ("niat", "practice", "chrome", "leetcode", "code")
            ),
            w["title"].lower(),
        )
    )

    return windows


class ScreenCaptureService:
    """Manages desktop screen capture with window targeting, sub-regions, and consent guards."""

    def __init__(self, worker_id: str = "worker-default") -> None:
        self.worker_id = worker_id
        self._user_permission_granted: bool = False
        self._is_active: bool = False

        # Capture targeting configuration
        self.target_mode: str = "monitor"  # "monitor", "window", or "region"
        self.target_monitor_index: int = 1
        self.target_hwnd: Optional[int] = None
        self.target_window_title: Optional[str] = None
        self.target_region: Optional[Dict[str, int]] = None  # {"left", "top", "width", "height"}

        # Stored approved frame ensuring preview and AI use the same capture
        self._last_approved_b64: Optional[str] = None
        self._last_approved_meta: Optional[ScreenCaptureMetadata] = None

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
            self.clear_approved_frame()
            logger.warning(
                f"Screen capture permission REVOKED on worker '{self.worker_id}'."
            )
        else:
            logger.info(
                f"Screen capture permission ACTIVATED on worker '{self.worker_id}' by user."
            )

    def set_target_mode(
        self,
        mode: str = "monitor",
        monitor_index: int = 1,
        hwnd: Optional[int] = None,
        window_hwnd: Optional[int] = None,
        window_title: Optional[str] = None,
        region: Optional[Union[Dict[str, int], Tuple[int, int, int, int]]] = None,
        region_rect: Optional[Union[Dict[str, int], Tuple[int, int, int, int]]] = None,
    ) -> None:
        """Configure capture targeting: full monitor, application window, or rectangular region."""
        if mode not in ("monitor", "window", "region"):
            raise ValueError(f"Invalid capture mode '{mode}'. Choose 'monitor', 'window', or 'region'.")

        self.target_mode = mode
        self.target_monitor_index = monitor_index
        self.target_hwnd = hwnd if hwnd is not None else window_hwnd
        self.target_window_title = window_title

        reg = region if region is not None else region_rect
        if reg:
            if isinstance(reg, (tuple, list)):
                self.target_region = {
                    "left": int(reg[0]),
                    "top": int(reg[1]),
                    "width": max(10, int(reg[2])),
                    "height": max(10, int(reg[3])),
                }
            else:
                self.target_region = {
                    "left": int(reg.get("left", 0)),
                    "top": int(reg.get("top", 0)),
                    "width": max(10, int(reg.get("width", 100))),
                    "height": max(10, int(reg.get("height", 100))),
                }
        else:
            self.target_region = None

        logger.info(
            f"Screen capture target set to '{mode}' (monitor={monitor_index}, hwnd={self.target_hwnd}, region={self.target_region})"
        )

    @property
    def region_rect(self) -> Optional[Tuple[int, int, int, int]]:
        if self.target_region:
            return (
                self.target_region["left"],
                self.target_region["top"],
                self.target_region["width"],
                self.target_region["height"],
            )
        return None

    @property
    def window_hwnd(self) -> Optional[int]:
        return self.target_hwnd

    @property
    def monitor_index(self) -> int:
        return self.target_monitor_index

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
        """Immediately cut screen capture, revoke active status, and flush stored frames."""
        self._is_active = False
        self._user_permission_granted = False
        self.clear_approved_frame()
        logger.critical(
            f"EMERGENCY HALT triggered on screen capture for worker '{self.worker_id}'."
        )

    # ------------------------------------------------------------------
    # Approved Frame Management
    # ------------------------------------------------------------------
    def set_approved_frame(self, b64_jpeg: str, metadata: ScreenCaptureMetadata) -> None:
        """Store the latest user-reviewed captured frame as the approved frame for AI analysis."""
        self._last_approved_b64 = b64_jpeg
        self._last_approved_meta = metadata

    def get_last_approved_frame(self) -> Optional[Tuple[str, ScreenCaptureMetadata]]:
        """Retrieve the approved frame to ensure preview and AI analysis use the identical capture."""
        if self._last_approved_b64 and self._last_approved_meta:
            return self._last_approved_b64, self._last_approved_meta
        return None

    def clear_approved_frame(self) -> None:
        """Clear approved frame buffer upon stop, emergency halt, or permission revocation."""
        self._last_approved_b64 = None
        self._last_approved_meta = None

    # ------------------------------------------------------------------
    # Core Grabbing Engine
    # ------------------------------------------------------------------
    def _grab_pil_image(
        self,
        max_size: Optional[Tuple[int, int]] = (1280, 720),
        monitor_index: Optional[int] = None,
    ) -> Image.Image:
        """Grab screen pixels based on active target mode (monitor, window, or region).

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

        with mss.mss() as sct:
            bbox: Dict[str, int]

            # 1. Window target mode
            if self.target_mode == "window":
                if not self.target_hwnd:
                    raise RuntimeError(
                        "No application window selected for capture. "
                        "Please select a valid open window from the dropdown."
                    )

                try:
                    import win32gui
                except ImportError as ie:
                    raise RuntimeError(
                        f"Window capture requires win32gui ({ie}). Please select monitor or region mode."
                    ) from ie

                if not win32gui.IsWindow(self.target_hwnd):
                    title = self.target_window_title or f"HWND {self.target_hwnd}"
                    raise RuntimeError(
                        f"Target application window '{title}' is closed or no longer exists. "
                        "Please reselect an active window."
                    )

                if win32gui.IsIconic(self.target_hwnd):
                    title = self.target_window_title or win32gui.GetWindowText(self.target_hwnd) or f"HWND {self.target_hwnd}"
                    raise RuntimeError(
                        f"Target application window '{title}' is minimized. "
                        "Please restore the window on screen before capturing."
                    )

                if not win32gui.IsWindowVisible(self.target_hwnd):
                    title = self.target_window_title or win32gui.GetWindowText(self.target_hwnd) or f"HWND {self.target_hwnd}"
                    raise RuntimeError(
                        f"Target application window '{title}' is hidden or not visible. "
                        "Please restore or unhide the window before capturing."
                    )

                try:
                    rect = win32gui.GetWindowRect(self.target_hwnd)
                except Exception as e:
                    raise RuntimeError(
                        f"Failed to query geometry for application window (HWND {self.target_hwnd}): {e}. "
                        "Please restore or reselect the window."
                    ) from e

                left, top, right, bottom = rect
                w = right - left
                h = bottom - top
                if w <= 0 or h <= 0:
                    raise RuntimeError(
                        f"Target application window has invalid dimensions ({w}x{h}). "
                        "Please restore or resize the window before capturing."
                    )

                bbox = {
                    "left": max(0, left),
                    "top": max(0, top),
                    "width": w,
                    "height": h,
                }

            # 2. Sub-region target mode
            elif self.target_mode == "region":
                if not self.target_region:
                    raise RuntimeError(
                        "No rectangular region defined. Please configure region coordinates."
                    )
                w = self.target_region.get("width", 0)
                h = self.target_region.get("height", 0)
                if w <= 0 or h <= 0:
                    raise RuntimeError(
                        f"Invalid rectangular region dimensions ({w}x{h}). Width and Height must be greater than zero."
                    )
                bbox = {
                    "left": max(0, self.target_region["left"]),
                    "top": max(0, self.target_region["top"]),
                    "width": w,
                    "height": h,
                }

            # 3. Full monitor target mode (default)
            elif self.target_mode == "monitor":
                monitors = sct.monitors
                idx = monitor_index if monitor_index is not None else self.target_monitor_index
                bbox = monitors[idx] if idx < len(monitors) else monitors[0]

            else:
                raise ValueError(
                    f"Unsupported target mode '{self.target_mode}'. Choose 'monitor', 'window', or 'region'."
                )

            sct_img = sct.grab(bbox)
            img = Image.frombytes("RGB", (sct_img.width, sct_img.height), sct_img.rgb)

            if max_size:
                img.thumbnail(max_size, Image.Resampling.LANCZOS)

            return img

    def capture_frame_bytes(
        self,
        max_size: Optional[Tuple[int, int]] = (1280, 720),
        monitor_index: Optional[int] = None,
    ) -> Tuple[bytes, ScreenCaptureMetadata]:
        """Capture the permitted screen content and return compressed PNG bytes with metadata."""
        try:
            img = self._grab_pil_image(max_size, monitor_index=monitor_index)

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

        except (PermissionError, RuntimeError):
            raise
        except Exception as e:
            logger.error(f"Failed to capture screen frame: {e}")
            raise

    def capture_jpeg_base64(
        self,
        max_size: Optional[Tuple[int, int]] = (1280, 720),
        quality: int = 75,
        monitor_index: Optional[int] = None,
    ) -> Tuple[str, ScreenCaptureMetadata]:
        """Capture and return base64 JPEG for AI vision transmission and approval."""
        try:
            img = self._grab_pil_image(max_size, monitor_index=monitor_index)

            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            jpeg_bytes = buffer.getvalue()
            b64_str = base64.b64encode(jpeg_bytes).decode("ascii")

            metadata = ScreenCaptureMetadata(
                worker_id=self.worker_id,
                width=img.width,
                height=img.height,
                captured_at=current_utc_time(),
                explicit_permission_verified=True,
                format="JPEG",
                frame_size_bytes=len(jpeg_bytes),
            )

            # Record as the approved frame
            self.set_approved_frame(b64_str, metadata)

            return b64_str, metadata

        except (PermissionError, RuntimeError):
            raise
        except Exception as e:
            logger.error(f"Failed to capture JPEG screen frame: {e}")
            raise
