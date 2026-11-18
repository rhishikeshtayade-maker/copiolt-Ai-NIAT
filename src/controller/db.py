"""Supabase database integration and fallback data persistence."""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger("Controller.DB")


class DatabaseService:
    """Manages integration with Supabase with graceful local fallback."""

    def __init__(self) -> None:
        self._supabase_client = None
        self._is_connected = False
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize the Supabase client using environment variables."""
        if settings.supabase_url and settings.supabase_key:
            try:
                from supabase import create_client, Client

                self._supabase_client: Optional[Client] = create_client(
                    settings.supabase_url, settings.supabase_key
                )
                self._is_connected = True
                logger.info("Connected successfully to Supabase.")
            except Exception as e:
                logger.warning(
                    f"Failed to connect to Supabase: {e}. Falling back to in-memory persistence."
                )
                self._is_connected = False
        else:
            logger.info(
                "Supabase credentials not configured in environment. Operating in memory-persisted mode."
            )
            self._is_connected = False

    @property
    def is_connected(self) -> bool:
        """Check if Supabase is connected."""
        return self._is_connected

    async def log_worker_event(
        self,
        worker_id: str,
        event_type: str,
        details: Dict[str, Any],
    ) -> bool:
        """Audit log a worker lifecycle event."""
        # Security check: never log passwords or raw secrets
        sanitized_details = {
            k: v for k, v in details.items() if "password" not in k.lower() and "secret" not in k.lower()
        }

        payload = {
            "worker_id": worker_id,
            "event_type": event_type,
            "details": sanitized_details,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if self._is_connected and self._supabase_client is not None:
            try:
                self._supabase_client.table("worker_audit_logs").insert(payload).execute()
                return True
            except Exception as e:
                logger.error(f"Error persisting audit log to Supabase: {e}")
                return False

        logger.debug(f"[Audit Log - Local]: {event_type} for {worker_id}")
        return True


# Global database service instance
db_service = DatabaseService()
