"""System info API endpoints."""

from typing import Any

from fastapi import APIRouter, Request

from backend.app.core.config import settings
from backend.app.core.safety import get_safety_report
from backend.app.simulation.runtime import get_simulation_runtime

router = APIRouter(tags=["System Info"])


@router.get("/info")
async def get_system_info(request: Request) -> dict[str, Any]:
    """Return platform metadata, safety report, and simulation engine status.

    The engine status is read from the application-scoped runtime, the same
    source the Plant Overview reads. A read of this endpoint must never
    report an engine other than the one that owns the plant: the HMI takes
    the engine state it shows the operator from here, so a status resolved
    from any other runtime would tell the operator that a running plant is
    not connected.
    """
    runtime = get_simulation_runtime(request=request)
    return {
        "project_name": settings.PROJECT_NAME,
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
        "safety": get_safety_report(),
        "engine": runtime.status(),
    }
