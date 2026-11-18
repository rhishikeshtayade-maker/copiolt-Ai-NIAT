"""Distributed systems integration tests for multi-worker deployment on local network.

Covers:
1. Concurrent registration of Worker Alpha and Worker Beta.
2. Shared secret authentication enforcement and rejection (401).
3. Duplicate worker ID conflict prevention (409) across different hosts.
4. Same-host reconnection and session renewal.
5. Heartbeat expiry and stale worker reaping.
6. Worker client auto-reconnection resilience.
7. Worker-scoped task isolation (preventing cross-worker task delivery).
8. Remote emergency stop across multiple workers.
9. Central controller web dashboard endpoints.
"""

import asyncio
from datetime import timedelta
import pytest
from httpx import ASGITransport, AsyncClient

from src.common.config import settings
from src.common.constants import WorkerCommand, WorkerStatus
from src.common.schemas import (
    HeartbeatRequest,
    TaskAssignmentRequest,
    WorkerRegistrationRequest,
    current_utc_time,
)
from src.controller.main import create_app
from src.controller.manager import worker_manager
from src.worker.client import WorkerClient


@pytest.fixture(autouse=True)
def reset_worker_manager():
    """Ensure clean worker state between tests."""
    worker_manager._workers.clear()
    worker_manager._worker_tasks.clear()
    yield
    worker_manager._workers.clear()
    worker_manager._worker_tasks.clear()


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_two_workers_concurrent_registration(app):
    """Verify Worker Alpha and Worker Beta can register concurrently without race conditions."""
    transport = ASGITransport(app=app)
    auth_headers = {"X-Worker-Token": settings.controller_secret_key}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Worker Alpha (Laptop 2)
        alpha_payload = {
            "worker_id": "worker-laptop-01",
            "worker_name": "Worker Alpha",
            "hostname": "laptop-alpha",
            "ip_address": "192.168.1.101",
            "explicit_consent_granted": True,
        }
        # Worker Beta (Laptop 3)
        beta_payload = {
            "worker_id": "worker-laptop-02",
            "worker_name": "Worker Beta",
            "hostname": "laptop-beta",
            "ip_address": "192.168.1.102",
            "explicit_consent_granted": True,
        }

        # Concurrently register both workers
        resp_alpha, resp_beta = await asyncio.gather(
            client.post("/api/v1/workers/register", json=alpha_payload, headers=auth_headers),
            client.post("/api/v1/workers/register", json=beta_payload, headers=auth_headers),
        )

        assert resp_alpha.status_code == 201
        assert resp_alpha.json()["worker_id"] == "worker-laptop-01"
        assert resp_beta.status_code == 201
        assert resp_beta.json()["worker_id"] == "worker-laptop-02"

        # Verify both appear in controller worker list
        list_resp = await client.get("/api/v1/workers")
        assert list_resp.status_code == 200
        workers = list_resp.json()
        assert len(workers) == 2
        worker_ids = {w["worker_id"] for w in workers}
        assert "worker-laptop-01" in worker_ids
        assert "worker-laptop-02" in worker_ids


