"""Health check API endpoints."""

from typing import Any

from backend.app.core.safety import get_safety_report
from fastapi import APIRouter, Response, status

router = APIRouter(tags=["Health"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, Any]:
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "service": "powertwin-backend",
        "safety": get_safety_report(),
    }


@router.get("/health/liveness", status_code=status.HTTP_200_OK)
async def liveness_probe() -> dict[str, str]:
    """Liveness probe endpoint."""
    return {"status": "ok"}


@router.get("/health/readiness", status_code=status.HTTP_200_OK)
async def readiness_probe(response: Response) -> dict[str, Any]:
    """Readiness probe endpoint ensuring system components are initialized."""
    safety_report = get_safety_report()
    if not safety_report["simulation_only"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unhealthy",
            "reason": "SAFETY_INVARIANT_VIOLATION_SIMULATION_MODE_REQUIRED",
        }

    return {
        "status": "ready",
        "database": "configured",
        "safety": safety_report,
    }
