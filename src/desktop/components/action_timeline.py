"""Action Timeline widget displaying computer-use agent execution steps in real time."""

from typing import Optional
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.worker.interaction import TimelineEvent, TimelineEventStatus, TimelineEventType


class ActionTimelineWidget(QFrame):
    """Real-time timeline displaying granular agent actions:
    - Screen observation ticks
    - Multimodal Gemini problem detection
    - Editor focus verification
    - Keyboard typing chunks (with character count & progress)
    - Code comparison & verification
    - Focus-loss & emergency stop events
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ActionTimeline")
        self.setMinimumHeight(160)
        self.setMaximumHeight(260)
        self._events_count: int = 0

        self._init_ui()
        self._apply_glass_styles()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        # Header bar
        header = QHBoxLayout()
        header.setSpacing(8)

        icon_lbl = QLabel("⏱️", self)
        icon_lbl.setStyleSheet("font-size: 13px;")
        header.addWidget(icon_lbl)

        title = QLabel("Action Timeline • Computer-Use Agent", self)
        title.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: bold; letter-spacing: 0.5px;")
        header.addWidget(title)

        self.counter_badge = QLabel("0 Events", self)
        self.counter_badge.setStyleSheet(
            """
            QLabel {
                background-color: rgba(0, 229, 255, 0.15);
                color: #00E5FF;
                border: 1px solid rgba(0, 229, 255, 0.30);
                border-radius: 6px;
                padding: 1px 8px;
                font-size: 10px;
                font-weight: bold;
            }
            """
        )
        header.addWidget(self.counter_badge)

        header.addStretch()

        self.clear_btn = QPushButton("Clear", self)
        self.clear_btn.setFixedSize(50, 22)
        self.clear_btn.clicked.connect(self.clear_timeline)
        self.clear_btn.setStyleSheet(
            """
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                color: #A0AEC0;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 4px;
                font-size: 10px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
                color: #FFFFFF;
            }
            """
        )
        header.addWidget(self.clear_btn)

        layout.addLayout(header)

        # Scrollable event list
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.events_container = QWidget()
        self.events_layout = QVBoxLayout(self.events_container)
        self.events_layout.setContentsMargins(0, 0, 0, 0)
        self.events_layout.setSpacing(6)
        self.events_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.placeholder = QLabel("Standing by. Agent actions (observation, focus check, keyboard chunks) will appear here.", self)
        self.placeholder.setStyleSheet("color: #64748B; font-size: 11px; padding: 10px 0;")
        self.events_layout.addWidget(self.placeholder)

        self.scroll_area.setWidget(self.events_container)
        layout.addWidget(self.scroll_area, 1)

    def _apply_glass_styles(self) -> None:
        self.setStyleSheet(
            """
            #ActionTimeline {
                background-color: rgba(12, 17, 28, 0.85);
                border: 1px solid rgba(0, 229, 255, 0.18);
                border-radius: 12px;
            }
            """
        )

    def add_event(self, event: TimelineEvent) -> None:
        """Append a new action event to the live timeline."""
        if self.placeholder.isVisible():
            self.placeholder.setVisible(False)

        self._events_count += 1
        self.counter_badge.setText(f"{self._events_count} Events")

        item = QFrame(self)
        item.setStyleSheet(
            """
            QFrame {
                background-color: rgba(18, 24, 38, 0.70);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 6px;
                padding: 4px 8px;
            }
            """
        )
        row = QHBoxLayout(item)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(8)

        # Status icon
        status_icons = {
            TimelineEventStatus.SUCCESS: ("🟢", "#00E676"),
            TimelineEventStatus.IN_PROGRESS: ("🔵", "#2979FF"),
            TimelineEventStatus.WARNING: ("🟡", "#FFD600"),
            TimelineEventStatus.FAILED: ("🔴", "#FF1744"),
            TimelineEventStatus.PENDING: ("⚪", "#94A3B8"),
        }
        icon, color = status_icons.get(event.status, ("⚪", "#94A3B8"))
        icon_lbl = QLabel(icon, item)
        icon_lbl.setFixedWidth(16)
        row.addWidget(icon_lbl)

        # Timestamp badge
        time_lbl = QLabel(event.timestamp, item)
        time_lbl.setStyleSheet("color: #64748B; font-family: monospace; font-size: 10px;")
        time_lbl.setFixedWidth(55)
        row.addWidget(time_lbl)

        # Event type badge
        type_colors = {
            TimelineEventType.OBSERVE: ("#00E5FF", "rgba(0, 229, 255, 0.15)"),
            TimelineEventType.ANALYZE: ("#B388FF", "rgba(124, 77, 255, 0.18)"),
            TimelineEventType.FOCUS_CHECK: ("#80D8FF", "rgba(41, 121, 255, 0.18)"),
            TimelineEventType.TYPE_CHUNK: ("#69F0AE", "rgba(0, 230, 118, 0.15)"),
            TimelineEventType.VERIFY: ("#FFD180", "rgba(255, 171, 0, 0.15)"),
            TimelineEventType.PAUSE: ("#FFE57F", "rgba(255, 214, 0, 0.15)"),
            TimelineEventType.EMERGENCY_STOP: ("#FF5252", "rgba(255, 23, 68, 0.25)"),
            TimelineEventType.ERROR: ("#FF5252", "rgba(255, 23, 68, 0.25)"),
        }
        fg, bg = type_colors.get(event.event_type, ("#CBD5E1", "rgba(255, 255, 255, 0.10)"))
        type_lbl = QLabel(event.event_type.value, item)
        type_lbl.setStyleSheet(
            f"color: {fg}; background-color: {bg}; border-radius: 4px; padding: 2px 6px; font-size: 9px; font-weight: bold;"
        )
        row.addWidget(type_lbl)

        # Title & Description
        detail_col = QVBoxLayout()
        detail_col.setSpacing(1)
        title_lbl = QLabel(event.title, item)
        title_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 11px;")
        detail_col.addWidget(title_lbl)

        if event.description:
            desc_lbl = QLabel(event.description, item)
            desc_lbl.setStyleSheet("color: #94A3B8; font-size: 10px;")
            desc_lbl.setWordWrap(True)
            detail_col.addWidget(desc_lbl)
        row.addLayout(detail_col, 1)

        self.events_layout.addWidget(item)

        # Autoscroll to bottom
        QTimer.singleShot(20, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def clear_timeline(self) -> None:
        """Clear all events and reset placeholder."""
        while self.events_layout.count() > 1:
            child = self.events_layout.takeAt(1)
            if child.widget():
                child.widget().deleteLater()
        self._events_count = 0
        self.counter_badge.setText("0 Events")
        self.placeholder.setVisible(True)
