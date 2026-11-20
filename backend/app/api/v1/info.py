"""System info API endpoints."""

from typing import Any

from fastapi import APIRouter

from backend.app.core.config import settings
from backend.app.core.safety import get_safety_report
from backend.app.simulation.engine_stub import engine_stub

router = APIRouter(tags=["System Info"])


@router.get("/info")
async def get_system_info() -> dict[str, Any]:
    """Return platform metadata, safety report, and simulation engine status."""
    return {
        "project_name": settings.PROJECT_NAME,
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
        "safety": get_safety_report(),
        "engine": engine_stub.get_status(),
    }
