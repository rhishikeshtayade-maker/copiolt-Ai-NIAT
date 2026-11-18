"""Entrypoint for the NIAT CodePilot PySide6 Desktop Application."""

import sys
from src.desktop.app import main as app_main
from src.common.logger import get_logger

logger = get_logger("Desktop.Main")


def main() -> int:
    """Run the PySide6 desktop interface."""
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
