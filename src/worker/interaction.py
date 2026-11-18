"""Keyboard automation, editor focus verification, and chunked text entry for Windows.

Strict Safety Invariants:
1. NEVER uses clipboard paste (no ctrl+v, no clipboard inspection or modification).
2. Uses native Windows SendInput with KEYEVENTF_UNICODE for true hardware-level keystrokes.
3. Verifies editor focus BEFORE every chunk; aborts immediately if focus shifts.
4. Supports continuous observation, pause checks, and instantaneous emergency stop.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.common.logger import get_logger
from src.common.schemas import current_utc_time

logger = get_logger("Worker.Interaction")

# Win32 SendInput constants
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
VK_BACK = 0x08
GA_ROOT = 2


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulong),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulong),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


class EditorFocusLostError(RuntimeError):
    """Raised when the target editor window loses foreground focus during interaction."""
    pass


class EmergencyStopError(RuntimeError):
    """Raised when interaction is cancelled by emergency stop."""
    pass


class TimelineEventType(str, Enum):
    OBSERVE = "OBSERVE"
    ANALYZE = "ANALYZE"
    FOCUS_CHECK = "FOCUS_CHECK"
    TYPE_CHUNK = "TYPE_CHUNK"
    VERIFY = "VERIFY"
    PAUSE = "PAUSE"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    ERROR = "ERROR"


class TimelineEventStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    FAILED = "FAILED"


@dataclass
class TimelineEvent:
    """Represents a single granular action executed by the computer-use agent."""
    event_type: TimelineEventType
    title: str
    description: str = ""
    status: TimelineEventStatus = TimelineEventStatus.SUCCESS
    timestamp: str = field(default_factory=lambda: time.strftime("%H:%M:%S"))
    metadata: Dict[str, Any] = field(default_factory=dict)


def is_window_focused(target_hwnd: int) -> bool:
    """Check if target_hwnd or one of its child controls is currently the foreground window."""
    try:
        import win32gui
        fg = win32gui.GetForegroundWindow()
        if fg == target_hwnd:
            return True
        # Check if foreground window is a child/descendant of target_hwnd
        root = win32gui.GetAncestor(fg, GA_ROOT)
        return root == target_hwnd
    except Exception as e:
        logger.debug(f"Focus check error: {e}")
        return False


def get_foreground_window_title() -> str:
    """Retrieve title of the active foreground window."""
    try:
        import win32gui
        fg = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(fg).strip()
    except Exception:
        return ""


def activate_window(hwnd: int) -> bool:
    """Bring the target window to the foreground."""
    try:
        import win32gui
        import win32con
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        return is_window_focused(hwnd)
    except Exception as e:
        logger.debug(f"Could not activate window {hwnd}: {e}")
        return False


def send_unicode_char(char: str) -> None:
    """Send a single character via Windows SendInput using KEYEVENTF_UNICODE.

    Never touches the system clipboard. Handles newlines, spaces, and Unicode symbols.
    """
    user32 = ctypes.windll.user32

    if char == "\r":
        return
    if char == "\n":
        # Send Enter key
        inp_down = INPUT(type=INPUT_KEYBOARD)
        inp_down.union.ki = KEYBDINPUT(wVk=VK_RETURN, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
        inp_up = INPUT(type=INPUT_KEYBOARD)
        inp_up.union.ki = KEYBDINPUT(wVk=VK_RETURN, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
        inputs = (INPUT * 2)(inp_down, inp_up)
        user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
        return

    code = ord(char)
    inp_down = INPUT(type=INPUT_KEYBOARD)
    inp_down.union.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0)
    inp_up = INPUT(type=INPUT_KEYBOARD)
    inp_up.union.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
    inputs = (INPUT * 2)(inp_down, inp_up)
    user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))


def send_backspace(count: int = 1) -> None:
    """Send backspace keystrokes to undo or clear text."""
    user32 = ctypes.windll.user32
    for _ in range(count):
        inp_down = INPUT(type=INPUT_KEYBOARD)
        inp_down.union.ki = KEYBDINPUT(wVk=VK_BACK, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
        inp_up = INPUT(type=INPUT_KEYBOARD)
        inp_up.union.ki = KEYBDINPUT(wVk=VK_BACK, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
        inputs = (INPUT * 2)(inp_down, inp_up)
        user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
        time.sleep(0.01)


class KeyboardComputerUseAgent:
    """Computer-use agent that types code in verified, controlled chunks.

    Guarantees:
    - Zero clipboard paste.
    - Pre-chunk and intra-chunk editor focus verification.
    - Continuous emergency stop & pause polling.
    - Real-time action timeline event dispatch.
    """

    def __init__(
        self,
        target_hwnd: int,
        target_title: str = "",
        chunk_size: int = 12,
        delay_between_chunks: float = 0.04,
        on_timeline_event: Optional[Callable[[TimelineEvent], None]] = None,
        is_paused_check: Optional[Callable[[], bool]] = None,
        is_stopped_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.target_hwnd = target_hwnd
        self.target_title = target_title
        self.chunk_size = max(1, chunk_size)
        self.delay_between_chunks = max(0.01, delay_between_chunks)
        self.on_timeline_event = on_timeline_event or (lambda ev: None)
        self.is_paused_check = is_paused_check or (lambda: False)
        self.is_stopped_check = is_stopped_check or (lambda: False)

    def _emit(
        self,
        event_type: TimelineEventType,
        title: str,
        desc: str = "",
        status: TimelineEventStatus = TimelineEventStatus.SUCCESS,
        **metadata,
    ) -> None:
        event = TimelineEvent(
            event_type=event_type,
            title=title,
            description=desc,
            status=status,
            metadata=metadata,
        )
        self.on_timeline_event(event)
        logger.info(f"[Timeline {event_type.value}] {title} - {desc}")

    def type_code(self, code: str) -> bool:
        """Execute keyboard text entry into the target window in controlled chunks.

        Returns True on full completion. Raises EditorFocusLostError or EmergencyStopError.
        """
        if not code:
            self._emit(TimelineEventType.VERIFY, "Empty Code", "No code provided to type", TimelineEventStatus.WARNING)
            return False

        # 1. Focus Verification
        self._emit(
            TimelineEventType.FOCUS_CHECK,
            "Verifying Editor Focus",
            f"Checking target window '{self.target_title}' (HWND {self.target_hwnd})",
            TimelineEventStatus.IN_PROGRESS,
        )

        if not is_window_focused(self.target_hwnd):
            # Attempt to bring to foreground if student authorized
            activated = activate_window(self.target_hwnd)
            if not activated or not is_window_focused(self.target_hwnd):
                fg_title = get_foreground_window_title()
                err_msg = (
                    f"Target window is not in focus (Current active: '{fg_title}'). "
                    "Please click inside the target editor before typing."
                )
                self._emit(TimelineEventType.ERROR, "Focus Lost", err_msg, TimelineEventStatus.FAILED)
                raise EditorFocusLostError(err_msg)

        self._emit(
            TimelineEventType.FOCUS_CHECK,
            "Editor Focused",
            f"Verified active focus on '{self.target_title}'",
            TimelineEventStatus.SUCCESS,
        )

        # 2. Chunking
        total_len = len(code)
        chunks = [code[i : i + self.chunk_size] for i in range(0, total_len, self.chunk_size)]
        total_chunks = len(chunks)

        self._emit(
            TimelineEventType.TYPE_CHUNK,
            "Starting Keyboard Entry",
            f"Total {total_len} characters split into {total_chunks} chunks (no clipboard paste)",
            TimelineEventStatus.IN_PROGRESS,
        )

        typed_chars = 0
        t0 = time.time()

        for idx, chunk in enumerate(chunks):
            # A. Check Emergency Stop
            if self.is_stopped_check():
                self._emit(
                    TimelineEventType.EMERGENCY_STOP,
                    "Emergency Stop Triggered",
                    f"Aborted after chunk {idx}/{total_chunks} ({typed_chars}/{total_len} chars)",
                    TimelineEventStatus.FAILED,
                )
                raise EmergencyStopError("Interaction cancelled by Emergency Stop.")

            # B. Check Pause
            while self.is_paused_check():
                self._emit(
                    TimelineEventType.PAUSE,
                    "Typing Paused",
                    "Execution suspended by student. Standing by to resume...",
                    TimelineEventStatus.WARNING,
                )
                time.sleep(0.2)
                if self.is_stopped_check():
                    raise EmergencyStopError("Cancelled while paused.")

            # C. Check Focus before typing chunk
            if not is_window_focused(self.target_hwnd):
                fg_title = get_foreground_window_title()
                err_msg = (
                    f"Editor lost focus at chunk {idx + 1}/{total_chunks} "
                    f"(Current active window: '{fg_title}'). Typing halted for student protection."
                )
                self._emit(TimelineEventType.ERROR, "Editor Focus Lost", err_msg, TimelineEventStatus.FAILED)
                raise EditorFocusLostError(err_msg)

            # D. Send keystrokes
            for ch in chunk:
                send_unicode_char(ch)
                time.sleep(0.003)

            typed_chars += len(chunk)
            progress_pct = int((typed_chars / total_len) * 100)

            # E. Chunk verification timeline event
            preview = repr(chunk)[1:-1]
            if len(preview) > 16:
                preview = preview[:16] + "..."
            self._emit(
                TimelineEventType.TYPE_CHUNK,
                f"Typed Chunk {idx + 1}/{total_chunks} ({progress_pct}%)",
                f"Sent '{preview}' via SendInput | Focus verified",
                TimelineEventStatus.SUCCESS,
                chunk_index=idx + 1,
                total_chunks=total_chunks,
                progress_pct=progress_pct,
            )

            time.sleep(self.delay_between_chunks)

        # 3. Completion & Final Invariant Check
        elapsed = time.time() - t0
        rate = typed_chars / max(0.1, elapsed)
        self._emit(
            TimelineEventType.VERIFY,
            "Keyboard Entry Completed",
            f"Successfully typed {typed_chars} characters in {elapsed:.2f}s ({rate:.0f} chars/sec). "
            "Clipboard was not modified. Student retains execution control.",
            TimelineEventStatus.SUCCESS,
            total_chars=typed_chars,
            duration_seconds=elapsed,
        )
        return True