@pytest.mark.asyncio
async def test_authentication_failure_rejection(app):
    """Verify that registration and heartbeats without valid shared secret are rejected (401)."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "worker_id": "worker-unauth-01",
            "worker_name": "Unauthenticated Worker",
            "hostname": "rogue-host",
            "explicit_consent_granted": True,
        }

        # 1. Missing auth header and missing body token -> 401
        resp_no_auth = await client.post("/api/v1/workers/register", json=payload)
        assert resp_no_auth.status_code == 401
        assert "Unauthorized" in resp_no_auth.json()["detail"]

        # 2. Wrong auth token in header -> 401
        resp_wrong_header = await client.post(
            "/api/v1/workers/register",
            json=payload,
            headers={"X-Worker-Token": "invalid-secret-key-12345"},
        )
        assert resp_wrong_header.status_code == 401

        # 3. Wrong auth token in payload -> 401
        payload_wrong_body = {**payload, "auth_token": "wrong-secret"}
        resp_wrong_body = await client.post("/api/v1/workers/register", json=payload_wrong_body)
        assert resp_wrong_body.status_code == 401

        # 4. Correct auth token in body -> 201 Success
        payload_correct_body = {**payload, "auth_token": settings.controller_secret_key}
        resp_ok = await client.post("/api/v1/workers/register", json=payload_correct_body)
        assert resp_ok.status_code == 201


@pytest.mark.asyncio
async def test_duplicate_worker_id_conflict_rejection(app):
    """Verify that a second machine trying to use an active worker ID is rejected with 409 Conflict."""
    transport = ASGITransport(app=app)
    auth_headers = {"X-Worker-Token": settings.controller_secret_key}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First registration on Host A
        host_a_payload = {
            "worker_id": "worker-laptop-01",
            "worker_name": "Worker Alpha Primary",
            "hostname": "laptop-alpha-original",
            "ip_address": "192.168.1.101",
            "explicit_consent_granted": True,
        }
        resp1 = await client.post("/api/v1/workers/register", json=host_a_payload, headers=auth_headers)
        assert resp1.status_code == 201

        # Conflicting registration attempt on Host B with same worker ID
        host_b_conflict = {
            "worker_id": "worker-laptop-01",
            "worker_name": "Imposter Alpha",
            "hostname": "laptop-imposter",
            "ip_address": "192.168.1.199",
            "explicit_consent_granted": True,
        }
        resp2 = await client.post("/api/v1/workers/register", json=host_b_conflict, headers=auth_headers)
        assert resp2.status_code == 409
        assert "conflict" in resp2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_same_host_reconnection_and_session_renewal(app):
    """Verify that the same machine can safely re-register (e.g. after restart or Wi-Fi reconnect)."""
    transport = ASGITransport(app=app)
    auth_headers = {"X-Worker-Token": settings.controller_secret_key}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "worker_id": "worker-laptop-01",
            "worker_name": "Worker Alpha",
            "hostname": "laptop-alpha",
            "ip_address": "192.168.1.101",
            "explicit_consent_granted": True,
        }
        # Initial registration
        resp1 = await client.post("/api/v1/workers/register", json=payload, headers=auth_headers)
        assert resp1.status_code == 201

        # Same host re-registers (e.g. client application restarted)
        resp2 = await client.post("/api/v1/workers/register", json=payload, headers=auth_headers)
        assert resp2.status_code == 201
        assert resp2.json()["worker_id"] == "worker-laptop-01"


@pytest.mark.asyncio
async def test_heartbeat_expiry_and_stale_reaping():
    """Verify that workers exceeding the heartbeat timeout are marked OFFLINE."""
    req = WorkerRegistrationRequest(
        worker_id="worker-timeout-01",
        worker_name="Timeout Test Worker",
        hostname="test-host",
        explicit_consent_granted=True,
    )
    await worker_manager.register_worker(req)

    worker = await worker_manager.get_worker("worker-timeout-01")
    assert worker.status == WorkerStatus.ONLINE

    # Artificially age the heartbeat past timeout
    worker.last_heartbeat = current_utc_time() - timedelta(seconds=settings.heartbeat_timeout_seconds + 5)

    stale = await worker_manager.reap_stale_workers()
    assert "worker-timeout-01" in stale

    # Verify status changed to OFFLINE
    updated = await worker_manager.get_worker("worker-timeout-01")
    assert updated.status == WorkerStatus.OFFLINE
    assert updated.connection_status == "DISCONNECTED"


@pytest.mark.asyncio
async def test_worker_task_isolation(app):
    """Verify task queue isolation: Worker Beta cannot receive tasks queued for Worker Alpha."""
    transport = ASGITransport(app=app)
    auth_headers = {"X-Worker-Token": settings.controller_secret_key}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register Worker Alpha and Worker Beta
        await client.post(
            "/api/v1/workers/register",
            json={
                "worker_id": "worker-alpha",
                "worker_name": "Alpha",
                "hostname": "host-alpha",
                "explicit_consent_granted": True,
            },
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/workers/register",
            json={
                "worker_id": "worker-beta",
                "worker_name": "Beta",
                "hostname": "host-beta",
                "explicit_consent_granted": True,
            },
            headers=auth_headers,
        )

        # Assign task strictly to Worker Alpha
        task_payload = {
            "worker_id": "worker-alpha",
            "title": "Reverse Linked List",
            "description": "Implement in-place reversal in Python",
        }
        assign_resp = await client.post("/api/v1/tasks/assign", json=task_payload, headers=auth_headers)
        assert assign_resp.status_code == 201

        # Worker Beta polls -> must have NO task
        beta_poll = await client.get("/api/v1/tasks/poll/worker-beta", headers=auth_headers)
        assert beta_poll.status_code == 200
        assert beta_poll.json()["has_task"] is False
        assert beta_poll.json()["task"] is None

        # Worker Alpha polls -> must receive the assigned task
        alpha_poll = await client.get("/api/v1/tasks/poll/worker-alpha", headers=auth_headers)
        assert alpha_poll.status_code == 200
        assert alpha_poll.json()["has_task"] is True
        assert alpha_poll.json()["task"]["title"] == "Reverse Linked List"
        assert alpha_poll.json()["task"]["worker_id"] == "worker-alpha"

        # Subsequent poll from Alpha -> queue is now empty
        alpha_poll_empty = await client.get("/api/v1/tasks/poll/worker-alpha", headers=auth_headers)
        assert alpha_poll_empty.json()["has_task"] is False


@pytest.mark.asyncio
async def test_remote_emergency_stop_multi_worker(app):
    """Verify emergency stop propagates to multiple workers and halts their operations."""
    transport = ASGITransport(app=app)
    auth_headers = {"X-Worker-Token": settings.controller_secret_key}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register Alpha and Beta
        for wid in ("worker-alpha", "worker-beta"):
            await client.post(
                "/api/v1/workers/register",
                json={
                    "worker_id": wid,
                    "worker_name": wid.title(),
                    "hostname": f"host-{wid}",
                    "explicit_consent_granted": True,
                },
                headers=auth_headers,
            )

        # Trigger Global Emergency Stop
        stop_resp = await client.post(
            "/api/v1/workers/emergency-stop",
            json={"reason": "Safety drill trigger"},
        )
        assert stop_resp.status_code == 200
        affected = stop_resp.json()["affected_workers"]
        assert "worker-alpha" in affected
        assert "worker-beta" in affected

        # Next heartbeats must return EMERGENCY_STOP command
        hb_alpha = await client.post(
            "/api/v1/workers/heartbeat",
            json={"worker_id": "worker-alpha", "status": "ONLINE", "permission_active": True},
            headers=auth_headers,
        )
        assert hb_alpha.json()["command"] == "EMERGENCY_STOP"

        hb_beta = await client.post(
            "/api/v1/workers/heartbeat",
            json={"worker_id": "worker-beta", "status": "ONLINE", "permission_active": True},
            headers=auth_headers,
        )
        assert hb_beta.json()["command"] == "EMERGENCY_STOP"


@pytest.mark.asyncio
async def test_controller_dashboard_endpoints(app):
    """Verify central dashboard serves responsive HTML and does not expose secrets."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test GET /
        resp_root = await client.get("/")
        assert resp_root.status_code == 200
        assert "text/html" in resp_root.headers.get("content-type", "")
        assert "NIAT CodePilot Central Controller" in resp_root.text

        # Test GET /dashboard
        resp_dash = await client.get("/dashboard")
        assert resp_dash.status_code == 200
        assert "text/html" in resp_dash.headers.get("content-type", "")

        # Verify sensitive secrets are NEVER exposed in the HTML output
        assert settings.controller_secret_key not in resp_dash.text
        if settings.gemini_api_key:
            assert settings.gemini_api_key not in resp_dash.text
        if settings.openai_api_key:
            assert settings.openai_api_key not in resp_dash.text


