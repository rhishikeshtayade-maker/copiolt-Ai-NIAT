"""Worker lifecycle, registration, and heartbeat endpoints."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, status
from src.common.logger import get_logger
from src.common.schemas import (
    EmergencyStopRequest,
    EmergencyStopResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    WorkerInfo,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
)
from src.controller.manager import worker_manager

logger = get_logger("Controller.Routes.Workers")
router = APIRouter(prefix="/api/v1/workers", tags=["Workers"])


@router.post(
    "/register",
    response_model=WorkerRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new worker laptop",
)
async def register_worker(request: WorkerRegistrationRequest):
    """Register a worker laptop. Explicit user permission must be confirmed in the request."""
    try:
        response = await worker_manager.register_worker(request)
        return response
    except PermissionError as pe:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(pe),
        )
    except Exception as e:
        logger.error(f"Worker registration failure: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}",
        )


@router.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    summary="Worker heartbeat and health pulse",
)
async def worker_heartbeat(request: HeartbeatRequest):
    """Receive worker heartbeat, record metrics, and return queued control commands."""
    try:
        response = await worker_manager.process_heartbeat(request)
        return response
    except Exception as e:
        logger.error(f"Error processing heartbeat for {request.worker_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing heartbeat",
        )


@router.get(
    "",
    response_model=List[WorkerInfo],
    summary="List all registered workers",
)
async def list_workers():
    """Retrieve state and metrics for all registered workers."""
    return await worker_manager.get_all_workers()


@router.get(
    "/{worker_id}",
    response_model=WorkerInfo,
    summary="Get single worker details",
)
async def get_worker_status(worker_id: str):
    """Retrieve details for a specific worker."""
    worker = await worker_manager.get_worker(worker_id)
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker '{worker_id}' not found",
        )
    return worker


@router.post(
    "/emergency-stop",
    response_model=EmergencyStopResponse,
    summary="Halt all or specific workers immediately",
)
async def emergency_stop_all(request: Optional[EmergencyStopRequest] = None):
    """Emergency halt for all active workers or a specified worker."""
    target_id = request.worker_id if request else None
    reason = request.reason if request else "Emergency stop triggered"
    affected = await worker_manager.trigger_emergency_stop(target_id, reason)
    return EmergencyStopResponse(
        success=True,
        affected_workers=affected,
        message=f"Emergency stop executed across {len(affected)} worker(s).",
    )


@router.post(
    "/{worker_id}/emergency-stop",
    response_model=EmergencyStopResponse,
    summary="Halt a specific worker immediately",
)
async def emergency_stop_worker(worker_id: str):
    """Trigger emergency stop specifically for one worker."""
    affected = await worker_manager.trigger_emergency_stop(
        target_worker_id=worker_id, reason="Worker-specific emergency halt"
    )
    if not affected:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker '{worker_id}' not registered",
        )
    return EmergencyStopResponse(
        success=True,
        affected_workers=affected,
        message=f"Worker '{worker_id}' halted immediately.",
    )
