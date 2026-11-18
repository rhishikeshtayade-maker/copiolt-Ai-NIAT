"""FastAPI application initialization for the NIAT CodePilot Central Controller."""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.common.config import settings
from src.common.logger import get_logger
from src.controller.manager import worker_manager
from src.controller.routes import dashboard, health, tasks, workers

logger = get_logger("Controller.Main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: starts background monitor to reap stale workers."""
    logger.info("Initializing NIAT CodePilot Controller...")

    stop_event = asyncio.Event()

    async def monitor_heartbeats():
        while not stop_event.is_set():
            try:
                await asyncio.sleep(settings.heartbeat_interval_seconds)
                stale = await worker_manager.reap_stale_workers()
                if stale:
                    logger.info(f"Reaped stale workers: {stale}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat monitor loop: {e}")

    task = asyncio.create_task(monitor_heartbeats())
    logger.info(
        f"Controller started on {settings.controller_host}:{settings.controller_port}"
    )

    yield

    logger.info("Shutting down Controller background tasks...")
    stop_event.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Controller shutdown complete.")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="NIAT CodePilot Central Controller",
        description=(
            "Central controller for distributed AI coding assistant. "
            "Manages worker registration, health heartbeats, and safety policies."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include route modules
    app.include_router(dashboard.router)
    app.include_router(health.router)
    app.include_router(workers.router)
    app.include_router(tasks.router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.controller.main:app",
        host=settings.controller_host,
        port=settings.controller_port,
        reload=False,
    )
