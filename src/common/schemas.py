"""Pydantic data schemas for API requests, responses, and internal models."""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from src.common.constants import WorkerCommand, WorkerStatus


def current_utc_time() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class WorkerRegistrationRequest(BaseModel):
    """Payload sent by a worker laptop when registering with the central controller."""

    worker_id: str = Field(..., min_length=2, max_length=64, description="Unique worker identifier")
    worker_name: str = Field(..., min_length=1, max_length=128, description="Human readable name")
    hostname: str = Field(..., description="Machine hostname")
    ip_address: Optional[str] = Field(default=None, description="Worker local IP address")
    capabilities: List[str] = Field(
        default_factory=lambda: ["screen_capture", "ai_reasoning"],
        description="List of capabilities supported by the worker",
    )
    explicit_consent_granted: bool = Field(
        ...,
        description="Whether the user on this worker machine has explicitly consented to participate and capture permitted screen areas",
    )
    auth_token: Optional[str] = Field(
        default=None,
        description="Shared secret token for authenticated registration",
    )
    metadata: Dict[str, str] = Field(default_factory=dict)


class WorkerRegistrationResponse(BaseModel):
    """Payload returned by controller upon successful registration."""

    status: str = "registered"
    worker_id: str
    heartbeat_interval_seconds: float
    registered_at: datetime = Field(default_factory=current_utc_time)
    message: str = "Worker registered successfully"


class HeartbeatRequest(BaseModel):
    """Heartbeat sent periodically by workers to the controller."""

    worker_id: str
    status: WorkerStatus = WorkerStatus.ONLINE
    cpu_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    memory_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    timestamp: datetime = Field(default_factory=current_utc_time)
    current_task_id: Optional[str] = None
    permission_active: bool = Field(
        default=False,
        description="Indicates whether the user currently has screen capture permission toggled ON",
    )
    auth_token: Optional[str] = Field(
        default=None,
        description="Shared secret token for authenticated heartbeat pulse",
    )


class HeartbeatResponse(BaseModel):
    """Response returned by controller acknowledging worker heartbeat."""

    acknowledged: bool = True
    command: WorkerCommand = WorkerCommand.NONE
    server_time: datetime = Field(default_factory=current_utc_time)
    message: Optional[str] = None


class WorkerInfo(BaseModel):
    """Detailed worker state maintained by the Controller."""

    worker_id: str
    worker_name: str
    hostname: str
    ip_address: Optional[str] = None
    status: WorkerStatus = WorkerStatus.REGISTERED
    connection_status: str = Field(
        default="CONNECTED",
        description="Human-readable connection health: CONNECTED, RECONNECTING, or DISCONNECTED",
    )
    last_heartbeat: datetime = Field(default_factory=current_utc_time)
    registered_at: datetime = Field(default_factory=current_utc_time)
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    capabilities: List[str] = Field(default_factory=list)
    permission_active: bool = False
    pending_command: WorkerCommand = WorkerCommand.NONE
    current_task_id: Optional[str] = None


class ScreenCaptureMetadata(BaseModel):
    """Metadata regarding a captured screen frame."""

    worker_id: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    captured_at: datetime = Field(default_factory=current_utc_time)
    explicit_permission_verified: bool = True
    format: str = "PNG"
    frame_size_bytes: int = Field(ge=0)


class EmergencyStopRequest(BaseModel):
    """Payload to trigger an immediate emergency halt on one or all workers."""

    worker_id: Optional[str] = Field(
        default=None,
        description="Worker to halt, or null/empty to halt all active workers",
    )
    reason: str = Field(default="Emergency stop triggered by operator", max_length=256)


class EmergencyStopResponse(BaseModel):
    """Confirmation of emergency stop execution."""

    success: bool
    affected_workers: List[str]
    timestamp: datetime = Field(default_factory=current_utc_time)
    message: str


