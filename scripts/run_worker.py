"""Launch script for the NIAT CodePilot Worker Desktop Client."""

import argparse
import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.common.config import settings
from src.common.logger import get_logger
from src.desktop.main import main as run_desktop_app

logger = get_logger("Launcher.Worker")


def main():
    parser = argparse.ArgumentParser(description="Run NIAT CodePilot Worker Desktop App")
    parser.add_argument("--id", default=None, help="Worker ID (overrides WORKER_ID in .env)")
    parser.add_argument("--name", default=None, help="Worker Name (overrides WORKER_NAME in .env)")
    parser.add_argument("--controller", default=None, help="Controller URL (overrides CONTROLLER_URL in .env)")

    args = parser.parse_args()

    if args.id:
        settings.worker_id = args.id
    if args.name:
        settings.worker_name = args.name
    if args.controller:
        settings.controller_url = args.controller

    logger.info(f"Launching Worker '{settings.worker_id}' targeting {settings.controller_url}...")
    sys.exit(run_desktop_app())


if __name__ == "__main__":
    main()
