"""Worker client communicating with the central Controller via HTTP REST."""

import asyncio
import socket
from typing import Callable, Optional
import httpx
try:
    import psutil
except ImportError:
    psutil = None

from src.common.config import settings
from src.common.constants import WorkerCommand, WorkerStatus
from src.common.logger import get_logger
from src.common.schemas import (
    HeartbeatRequest,
    HeartbeatResponse,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
    current_utc_time,
)

logger = get_logger("Worker.Client")


class WorkerClient:
    """Manages connection, registration, and heartbeat pulse with the Central Controller."""

    def __init__(
        self,
        worker_id: Optional[str] = None,
        worker_name: Optional[str] = None,
        controller_url: Optional[str] = None,
        on_command_received: Optional[Callable[[WorkerCommand], None]] = None,
    ) -> None:
        self.worker_id = worker_id or settings.worker_id
        self.worker_name = worker_name or settings.worker_name
        self.controller_url = (controller_url or settings.controller_url).rstrip("/")
        self.on_command_received = on_command_received

        self.status = WorkerStatus.REGISTERED
        self._is_registered = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._permission_active: bool = False

    @property
    def is_registered(self) -> bool:
        return self._is_registered

    def set_permission_active(self, active: bool) -> None:
        """Update current permission state to report in heartbeats."""
        self._permission_active = active

    def _get_system_metrics(self) -> tuple[Optional[float], Optional[float]]:
        """Collect current CPU and Memory usage percentages safely."""
        if psutil:
            try:
                cpu = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory().percent
                return cpu, mem
            except Exception:
                pass
        return None, None

    async def register(self, explicit_consent: bool) -> WorkerRegistrationResponse:
        """Register this worker machine with the central controller."""
        hostname = socket.gethostname()
        ip_addr = socket.gethostbyname(hostname) if hostname else "127.0.0.1"

        req = WorkerRegistrationRequest(
            worker_id=self.worker_id,
            worker_name=self.worker_name,
            hostname=hostname,
            ip_address=ip_addr,
            capabilities=["screen_capture", "ai_reasoning"],
            explicit_consent_granted=explicit_consent,
        )

        url = f"{self.controller_url}/api/v1/workers/register"
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(url, json=req.model_dump(mode="json"))
                resp.raise_for_status()
                data = WorkerRegistrationResponse.model_validate(resp.json())
                self._is_registered = True
                self.status = WorkerStatus.ONLINE
                logger.info(
                    f"Successfully registered worker '{self.worker_id}' with controller at {self.controller_url}"
                )
                return data
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Failed to register with controller: {e.response.status_code} - {e.response.text}"
                )
                raise
            except Exception as e:
                logger.error(f"Connection error while registering worker: {e}")
                raise

    async def send_heartbeat(self) -> HeartbeatResponse:
        """Send a single health heartbeat to the controller."""
        cpu, mem = self._get_system_metrics()
        hb = HeartbeatRequest(
            worker_id=self.worker_id,
            status=self.status,
            cpu_percent=cpu,
            memory_percent=mem,
            timestamp=current_utc_time(),
            permission_active=self._permission_active,
        )

        url = f"{self.controller_url}/api/v1/workers/heartbeat"
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.post(url, json=hb.model_dump(mode="json"))
                resp.raise_for_status()
                data = HeartbeatResponse.model_validate(resp.json())

                # Check if controller issued a command
                if data.command != WorkerCommand.NONE:
                    logger.warning(
                        f"Command received from controller: {data.command.value}"
                    )
                    if self.on_command_received:
                        self.on_command_received(data.command)

                return data
            except Exception as e:
                logger.debug(f"Heartbeat dispatch failed: {e}")
                raise

    async def start_heartbeat_loop(self) -> None:
        """Run periodic heartbeat transmission in the background."""
        self._stop_event.clear()
        interval = settings.heartbeat_interval_seconds

        logger.info(
            f"Starting heartbeat loop for '{self.worker_id}' (interval: {interval}s)"
        )

        while not self._stop_event.is_set():
            try:
                if self._is_registered:
                    await self.send_heartbeat()
            except Exception as e:
                logger.warning(f"Heartbeat check failed: {e}")

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    def stop_heartbeat_loop(self) -> None:
        """Stop background heartbeat transmission."""
        self._stop_event.set()
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        logger.info("Heartbeat loop stopped.")
