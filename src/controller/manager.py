"""Worker management service: registers, tracks health, and issues control commands."""

import asyncio
import secrets
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from src.common.config import settings
from src.common.constants import WorkerCommand, WorkerStatus
from src.common.logger import get_logger
from src.common.schemas import (
    HeartbeatRequest,
    HeartbeatResponse,
    TaskAssignmentRequest,
    TaskAssignmentResponse,
    TaskItem,
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
        self._worker_tasks: Dict[str, List[TaskItem]] = {}
        self._lock = asyncio.Lock()
        self._timeout_seconds = settings.heartbeat_timeout_seconds

    def validate_auth(self, token: Optional[str]) -> bool:
        """Verify that the provided token matches the configured controller secret key in constant time."""
        configured_secret = (settings.controller_secret_key or "").strip().strip("'\"")
        if not configured_secret:
            return True  # No auth required if secret is unset
        if not token:
            return False
        clean_token = str(token).strip().strip("'\"")
        return secrets.compare_digest(clean_token, configured_secret)

    async def register_worker(
        self, req: WorkerRegistrationRequest
    ) -> WorkerRegistrationResponse:
        """Register a new worker laptop after verifying explicit consent and unique identity."""
        async with self._lock:
            if not req.explicit_consent_granted:
                logger.warning(
                    f"Registration rejected for '{req.worker_id}': User consent was not granted."
                )
                raise PermissionError("Explicit user permission is required to register a worker.")

            now = current_utc_time()

            # Prevent duplicate worker ID conflicts from different hosts
            if req.worker_id in self._workers:
                existing = self._workers[req.worker_id]
                # If existing worker is currently active on a different machine, reject conflict
                if (
                    existing.status not in (WorkerStatus.OFFLINE, WorkerStatus.EMERGENCY_STOPPED)
                    and existing.hostname != req.hostname
                ):
                    logger.warning(
                        f"Registration conflict for '{req.worker_id}': Already active on host '{existing.hostname}'."
                    )
                    raise ValueError(
                        f"Worker ID conflict: Worker '{req.worker_id}' is already active on host '{existing.hostname}' "
                        f"({existing.ip_address}). Each laptop must have a unique WORKER_ID."
                    )
                logger.info(
                    f"Worker '{req.worker_id}' re-registering from host '{req.hostname}' (previous status: {existing.status.value})"
                )

            worker_info = WorkerInfo(
                worker_id=req.worker_id,
                worker_name=req.worker_name,
                hostname=req.hostname,
                ip_address=req.ip_address,
                status=WorkerStatus.ONLINE,
                connection_status="CONNECTED",
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
            worker.connection_status = "CONNECTED"
            if hb.current_task_id:
                worker.current_task_id = hb.current_task_id

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
                    worker.connection_status = "DISCONNECTED"
                    stale_workers.append(wid)
                    logger.warning(
                        f"Worker '{wid}' marked OFFLINE: no heartbeat for {elapsed:.1f}s"
                    )

        return stale_workers

    # --- Worker-Scoped Task Queue Methods ---

    async def assign_task(self, req: TaskAssignmentRequest) -> TaskAssignmentResponse:
        """Assign and queue a task specifically for one worker machine."""
        async with self._lock:
            if req.worker_id not in self._workers:
                raise ValueError(f"Target worker '{req.worker_id}' is not registered.")

            task = TaskItem(
                task_id=f"task-{uuid.uuid4().hex[:8]}",
                worker_id=req.worker_id,
                title=req.title,
                description=req.description,
                code_context=req.code_context,
                status="pending",
                created_at=current_utc_time(),
            )

            if req.worker_id not in self._worker_tasks:
                self._worker_tasks[req.worker_id] = []
            self._worker_tasks[req.worker_id].append(task)

            logger.info(f"Task '{task.task_id}' assigned specifically to worker '{req.worker_id}'")
            return TaskAssignmentResponse(
                task_id=task.task_id,
                worker_id=task.worker_id,
                status="assigned",
                created_at=task.created_at,
                message=f"Task queued for worker '{req.worker_id}'",
            )

    async def poll_task_for_worker(self, worker_id: str) -> Optional[TaskItem]:
        """Retrieve the next pending task assigned strictly to this worker.

        Ensures workers cannot access or receive tasks assigned to another worker.
        """
        async with self._lock:
            tasks = self._worker_tasks.get(worker_id, [])
            for task in tasks:
                if task.status == "pending":
                    task.status = "in_progress"
                    return task
            return None

    async def get_tasks_for_worker(self, worker_id: str) -> List[TaskItem]:
        """List tasks assigned to a specific worker."""
        async with self._lock:
            return list(self._worker_tasks.get(worker_id, []))

    async def clear_all(self) -> None:
        """Reset state (useful for test isolation)."""
        async with self._lock:
            self._workers.clear()
            self._worker_tasks.clear()


# Global worker manager instance
worker_manager = WorkerManager()
