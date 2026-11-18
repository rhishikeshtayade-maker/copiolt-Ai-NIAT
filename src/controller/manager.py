"""Worker management service: registers, tracks health, and issues control commands."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
from src.common.config import settings
from src.common.constants import WorkerCommand, WorkerStatus
from src.common.logger import get_logger
from src.common.schemas import (
    HeartbeatRequest,
    HeartbeatResponse,
    WorkerInfo,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
    current_utc_time,
)
from src.controller.db import db_service

logger = get_logger("Controller.WorkerManager")


class WorkerManager:
    """Central repository and coordinator for all connected worker machines."""

    def __init__(self) -> None:
        self._workers: Dict[str, WorkerInfo] = {}
        self._lock = asyncio.Lock()
        self._timeout_seconds = settings.heartbeat_timeout_seconds

    async def register_worker(
        self, req: WorkerRegistrationRequest
    ) -> WorkerRegistrationResponse:
        """Register a new worker laptop after verifying explicit consent."""
        async with self._lock:
            if not req.explicit_consent_granted:
                logger.warning(
                    f"Registration rejected for '{req.worker_id}': User consent was not granted."
                )
                raise PermissionError("Explicit user permission is required to register a worker.")

            now = current_utc_time()
            worker_info = WorkerInfo(
                worker_id=req.worker_id,
                worker_name=req.worker_name,
                hostname=req.hostname,
                ip_address=req.ip_address,
                status=WorkerStatus.ONLINE,
                last_heartbeat=now,
                registered_at=now,
                capabilities=req.capabilities,
                permission_active=req.explicit_consent_granted,
                pending_command=WorkerCommand.NONE,
            )

            self._workers[req.worker_id] = worker_info
            logger.info(
                f"Worker registered: {req.worker_id} ({req.worker_name}) from host {req.hostname}"
            )

            # Audit log to Supabase/local
            await db_service.log_worker_event(
                worker_id=req.worker_id,
                event_type="WORKER_REGISTERED",
                details={
                    "hostname": req.hostname,
                    "ip_address": req.ip_address,
                    "capabilities": req.capabilities,
                },
            )

            return WorkerRegistrationResponse(
                status="registered",
                worker_id=req.worker_id,
                heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
                registered_at=now,
                message=f"Successfully registered worker '{req.worker_name}'",
            )

    async def process_heartbeat(self, hb: HeartbeatRequest) -> HeartbeatResponse:
        """Process a heartbeat from a worker, updating its health status and metrics."""
        async with self._lock:
            now = current_utc_time()
            worker = self._workers.get(hb.worker_id)

            if not worker:
                logger.warning(f"Heartbeat received from unknown worker '{hb.worker_id}'.")
                return HeartbeatResponse(
                    acknowledged=False,
                    command=WorkerCommand.STOP,
                    server_time=now,
                    message="Worker not registered. Please register first.",
                )

            # Update worker status and metrics
            worker.last_heartbeat = now
            worker.cpu_percent = hb.cpu_percent
            worker.memory_percent = hb.memory_percent
            worker.permission_active = hb.permission_active

            # Preserve EMERGENCY_STOPPED state if already stopped
            if worker.status != WorkerStatus.EMERGENCY_STOPPED:
                worker.status = hb.status

            # Retrieve and clear any pending command
            command_to_send = worker.pending_command
            worker.pending_command = WorkerCommand.NONE

            logger.debug(
                f"Heartbeat from {hb.worker_id}: status={worker.status}, "
                f"CPU={hb.cpu_percent}%, Mem={hb.memory_percent}%, Cmd={command_to_send}"
            )

            return HeartbeatResponse(
                acknowledged=True,
                command=command_to_send,
                server_time=now,
                message="Heartbeat acknowledged",
            )

    async def trigger_emergency_stop(
        self, target_worker_id: Optional[str] = None, reason: str = "Operator emergency stop"
    ) -> List[str]:
        """Trigger an emergency stop across one or all connected workers."""
        affected: List[str] = []
        async with self._lock:
            targets = (
                [target_worker_id]
                if target_worker_id and target_worker_id in self._workers
                else list(self._workers.keys())
            )

            for wid in targets:
                worker = self._workers[wid]
                worker.status = WorkerStatus.EMERGENCY_STOPPED
                worker.pending_command = WorkerCommand.EMERGENCY_STOP
                worker.permission_active = False
                affected.append(wid)
                logger.critical(
                    f"EMERGENCY STOP issued for worker '{wid}'. Reason: {reason}"
                )
                await db_service.log_worker_event(
                    worker_id=wid,
                    event_type="EMERGENCY_STOP",
                    details={"reason": reason},
                )

        return affected

    async def get_all_workers(self) -> List[WorkerInfo]:
        """Return list of all registered workers with current status."""
        async with self._lock:
            return list(self._workers.values())

    async def get_worker(self, worker_id: str) -> Optional[WorkerInfo]:
        """Retrieve state for a specific worker."""
        async with self._lock:
            return self._workers.get(worker_id)

    async def reap_stale_workers(self) -> List[str]:
        """Identify and mark workers that have exceeded heartbeat timeout."""
        stale_workers: List[str] = []
        async with self._lock:
            now = current_utc_time()
            for wid, worker in self._workers.items():
                if worker.status in (WorkerStatus.OFFLINE, WorkerStatus.EMERGENCY_STOPPED):
                    continue
                elapsed = (now - worker.last_heartbeat).total_seconds()
                if elapsed > self._timeout_seconds:
                    worker.status = WorkerStatus.OFFLINE
                    stale_workers.append(wid)
                    logger.warning(
                        f"Worker '{wid}' marked OFFLINE: no heartbeat for {elapsed:.1f}s"
                    )

        return stale_workers


# Global worker manager instance
worker_manager = WorkerManager()
