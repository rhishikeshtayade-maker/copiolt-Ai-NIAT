"""Health and diagnostic endpoints."""

from fastapi import APIRouter
from src.common.schemas import current_utc_time
from src.controller.db import db_service

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Controller health status check."""
    return {
        "status": "healthy",
        "service": "NIAT CodePilot Controller",
        "timestamp": current_utc_time().isoformat(),
        "database_connected": db_service.is_connected,
    }
