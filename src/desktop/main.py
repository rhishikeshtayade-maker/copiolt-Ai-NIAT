"""Entrypoint for the NIAT CodePilot PySide6 Desktop Application."""

import sys
from PySide6.QtWidgets import QApplication
from src.desktop.app import MainWindow
from src.common.logger import get_logger

logger = get_logger("Desktop.Main")


def main() -> int:
    """Run the PySide6 desktop interface."""
    logger.info("Starting NIAT CodePilot Desktop Interface...")
    app = QApplication(sys.argv)
    app.setApplicationName("NIAT CodePilot")
    app.setOrganizationName("NIAT")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