@pytest.mark.asyncio
async def test_worker_client_auto_reconnect_resilience():
    """Verify WorkerClient automatically attempts re-registration when heartbeat is unacknowledged."""
    client = WorkerClient(
        worker_id="worker-resilient-01",
        worker_name="Resilient Worker",
        controller_url="http://test",
    )
    client._explicit_consent = True

    # Mock client register call
    register_called = []

    async def mock_register(explicit_consent):
        register_called.append(explicit_consent)
        client._is_registered = True
        client.status = WorkerStatus.ONLINE

    client.register = mock_register

    # Simulate reconnect
    success = await client.reconnect(max_attempts=2, backoff_seconds=0.01)
    assert success is True
    assert len(register_called) == 1
    assert client.is_registered is True
    assert client.status == WorkerStatus.ONLINE


@pytest.mark.asyncio
async def test_auth_bearer_token_and_header_variants(app):
    """Regression test: verify registration succeeds with Authorization: Bearer, X-Worker-Token, and payload."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Authorization: Bearer <token>
        bearer_payload = {
            "worker_id": "worker-bearer-01",
            "worker_name": "Bearer Worker",
            "hostname": "host-bearer",
            "explicit_consent_granted": True,
        }
        resp = await client.post(
            "/api/v1/workers/register",
            json=bearer_payload,
            headers={"Authorization": f"Bearer {settings.controller_secret_key}"},
        )
        assert resp.status_code == 201

        # 2. X-Worker-Token with surrounding whitespace or quotes (normalized)
        header_payload = {
            "worker_id": "worker-header-02",
            "worker_name": "Header Worker",
            "hostname": "host-header",
            "explicit_consent_granted": True,
        }
        resp = await client.post(
            "/api/v1/workers/register",
            json=header_payload,
            headers={"X-Worker-Token": f"  \"{settings.controller_secret_key}\"  "},
        )
        assert resp.status_code == 201

        # 3. Invalid Bearer token -> 401
        invalid_bearer = {
            "worker_id": "worker-bearer-bad",
            "worker_name": "Bad Bearer Worker",
            "hostname": "host-bearer-bad",
            "explicit_consent_granted": True,
        }
        resp = await client.post(
            "/api/v1/workers/register",
            json=invalid_bearer,
            headers={"Authorization": "Bearer totally-wrong-token-value"},
        )
        assert resp.status_code == 401
        assert "Unauthorized" in resp.json()["detail"]


def test_env_path_resolution_from_subdirectories(monkeypatch):
    """Regression test: verify AppSettings resolves project root .env even if cwd is scripts/."""
    import os
    from pathlib import Path
    from src.common.config import AppSettings, PROJECT_ROOT, _ENV_FILE

    # Ensure PROJECT_ROOT points to repo root and _ENV_FILE exists
    assert PROJECT_ROOT.is_dir()
    assert _ENV_FILE.name == ".env"

    # Simulate running from the scripts/ subdirectory
    scripts_dir = PROJECT_ROOT / "scripts"
    monkeypatch.chdir(scripts_dir)

    # Instantiate new AppSettings from within scripts/
    sub_settings = AppSettings()
    # It must load the same secret key from project root .env, not fallback default
    assert sub_settings.controller_secret_key == settings.controller_secret_key
    assert sub_settings.controller_secret_key != "niat-default-secret-key-change-in-prod"
