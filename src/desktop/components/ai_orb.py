"""Central Floating AI Assistant Orb with state-driven dynamic animations."""

import math
from enum import Enum
from typing import Optional
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class OrbState(Enum):
    """Operational states of the NIAT CodePilot AI Assistant Orb."""
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    ANALYZING_SCREEN = "analyzing_screen"
    RESPONDING = "responding"
    ERROR = "error"


class AIOrbWidget(QWidget):
    """Visually distinctive, hardware-accelerated animated AI Orb.

    Renders balanced futuristic glass-and-energy states using layered gradients:
    - IDLE: Soft cyan/electric-blue gentle respiratory pulse with subtle aura.
    - LISTENING: Responsive concentric ripples mimicking audio/voice interaction.
    - THINKING: Dual orbiting violet/cyan gradient particle rings with continuous rotation.
    - ANALYZING_SCREEN: Electric-blue focus sweep beam with radial scan pulses.
    - RESPONDING: Warm violet & cyan harmonic radiance with gentle energy shimmer.
    - ERROR: Muted amber/rose warning glow with soft static boundary.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(220, 220)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._state: OrbState = OrbState.IDLE
        self._phase: float = 0.0
        self._rotation_angle: float = 0.0
        self._ripple_radius: float = 0.0
        self._scan_y: float = 0.0

        # Animation loop running at ~60fps (16ms per frame)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    @property
    def state(self) -> OrbState:
        return self._state

    def set_state(self, new_state: OrbState) -> None:
        """Switch orb state with immediate visual feedback."""
        if self._state != new_state:
            self._state = new_state
            self.update()

    def _on_tick(self) -> None:
        """Update animation phases based on active state."""
        self._phase += 0.04
        if self._phase > 2 * math.pi:
            self._phase -= 2 * math.pi

        # State-specific phase progress
        if self._state == OrbState.THINKING:
            self._rotation_angle = (self._rotation_angle + 2.8) % 360.0
        elif self._state == OrbState.LISTENING:
            self._ripple_radius = (self._ripple_radius + 0.9) % 38.0
        elif self._state == OrbState.ANALYZING_SCREEN:
            self._rotation_angle = (self._rotation_angle + 4.0) % 360.0
            self._scan_y = math.sin(self._phase * 1.5)
        elif self._state == OrbState.RESPONDING:
            self._rotation_angle = (self._rotation_angle + 1.2) % 360.0

        self.update()

    def paintEvent(self, event) -> None:
        """Render the layered, balanced futuristic orb."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        base_radius = min(w, h) * 0.30

        # Dynamic breathing offset for idle/responding
        breath = math.sin(self._phase) * (4.0 if self._state != OrbState.ERROR else 1.5)
        core_radius = base_radius + breath

        # -------------------------------------------------------------
        # 1. State-specific background ambient auras
        # -------------------------------------------------------------
        aura_gradient = QRadialGradient(cx, cy, core_radius * 1.9)
        if self._state == OrbState.IDLE:
            aura_gradient.setColorAt(0.0, QColor(0, 229, 255, 38))
            aura_gradient.setColorAt(0.6, QColor(41, 121, 255, 18))
            aura_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        elif self._state == OrbState.LISTENING:
            aura_gradient.setColorAt(0.0, QColor(0, 229, 255, 75))
            aura_gradient.setColorAt(0.5, QColor(0, 180, 216, 35))
            aura_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        elif self._state == OrbState.THINKING:
            aura_gradient.setColorAt(0.0, QColor(124, 77, 255, 65))
            aura_gradient.setColorAt(0.6, QColor(0, 229, 255, 30))
            aura_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        elif self._state == OrbState.ANALYZING_SCREEN:
            aura_gradient.setColorAt(0.0, QColor(0, 229, 255, 80))
            aura_gradient.setColorAt(0.5, QColor(41, 121, 255, 45))
            aura_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        elif self._state == OrbState.RESPONDING:
            aura_gradient.setColorAt(0.0, QColor(179, 136, 255, 70))
            aura_gradient.setColorAt(0.5, QColor(0, 229, 255, 35))
            aura_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        elif self._state == OrbState.ERROR:
            aura_gradient.setColorAt(0.0, QColor(255, 23, 68, 65))
            aura_gradient.setColorAt(0.6, QColor(255, 145, 0, 25))
            aura_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(aura_gradient))
        painter.drawEllipse(QPointF(cx, cy), core_radius * 1.9, core_radius * 1.9)

        # -------------------------------------------------------------
        # 2. Dynamic State Accents (Ripples, Orbiting Rings, Scan Beams)
        # -------------------------------------------------------------
        if self._state == OrbState.LISTENING:
            # Concentric voice-listening ripple rings
            for r_offset in (0.0, 16.0, 32.0):
                r = core_radius + ((self._ripple_radius + r_offset) % 45.0)
                alpha = max(0, int(150 * (1.0 - (r - core_radius) / 45.0)))
                pen = QPen(QColor(0, 229, 255, alpha), 1.6)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), r, r)

        elif self._state == OrbState.THINKING:
            # Dual rotating gradient arc rings
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(self._rotation_angle)
            ring_pen1 = QPen(QColor(124, 77, 255, 200), 2.2)
            painter.setPen(ring_pen1)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arc_rect1 = QRectF(-core_radius * 1.25, -core_radius * 1.25, core_radius * 2.5, core_radius * 2.5)
            painter.drawArc(arc_rect1, 0, 16 * 120)
            painter.drawArc(arc_rect1, 16 * 180, 16 * 120)

            # Counter-rotating outer cyan ring
            painter.rotate(-self._rotation_angle * 2.2)
            ring_pen2 = QPen(QColor(0, 229, 255, 170), 1.4)
            painter.setPen(ring_pen2)
            arc_rect2 = QRectF(-core_radius * 1.4, -core_radius * 1.4, core_radius * 2.8, core_radius * 2.8)
            painter.drawArc(arc_rect2, 16 * 60, 16 * 80)
            painter.drawArc(arc_rect2, 16 * 240, 16 * 80)
            painter.restore()

        elif self._state == OrbState.ANALYZING_SCREEN:
            # Radar/scanner sweep
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(self._rotation_angle)
            scan_grad = QConicalGradient(0, 0, 0)
            scan_grad.setColorAt(0.0, QColor(0, 229, 255, 180))
            scan_grad.setColorAt(0.2, QColor(41, 121, 255, 40))
            scan_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(scan_grad))
            painter.drawPie(
                QRectF(-core_radius * 1.35, -core_radius * 1.35, core_radius * 2.7, core_radius * 2.7),
                0,
                16 * 75,
            )
            painter.restore()

        # -------------------------------------------------------------
        # 3. Outer Glass Ring with Subtle Specular Highlight
        # -------------------------------------------------------------
        glass_ring_rect = QRectF(cx - core_radius * 1.08, cy - core_radius * 1.08, core_radius * 2.16, core_radius * 2.16)
        ring_color = QColor(0, 229, 255, 110) if self._state != OrbState.ERROR else QColor(255, 23, 68, 140)
        ring_pen = QPen(ring_color, 1.8)
        painter.setPen(ring_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(glass_ring_rect)

        # -------------------------------------------------------------
        # 4. Dense Energy Core with Multi-Stop Radial Gradient
        # -------------------------------------------------------------
        core_grad = QRadialGradient(cx - core_radius * 0.25, cy - core_radius * 0.25, core_radius)
        if self._state == OrbState.IDLE:
            core_grad.setColorAt(0.0, QColor(220, 250, 255, 245))
            core_grad.setColorAt(0.25, QColor(0, 229, 255, 220))
            core_grad.setColorAt(0.70, QColor(24, 75, 180, 190))
            core_grad.setColorAt(1.0, QColor(10, 18, 38, 220))
        elif self._state == OrbState.LISTENING:
            core_grad.setColorAt(0.0, QColor(235, 255, 255, 250))
            core_grad.setColorAt(0.25, QColor(0, 229, 255, 240))
            core_grad.setColorAt(0.75, QColor(0, 150, 214, 200))
            core_grad.setColorAt(1.0, QColor(6, 24, 46, 230))
        elif self._state == OrbState.THINKING:
            core_grad.setColorAt(0.0, QColor(245, 235, 255, 250))
            core_grad.setColorAt(0.25, QColor(179, 136, 255, 235))
            core_grad.setColorAt(0.65, QColor(124, 77, 255, 210))
            core_grad.setColorAt(1.0, QColor(20, 12, 44, 230))
        elif self._state == OrbState.ANALYZING_SCREEN:
            core_grad.setColorAt(0.0, QColor(230, 255, 255, 250))
            core_grad.setColorAt(0.25, QColor(0, 229, 255, 240))
            core_grad.setColorAt(0.65, QColor(41, 121, 255, 210))
            core_grad.setColorAt(1.0, QColor(8, 22, 50, 235))
        elif self._state == OrbState.RESPONDING:
            core_grad.setColorAt(0.0, QColor(250, 245, 255, 250))
            core_grad.setColorAt(0.25, QColor(179, 136, 255, 230))
            core_grad.setColorAt(0.65, QColor(0, 229, 255, 195))
            core_grad.setColorAt(1.0, QColor(14, 20, 48, 225))
        elif self._state == OrbState.ERROR:
            core_grad.setColorAt(0.0, QColor(255, 235, 238, 245))
            core_grad.setColorAt(0.25, QColor(255, 23, 68, 230))
            core_grad.setColorAt(0.70, QColor(198, 40, 40, 200))
            core_grad.setColorAt(1.0, QColor(45, 10, 16, 230))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(core_grad))
        painter.drawEllipse(QPointF(cx, cy), core_radius, core_radius)

        # -------------------------------------------------------------
        # 5. Core Specular Glint (Top-Left Light Reflection)
        # -------------------------------------------------------------
        glint_grad = QRadialGradient(cx - core_radius * 0.32, cy - core_radius * 0.32, core_radius * 0.45)
        glint_grad.setColorAt(0.0, QColor(255, 255, 255, 160))
        glint_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(glint_grad))
        painter.drawEllipse(
            QPointF(cx - core_radius * 0.28, cy - core_radius * 0.28),
            core_radius * 0.38,
            core_radius * 0.28,
        )


