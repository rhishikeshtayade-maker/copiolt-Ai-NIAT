"""Screen capture preview widget for the PySide6 desktop client."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class ScreenPreviewWidget(QFrame):
    """Displays live or snapshot screen capture previews with consent watermarks."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.setStyleSheet(
            """
            ScreenPreviewWidget {
                background-color: #1e1e1e;
                border: 2px dashed #3c3c3c;
                border-radius: 8px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setText("Screen Capture Inactive\n(Explicit user consent required)")
        self.image_label.setStyleSheet("color: #888888; font-size: 14px; font-weight: bold;")
        layout.addWidget(self.image_label)

        self._current_pixmap: QPixmap = QPixmap()

    def update_frame(self, pixmap: QPixmap, metadata_text: str = "") -> None:
        """Update the widget with a new captured frame pixmap."""
        self._current_pixmap = pixmap
        scaled = pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        if metadata_text:
            self.image_label.setToolTip(metadata_text)

    def set_placeholder(self, message: str, is_emergency: bool = False) -> None:
        """Clear current pixmap and display an informative placeholder."""
        self._current_pixmap = QPixmap()
        self.image_label.setPixmap(QPixmap())
        color = "#ff4444" if is_emergency else "#888888"
        self.image_label.setText(message)
        self.image_label.setStyleSheet(
            f"color: {color}; font-size: 14px; font-weight: bold; text-align: center;"
        )

    def resizeEvent(self, event) -> None:
        """Rescale current pixmap when window is resized."""
        super().resizeEvent(event)
        if not self._current_pixmap.isNull():
            scaled = self._current_pixmap.scaled(
                self.image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled)
