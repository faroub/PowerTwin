"""Health check API endpoints."""

from typing import Any

from fastapi import APIRouter, Response, status

from backend.app.core.safety import get_safety_report
from backend.app.historian.db import check_database_readiness

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
    """Readiness probe endpoint ensuring system components are initialized.

    The probe answers a question a merely configured connection never proves:
    whether the historian store actually serves the schema the application
    expects. A migration that has not been run leaves every table of the ORM
    metadata missing, and a database that cannot be reached proves neither:
    the probe names the reason so the operator knows the fix, not only that
    something is wrong.

    The probe never runs a migration: applying the schema is the explicit
    responsibility of the ``migrate`` service of the deployment, started
    deliberately, never by the application and never by each worker at startup.
    """
    safety_report = get_safety_report()
    if not safety_report["simulation_only"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unhealthy",
            "reason": "SAFETY_INVARIANT_VIOLATION_SIMULATION_MODE_REQUIRED",
            "safety": safety_report,
        }

    readiness = await check_database_readiness()
    if readiness.ready:
        return {
            "status": "ready",
            "database": readiness.status,
            "safety": safety_report,
        }

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    payload: dict[str, Any] = {
        "status": "not_ready",
        "database": readiness.status,
        "reason": readiness.reason,
        "safety": safety_report,
    }
    if readiness.missing_tables:
        # The table list is the only information the operator needs to read
        # to know the fix: the migration of the release has to run.
        payload["missing_tables"] = readiness.missing_tables

    return payload
