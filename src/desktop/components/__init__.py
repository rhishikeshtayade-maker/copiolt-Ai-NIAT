"""UI components and custom widgets for PySide6."""

from src.desktop.components.ai_orb import AIOrbWidget, AIOrbContainer, OrbState
from src.desktop.components.floating_controls import FloatingControlsDock
from src.desktop.components.coding_workspace import CodingWorkspaceWidget
from src.desktop.components.preview_widget import ScreenPreviewWidget
from src.desktop.components.status_bar import ConnectionStatusBar
from src.desktop.components.action_timeline import ActionTimelineWidget
from src.desktop.components.practice_editor import PracticeEditorWindow
from src.worker.interaction import (
    TimelineEvent,
    TimelineEventType,
    TimelineEventStatus,
    KeyboardComputerUseAgent,
    EditorFocusLostError,
    EmergencyStopError,
)

__all__ = [
    "AIOrbWidget",
    "AIOrbContainer",
    "OrbState",
    "FloatingControlsDock",
    "CodingWorkspaceWidget",
    "ScreenPreviewWidget",
    "ConnectionStatusBar",
    "ActionTimelineWidget",
    "PracticeEditorWindow",
    "TimelineEvent",
    "TimelineEventType",
    "TimelineEventStatus",
    "KeyboardComputerUseAgent",
    "EditorFocusLostError",
    "EmergencyStopError",
]
