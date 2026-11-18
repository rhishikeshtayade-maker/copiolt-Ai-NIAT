"""System constants and enums for NIAT CodePilot."""

from enum import Enum


class WorkerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ONLINE = "ONLINE"
    BUSY = "BUSY"
    OFFLINE = "OFFLINE"
    PAUSED = "PAUSED"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"


class WorkerCommand(str, Enum):
    NONE = "NONE"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EthicsPolicy:
    """Core ethical & regulatory boundaries enforced across all modules."""

    ALLOW_AUTOMATED_PORTAL_SUBMISSION: bool = False
    REQUIRE_EXPLICIT_SCREEN_CONSENT: bool = True
    ALLOW_PASSWORD_STORAGE: bool = False
    REQUIRE_STUDENT_APPROVAL_CONSEQUENTIAL_ACTIONS: bool = True
