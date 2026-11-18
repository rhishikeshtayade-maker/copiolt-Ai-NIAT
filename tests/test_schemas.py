"""Unit tests for Pydantic schema validation."""

import pytest
from pydantic import ValidationError
from src.common.constants import WorkerCommand, WorkerStatus
from src.common.schemas import (
    HeartbeatRequest,
    HeartbeatResponse,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
    ScreenCaptureMetadata,
)


def test_worker_registration_valid():
    """Verify valid worker registration schema."""
    req = WorkerRegistrationRequest(
        worker_id="worker-01",
        worker_name="Worker Alpha",
        hostname="laptop-host-01",
        ip_address="192.168.1.101",
        capabilities=["screen_capture", "ai_reasoning"],
        explicit_consent_granted=True,
    )
    assert req.worker_id == "worker-01"
    assert req.explicit_consent_granted is True


def test_worker_registration_missing_consent():
    """Verify registration fails validation if explicit consent field is omitted."""
    with pytest.raises(ValidationError):
        WorkerRegistrationRequest(
            worker_id="worker-01",
            worker_name="Worker Alpha",
            hostname="laptop-host-01",
        )


def test_heartbeat_request_validation():
    """Verify heartbeat model validation including bounds."""
    hb = HeartbeatRequest(
        worker_id="worker-01",
        status=WorkerStatus.ONLINE,
        cpu_percent=45.2,
        memory_percent=60.8,
        permission_active=True,
    )
    assert hb.worker_id == "worker-01"
    assert hb.status == WorkerStatus.ONLINE
    assert hb.permission_active is True

    # Out of bounds CPU should fail
    with pytest.raises(ValidationError):
        HeartbeatRequest(
            worker_id="worker-01",
            cpu_percent=150.0,
        )


def test_heartbeat_response_command():
    """Verify command structure in heartbeat response."""
    resp = HeartbeatResponse(
        acknowledged=True,
        command=WorkerCommand.EMERGENCY_STOP,
    )
    assert resp.command == WorkerCommand.EMERGENCY_STOP
