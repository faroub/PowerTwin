"""PowerTwin BESS Platform - FastAPI Main Entrypoint."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import health, router
from backend.app.core.config import settings
from backend.app.core.logging import setup_logging
from backend.app.core.safety import get_safety_report, validate_safety_invariants
from backend.app.simulation.application import close_simulation, init_simulation


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for startup and shutdown events."""
    setup_logging(log_level=settings.LOG_LEVEL, json_logs=settings.JSON_LOGS)
    validate_safety_invariants()
    safety_report = get_safety_report()
    print("===========================================================")
    print(f"  STARTING {settings.PROJECT_NAME}")
    print(f"  MODE: {safety_report['application_mode']}")
    print(f"  SAFETY STATUS: {safety_report['safety_status']}")
    print("===========================================================")
    init_simulation(app)
    yield
    print("Shutting down PowerTwin BESS Platform.")
    close_simulation(app)


def create_application() -> FastAPI:
    """Application factory for FastAPI instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="Modular BESS Simulator and Emulator Platform (SIMULATION ONLY)",
        version="0.1.0",
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
        lifespan=lifespan,
    )

    # Configure Restrictive CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Include Routers
    app.include_router(health.router)
    app.include_router(router.api_v1_router, prefix=settings.API_V1_STR)

    return app


app = create_application()
