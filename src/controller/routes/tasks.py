"""Task coordination, worker-isolated task queues, and policy enforcement endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel
from src.common.config import settings
from src.common.logger import get_logger
from src.common.schemas import (
    TaskAssignmentRequest,
    TaskAssignmentResponse,
    TaskItem,
    TaskPollResponse,
)
from src.controller.manager import worker_manager
from src.controller.routes.workers import extract_auth_token

logger = get_logger("Controller.Routes.Tasks")
router = APIRouter(prefix="/api/v1/tasks", tags=["Tasks"])


class TaskSubmissionAttempt(BaseModel):
    worker_id: str
    task_id: str
    code_content: str
    attempt_portal_submission: bool = False


@router.post("/submit-review", summary="Submit code explanation for student review")
async def submit_for_review(payload: TaskSubmissionAttempt):
    """Safety endpoint: strictly forbids automated portal submissions.

    All code assistance must be explicitly reviewed and accepted by the student.
    """
    if payload.attempt_portal_submission or not settings.allow_automated_portal_submission:
        if payload.attempt_portal_submission:
            logger.warning(
                f"Blocked automatic portal submission attempt from worker '{payload.worker_id}'. "
                "Ethics policy strictly requires student-driven manual review."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Automatic portal submissions and anti-bot bypassing are strictly prohibited. "
                    "All generated assistance must be manually reviewed and approved by the student."
                ),
            )

    return {
        "status": "pending_student_review",
        "task_id": payload.task_id,
        "message": "Assistance queued for explicit student verification and approval.",
    }


@router.post(
    "/assign",
    response_model=TaskAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a coding task to a specific worker",
)
async def assign_task(
    request: TaskAssignmentRequest,
    x_worker_token: Optional[str] = Header(None, alias="X-Worker-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Assign a coding task isolated to a single worker laptop."""
    token = extract_auth_token(x_worker_token, authorization)
    if not worker_manager.validate_auth(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing controller secret key.",
        )

    try:
        response = await worker_manager.assign_task(request)
        return response
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(ve),
        )


@router.get(
    "/poll/{worker_id}",
    response_model=TaskPollResponse,
    summary="Worker polls for its own assigned task",
)
async def poll_worker_task(
    worker_id: str,
    x_worker_token: Optional[str] = Header(None, alias="X-Worker-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Worker retrieves next task queued specifically for it.

    Ensures a worker cannot access or receive tasks intended for another worker.
    """
    token = extract_auth_token(x_worker_token, authorization)
    if not worker_manager.validate_auth(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing controller secret key.",
        )

    task = await worker_manager.poll_task_for_worker(worker_id)
    return TaskPollResponse(
        worker_id=worker_id,
        has_task=task is not None,
        task=task,
    )


@router.get(
    "/worker/{worker_id}",
    response_model=List[TaskItem],
    summary="List all tasks queued for a specific worker",
)
async def list_worker_tasks(
    worker_id: str,
    x_worker_token: Optional[str] = Header(None, alias="X-Worker-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """List tasks assigned to a specific worker machine."""
    token = extract_auth_token(x_worker_token, authorization)
    if not worker_manager.validate_auth(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing controller secret key.",
        )

    return await worker_manager.get_tasks_for_worker(worker_id)
