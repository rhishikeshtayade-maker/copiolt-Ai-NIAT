"""Launch script for the NIAT CodePilot Central Controller."""

import argparse
import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import uvicorn
from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger("Launcher.Controller")


def main():
    parser = argparse.ArgumentParser(description="Run NIAT CodePilot Central Controller")
    parser.add_argument("--host", default=settings.controller_host, help="Host address (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=settings.controller_port, help="Port (default 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument("--secret", default=None, help="Controller secret key (overrides CONTROLLER_SECRET_KEY in .env)")

    args = parser.parse_args()

    if args.secret:
        clean_secret = args.secret.strip().strip("'\"")
        settings.controller_secret_key = clean_secret
        os.environ["CONTROLLER_SECRET_KEY"] = clean_secret

    logger.info(f"Starting NIAT CodePilot Controller on http://{args.host}:{args.port}")
    uvicorn.run("src.controller.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
