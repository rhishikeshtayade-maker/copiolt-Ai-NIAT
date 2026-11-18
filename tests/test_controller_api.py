"""Integration tests for the FastAPI Central Controller routes."""

import pytest
from httpx import ASGITransport, AsyncClient
from src.controller.main import create_app
from src.common.config import settings
from src.common.constants import WorkerCommand, WorkerStatus


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_health_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "NIAT CodePilot Controller" in data["service"]


@pytest.mark.asyncio
async def test_worker_registration_and_heartbeat_flow(app):
    transport = ASGITransport(app=app)
    auth_headers = {"X-Worker-Token": settings.controller_secret_key}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Register with consent = False should return 403 Forbidden
        reg_payload_denied = {
            "worker_id": "worker-api-01",
            "worker_name": "API Worker 1",
            "hostname": "test-box",
            "explicit_consent_granted": False,
        }
        resp = await client.post("/api/v1/workers/register", json=reg_payload_denied, headers=auth_headers)
        assert resp.status_code == 403

        # 2. Register with consent = True should succeed
        reg_payload_ok = {
            "worker_id": "worker-api-01",
            "worker_name": "API Worker 1",
            "hostname": "test-box",
            "ip_address": "127.0.0.1",
            "explicit_consent_granted": True,
        }
        resp = await client.post("/api/v1/workers/register", json=reg_payload_ok, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "registered"
        assert data["worker_id"] == "worker-api-01"

        # 3. List workers
        resp = await client.get("/api/v1/workers")
        assert resp.status_code == 200
        workers = resp.json()
        assert any(w["worker_id"] == "worker-api-01" for w in workers)

        # 4. Dispatch heartbeat
        hb_payload = {
            "worker_id": "worker-api-01",
            "status": "ONLINE",
            "cpu_percent": 12.5,
            "memory_percent": 44.0,
            "permission_active": True,
        }
        resp = await client.post("/api/v1/workers/heartbeat", json=hb_payload, headers=auth_headers)
        assert resp.status_code == 200
        hb_data = resp.json()
        assert hb_data["acknowledged"] is True
        assert hb_data["command"] == "NONE"

        # 5. Trigger emergency stop
        stop_resp = await client.post(
            "/api/v1/workers/emergency-stop",
            json={"worker_id": "worker-api-01", "reason": "Test emergency"},
        )
        assert stop_resp.status_code == 200
        stop_data = stop_resp.json()
        assert "worker-api-01" in stop_data["affected_workers"]

        # 6. Next heartbeat must receive EMERGENCY_STOP command
        resp = await client.post("/api/v1/workers/heartbeat", json=hb_payload, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["command"] == "EMERGENCY_STOP"


@pytest.mark.asyncio
async def test_anti_bot_submission_prevention(app):
    """Verify that automated portal submission attempts are rejected."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Attempt automatic submission
        payload = {
            "worker_id": "worker-api-01",
            "task_id": "task-99",
            "code_content": "def solution(): return 42",
            "attempt_portal_submission": True,
        }
        resp = await client.post("/api/v1/tasks/submit-review", json=payload)
        assert resp.status_code == 400
        assert "strictly prohibited" in resp.json()["detail"]

        # Valid human-in-the-loop review queue submission
        valid_payload = {
            "worker_id": "worker-api-01",
            "task_id": "task-99",
            "code_content": "def solution(): return 42",
            "attempt_portal_submission": False,
        }
        resp = await client.post("/api/v1/tasks/submit-review", json=valid_payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_student_review"