class AIOrbContainer(QFrame):
    """Encapsulates the AI Orb, dynamic status badge, and sub-text."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            """
            AIOrbContainer {
                background: transparent;
                border: none;
            }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.orb = AIOrbWidget(self)
        layout.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status badge pill
        self.status_badge = QLabel("AI ASSISTANT • READY", self)
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setFixedHeight(28)
        self.status_badge.setStyleSheet(
            """
            QLabel {
                background-color: rgba(0, 229, 255, 0.12);
                color: #00E5FF;
                border: 1px solid rgba(0, 229, 255, 0.35);
                border-radius: 14px;
                padding: 4px 18px;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1.2px;
            }
            """
        )
        layout.addWidget(self.status_badge, alignment=Qt.AlignmentFlag.AlignCenter)

        # Subtitle
        self.sub_label = QLabel("Standing by for coding guidance & visual screen analysis", self)
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label.setStyleSheet(
            "color: #8E9DB8; font-family: 'Segoe UI', sans-serif; font-size: 12px; margin-top: 4px;"
        )
        layout.addWidget(self.sub_label, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_state(self, state: OrbState, custom_message: Optional[str] = None) -> None:
        """Update orb state and synchronized status text."""
        self.orb.set_state(state)

        state_configs = {
            OrbState.IDLE: (
                "AI ASSISTANT • READY",
                "rgba(0, 229, 255, 0.12)",
                "#00E5FF",
                "rgba(0, 229, 255, 0.35)",
                custom_message or "Standing by for coding guidance & visual screen analysis",
            ),
            OrbState.LISTENING: (
                "LISTENING • VOICE DETECTED",
                "rgba(0, 229, 255, 0.22)",
                "#00E5FF",
                "rgba(0, 229, 255, 0.60)",
                custom_message or "Listening to your request... Speak now or release to send.",
            ),
            OrbState.THINKING: (
                "THINKING • SYNTHESIZING SOLUTION",
                "rgba(124, 77, 255, 0.22)",
                "#B388FF",
                "rgba(124, 77, 255, 0.55)",
                custom_message or "Consulting Gemini AI with multimodal screenshot context...",
            ),
            OrbState.ANALYZING_SCREEN: (
                "ANALYZING • SCREEN CAPTURE IN PROGRESS",
                "rgba(41, 121, 255, 0.25)",
                "#80D8FF",
                "rgba(41, 121, 255, 0.65)",
                custom_message or "Capturing approved window frame with student consent...",
            ),
            OrbState.RESPONDING: (
                "SOLUTION READY • REVIEW GUIDANCE",
                "rgba(0, 230, 118, 0.18)",
                "#69F0AE",
                "rgba(0, 230, 118, 0.45)",
                custom_message or "Structured algorithmic breakdown ready in the workspace.",
            ),
            OrbState.ERROR: (
                "ALERT • ATTENTION REQUIRED",
                "rgba(255, 23, 68, 0.20)",
                "#FF5252",
                "rgba(255, 23, 68, 0.55)",
                custom_message or "Action paused. Check target window or network connection.",
            ),
        }

        badge_text, bg, fg, border, subtitle = state_configs[state]
        self.status_badge.setText(badge_text)
        self.status_badge.setStyleSheet(
            f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 14px;
                padding: 4px 18px;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1.2px;
            }}
            """
        )
        self.sub_label.setText(subtitle)
