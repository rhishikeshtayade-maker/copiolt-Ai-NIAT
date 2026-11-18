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
    TaskItem,
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
        secret_key: Optional[str] = None,
        on_command_received: Optional[Callable[[WorkerCommand], None]] = None,
        on_status_changed: Optional[Callable[[WorkerStatus, str], None]] = None,
    ) -> None:
        self.worker_id = worker_id or settings.worker_id
        self.worker_name = worker_name or settings.worker_name
        self.controller_url = (controller_url or settings.controller_url).rstrip("/")
        self.secret_key = (secret_key or settings.controller_secret_key or "").strip().strip("'\"")
        self.on_command_received = on_command_received
        self.on_status_changed = on_status_changed

        self.status = WorkerStatus.REGISTERED
        self._is_registered = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._permission_active: bool = False
        self._explicit_consent: bool = False
        self._consecutive_failures: int = 0
        self._is_reconnecting: bool = False

    @property
    def is_registered(self) -> bool:
        return self._is_registered

    @property
    def is_reconnecting(self) -> bool:
        return self._is_reconnecting

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

    def _auth_headers(self) -> dict:
        """Return headers with shared secret token for controller authentication."""
        return {
            "X-Worker-Token": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
        }

    async def register(self, explicit_consent: bool) -> WorkerRegistrationResponse:
        """Register this worker machine with the central controller using shared secret auth."""
        self._explicit_consent = explicit_consent
        hostname = socket.gethostname()
        ip_addr = socket.gethostbyname(hostname) if hostname else "127.0.0.1"

        req = WorkerRegistrationRequest(
            worker_id=self.worker_id,
            worker_name=self.worker_name,
            hostname=hostname,
            ip_address=ip_addr,
            capabilities=["screen_capture", "ai_reasoning"],
            explicit_consent_granted=explicit_consent,
            auth_token=self.secret_key,
        )

        url = f"{self.controller_url}/api/v1/workers/register"
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    url,
                    json=req.model_dump(mode="json"),
                    headers=self._auth_headers(),
                )
                resp.raise_for_status()
                data = WorkerRegistrationResponse.model_validate(resp.json())
                self._is_registered = True
                self.status = WorkerStatus.ONLINE
                self._consecutive_failures = 0
                logger.info(
                    f"Successfully registered worker '{self.worker_id}' with controller at {self.controller_url}"
                )
                if self.on_status_changed:
                    self.on_status_changed(WorkerStatus.ONLINE, "Registered and Online")
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
        """Send a single health heartbeat to the controller, handling auto-reconnect if needed."""
        cpu, mem = self._get_system_metrics()
        hb = HeartbeatRequest(
            worker_id=self.worker_id,
            status=self.status,
            cpu_percent=cpu,
            memory_percent=mem,
            timestamp=current_utc_time(),
            permission_active=self._permission_active,
            auth_token=self.secret_key,
        )

        url = f"{self.controller_url}/api/v1/workers/heartbeat"
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.post(
                    url,
                    json=hb.model_dump(mode="json"),
                    headers=self._auth_headers(),
                )
                resp.raise_for_status()
                data = HeartbeatResponse.model_validate(resp.json())

                # If controller restarted or dropped session
                if not data.acknowledged:
                    logger.warning(
                        f"Heartbeat unacknowledged by controller: {data.message}. Initiating auto-reconnection..."
                    )
                    self._is_registered = False
                    if self._explicit_consent and not self._is_reconnecting:
                        await self.reconnect()
                    return data

                # Reset failure counter on successful heartbeat
                self._consecutive_failures = 0
                if self.status != WorkerStatus.ONLINE and self.status != WorkerStatus.EMERGENCY_STOPPED:
                    self.status = WorkerStatus.ONLINE
                    if self.on_status_changed:
                        self.on_status_changed(WorkerStatus.ONLINE, "Online")

                # Check if controller issued a command
                if data.command != WorkerCommand.NONE:
                    logger.warning(
                        f"Command received from controller: {data.command.value}"
                    )
                    if data.command == WorkerCommand.EMERGENCY_STOP:
                        self.status = WorkerStatus.EMERGENCY_STOPPED
                        self._permission_active = False
                    if self.on_command_received:
                        self.on_command_received(data.command)

                return data
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as net_err:
                self._consecutive_failures += 1
                logger.warning(
                    f"Heartbeat network failure ({self._consecutive_failures}): {net_err}"
                )
                if self._consecutive_failures >= 2 and self.status != WorkerStatus.OFFLINE:
                    self.status = WorkerStatus.OFFLINE
                    if self.on_status_changed:
                        self.on_status_changed(WorkerStatus.OFFLINE, "Network connection lost")
                raise
            except Exception as e:
                logger.debug(f"Heartbeat dispatch failed: {e}")
                raise

    async def reconnect(self, max_attempts: int = 3, backoff_seconds: float = 1.0) -> bool:
        """Automatically attempt to reconnect and re-register after temporary network loss."""
        if not self._explicit_consent:
            logger.warning("Reconnection aborted: Explicit user consent is required.")
            return False

        self._is_reconnecting = True
        logger.info(f"Reconnecting worker '{self.worker_id}' to controller...")
        if self.on_status_changed:
            self.on_status_changed(WorkerStatus.OFFLINE, "Reconnecting to controller...")

        for attempt in range(1, max_attempts + 1):
            try:
                await self.register(explicit_consent=self._explicit_consent)
                self._is_reconnecting = False
                self._consecutive_failures = 0
                logger.info(f"Worker '{self.worker_id}' reconnected successfully on attempt {attempt}.")
                return True
            except Exception as e:
                logger.warning(f"Reconnection attempt {attempt}/{max_attempts} failed: {e}")
                if attempt < max_attempts:
                    await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))

        self._is_reconnecting = False
        return False

    async def poll_task(self) -> Optional[TaskItem]:
        """Poll the central controller for tasks assigned strictly to this worker.

        Guarantees isolation so workers only receive their own assigned tasks.
        """
        url = f"{self.controller_url}/api/v1/tasks/poll/{self.worker_id}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(url, headers=self._auth_headers())
                resp.raise_for_status()
                data = resp.json()
                if data.get("has_task") and data.get("task"):
                    return TaskItem.model_validate(data["task"])
                return None
            except Exception as e:
                logger.debug(f"Task poll failed: {e}")
                return None

    async def start_heartbeat_loop(self) -> None:
        """Run periodic heartbeat transmission in the background with auto-reconnection."""
        self._stop_event.clear()
        interval = settings.heartbeat_interval_seconds

        logger.info(
            f"Starting heartbeat loop for '{self.worker_id}' (interval: {interval}s)"
        )

        while not self._stop_event.is_set():
            try:
                if self._is_registered:
                    await self.send_heartbeat()
                elif self._explicit_consent and not self._is_reconnecting:
                    # Try to re-register if dropped
                    await self.reconnect(max_attempts=1)
            except Exception as e:
                logger.warning(f"Heartbeat loop tick error: {e}")

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
