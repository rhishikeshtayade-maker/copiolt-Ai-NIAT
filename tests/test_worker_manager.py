"""Unit tests for the WorkerManager service."""

import pytest
from datetime import datetime, timedelta, timezone
from src.common.constants import WorkerCommand, WorkerStatus
from src.common.schemas import (
    HeartbeatRequest,
    WorkerRegistrationRequest,
    current_utc_time,
)
from src.controller.manager import WorkerManager


@pytest.mark.asyncio
async def test_worker_registration_success():
    manager = WorkerManager()
    req = WorkerRegistrationRequest(
        worker_id="worker-w1",
        worker_name="Worker 1",
        hostname="laptop-w1",
        explicit_consent_granted=True,
    )
    resp = await manager.register_worker(req)
    assert resp.status == "registered"
    assert resp.worker_id == "worker-w1"

    worker = await manager.get_worker("worker-w1")
    assert worker is not None
    assert worker.status == WorkerStatus.ONLINE
    assert worker.permission_active is True


@pytest.mark.asyncio
async def test_worker_registration_denied_without_consent():
    manager = WorkerManager()
    req = WorkerRegistrationRequest(
        worker_id="worker-denied",
        worker_name="Worker Denied",
        hostname="laptop-denied",
        explicit_consent_granted=False,
    )
    with pytest.raises(PermissionError):
        await manager.register_worker(req)


@pytest.mark.asyncio
async def test_heartbeat_processing():
    manager = WorkerManager()
    req = WorkerRegistrationRequest(
        worker_id="worker-hb",
        worker_name="Worker HB",
        hostname="laptop-hb",
        explicit_consent_granted=True,
    )
    await manager.register_worker(req)

    hb = HeartbeatRequest(
        worker_id="worker-hb",
        status=WorkerStatus.ONLINE,
        cpu_percent=25.0,
        memory_percent=55.0,
        permission_active=True,
    )
    hb_resp = await manager.process_heartbeat(hb)
    assert hb_resp.acknowledged is True
    assert hb_resp.command == WorkerCommand.NONE

    worker = await manager.get_worker("worker-hb")
    assert worker.cpu_percent == 25.0
    assert worker.memory_percent == 55.0


@pytest.mark.asyncio
async def test_emergency_stop_trigger():
    manager = WorkerManager()
    req = WorkerRegistrationRequest(
        worker_id="worker-es",
        worker_name="Worker ES",
        hostname="laptop-es",
        explicit_consent_granted=True,
    )
    await manager.register_worker(req)

    affected = await manager.trigger_emergency_stop(target_worker_id="worker-es")
    assert "worker-es" in affected

    worker = await manager.get_worker("worker-es")
    assert worker.status == WorkerStatus.EMERGENCY_STOPPED
    assert worker.permission_active is False

    # Next heartbeat from this worker should receive the EMERGENCY_STOP command
    hb = HeartbeatRequest(worker_id="worker-es", status=WorkerStatus.ONLINE)
    hb_resp = await manager.process_heartbeat(hb)
    assert hb_resp.command == WorkerCommand.EMERGENCY_STOP


@pytest.mark.asyncio
async def test_reap_stale_workers():
    manager = WorkerManager()
    manager._timeout_seconds = 1.0  # 1 second timeout

    req = WorkerRegistrationRequest(
        worker_id="worker-stale",
        worker_name="Worker Stale",
        hostname="laptop-stale",
        explicit_consent_granted=True,
    )
    await manager.register_worker(req)

    # Fake the last_heartbeat to be in the past
    worker = await manager.get_worker("worker-stale")
    worker.last_heartbeat = current_utc_time() - timedelta(seconds=5)

    stale = await manager.reap_stale_workers()
    assert "worker-stale" in stale

    worker = await manager.get_worker("worker-stale")
    assert worker.status == WorkerStatus.OFFLINE