class AIAnalysisRequest(BaseModel):
    """Request for AI vision and reasoning on permitted screen capture content."""

    worker_id: str
    prompt: str = Field(..., min_length=3, description="Question or task explanation request")
    image_base64: Optional[str] = Field(
        default=None,
        description="Base64 encoded permitted screenshot",
    )
    explicit_student_approval: bool = Field(
        default=False,
        description="Consent confirmation that screenshot is permitted content",
    )


class AIAnalysisResponse(BaseModel):
    """Response returned by the AI engine with explanations and coding guidance."""

    worker_id: str
    explanation: str
    suggested_code: Optional[str] = None
    requires_student_review: bool = True
    auto_submission_permitted: bool = False
    analyzed_at: datetime = Field(default_factory=current_utc_time)


class EdgeCase(BaseModel):
    """A single edge case identified during problem analysis."""

    description: str = Field(..., description="Description of the edge case")
    example_input: Optional[str] = Field(default=None, description="Example input triggering this case")
    expected_behavior: Optional[str] = Field(default=None, description="Expected output or behavior")


class CodingAnalysisResult(BaseModel):
    """Structured breakdown of a coding problem identified from a screenshot.

    Returned by the AI engine after vision analysis of permitted screen content.
    All fields require explicit student review before any action is taken.
    """

    # Problem identification
    problem_title: str = Field(default="Untitled Problem", description="Short title of the visible coding problem")
    problem_description: str = Field(default="", description="Full problem statement as read from the screen")
    programming_language: Optional[str] = Field(default=None, description="Detected programming language")

    # Constraints and I/O
    constraints: List[str] = Field(default_factory=list, description="Extracted constraints and limits")
    input_format: Optional[str] = Field(default=None, description="Expected input format")
    output_format: Optional[str] = Field(default=None, description="Expected output format")
    sample_inputs: List[str] = Field(default_factory=list, description="Visible sample input examples")
    sample_outputs: List[str] = Field(default_factory=list, description="Visible sample output examples")

    # Concepts and approach
    relevant_concepts: List[str] = Field(default_factory=list, description="Data structures, algorithms, or concepts needed")
    step_by_step_explanation: List[str] = Field(default_factory=list, description="Ordered reasoning steps towards a solution")

    # Solution guidance
    suggested_code: Optional[str] = Field(default=None, description="Example solution code for student review")
    code_explanation: Optional[str] = Field(default=None, description="Line-by-line or block-level code walkthrough")

    # Edge cases
    edge_cases: List[EdgeCase] = Field(default_factory=list, description="Potential edge cases to consider")

    # Confidence
    confidence_note: Optional[str] = Field(
        default=None,
        description="AI confidence note, e.g. if the screenshot was partially obscured",
    )

    # Safety flags (always enforced)
    requires_student_review: bool = Field(default=True, description="Always True: student must review before acting")
    auto_submission_permitted: bool = Field(default=False, description="Always False: no automated submissions")


class TaskItem(BaseModel):
    """Worker-isolated coding task queued on the controller."""

    task_id: str = Field(..., description="Unique task identifier")
    worker_id: str = Field(..., description="Target worker ID (tasks are isolated to this worker)")
    title: str = Field(..., description="Task title or problem name")
    description: str = Field(..., description="Task details or problem statement")
    code_context: Optional[str] = Field(default=None, description="Optional starter code or context")
    status: str = Field(default="pending", description="Task lifecycle status (pending, completed, cancelled)")
    created_at: datetime = Field(default_factory=current_utc_time)


class TaskAssignmentRequest(BaseModel):
    """Request payload to assign a task specifically to one worker."""

    worker_id: str = Field(..., description="Worker ID to receive this task")
    title: str = Field(..., min_length=2, max_length=256)
    description: str = Field(..., min_length=2)
    code_context: Optional[str] = None


class TaskAssignmentResponse(BaseModel):
    """Response confirming task assignment to a worker."""

    task_id: str
    worker_id: str
    status: str = "assigned"
    created_at: datetime = Field(default_factory=current_utc_time)
    message: str = "Task successfully queued for worker"


class TaskPollResponse(BaseModel):
    """Response when a worker polls for its own pending tasks."""

    worker_id: str
    has_task: bool
    task: Optional[TaskItem] = None
