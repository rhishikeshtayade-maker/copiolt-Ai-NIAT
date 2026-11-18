"""Task coordination and policy enforcement endpoints."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from src.common.config import settings
from src.common.logger import get_logger

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
